export const MOVE_CLASSIFICATIONS = [
  "brilliant",
  "great",
  "best",
  "excellent",
  "good",
  "book",
  "inaccuracy",
  "mistake",
  "blunder",
  "miss",
] as const;

export type MoveClassification = (typeof MOVE_CLASSIFICATIONS)[number];

const moveClassificationSet: ReadonlySet<string> = new Set(MOVE_CLASSIFICATIONS);

export function normalizeMoveClassification(value: unknown): MoveClassification {
  if (typeof value === "string" && moveClassificationSet.has(value)) {
    return value as MoveClassification;
  }
  if (value === "missed_win") return "miss";
  throw new Error(`Unsupported move quality: ${String(value)}.`);
}

export interface EngineScore {
  type: "cp" | "mate";
  value: number;
}

export interface AnalyzedMove {
  ply: number;
  moveNumber: number;
  san: string;
  uci: string;
  color: "w" | "b";
  from: string;
  to: string;
  fenBefore: string | null;
  fenAfter: string;
  bestMove: { san: string; uci: string } | null;
  centipawnLoss: number;
  winProbDelta: number;
  clock: string | null;
  /** White-centric evaluation in pawns after the move. */
  evaluation: number;
  /** Engine score in centipawns or mate distance, from White's perspective. */
  scoreAfter: EngineScore;
  classification: MoveClassification;
  explanation: string | null;
  suggestion: string | null;
}

export interface GameAnalysis {
  metadata: {
    white: string;
    black: string;
    result: string;
  };
  startFen: string;
  moves: AnalyzedMove[];
  whiteAccuracy: number;
  blackAccuracy: number;
  summary: string;
  headers: Record<string, string>;
  finalScore: EngineScore | null;
  finalEvaluation: number;
  termination: { result: string; reason: string; winner: "w" | "b" | null } | null;
}

interface ApiMove {
  ply: number;
  move_number: number;
  san: string;
  uci: string;
  color: "w" | "b";
  from: string;
  to: string;
  fen_before?: string;
  fen_after: string;
  best_move?: { san: string; uci: string } | null;
  evaluation: number;
  score_after: EngineScore;
  centipawn_loss?: number;
  win_prob_delta?: number;
  clock?: string | null;
  classification: unknown;
  explanation: unknown;
  suggestion: unknown;
}

interface ApiAnalysis extends Omit<
  GameAnalysis,
  | "startFen"
  | "whiteAccuracy"
  | "blackAccuracy"
  | "finalScore"
  | "finalEvaluation"
  | "moves"
  | "termination"
> {
  start_fen: string;
  white_accuracy: number;
  black_accuracy: number;
  final_score: EngineScore | null;
  final_evaluation: number;
  termination?: GameAnalysis["termination"];
  moves: ApiMove[];
}

export const ANALYSIS_STORAGE_KEY = "chessreview:analysis";

export const SAMPLE_PGN = `[Event "Immortal Game"]
[White "Anderssen"]
[Black "Kieseritzky"]

1. e4 e5 2. f4 exf4 3. Bc4 Qh4+ 4. Kf1 b5 5. Bxb5 Nf6 6. Nf3 Qh6 7. d3 Nh5
8. Nh4 Qg5 9. Nf5 c6 10. g4 Nf6 11. Rg1 cxb5 12. h4 Qg6 13. h5 Qg5 14. Qf3 Ng8
15. Bxf4 Qf6 16. Nc3 Bc5 17. Nd5 Qxb2 18. Bd6 Bxg1 19. e5 Qxa1+ 20. Ke2 Na6
21. Nxg7+ Kd8 22. Qf6+ Nxf6 23. Be7#`;

const API_URL = (import.meta.env["VITE_ANALYSIS_API_URL"] || "http://localhost:8000").replace(
  /\/$/,
  "",
);

async function decodeAnalysisResponse(response: Response): Promise<GameAnalysis> {
  const payload: unknown = await response
    .text()
    .then(parseSafeJson)
    .catch(() => null);
  if (!response.ok) {
    const detail =
      typeof payload === "object" &&
      payload !== null &&
      "detail" in payload &&
      typeof payload.detail === "string"
        ? payload.detail
        : "The game could not be analyzed.";
    throw new Error(detail);
  }
  const data = payload as ApiAnalysis;
  const moves = data.moves.map((move) => {
    if (typeof move.explanation !== "string" || typeof move.suggestion !== "string") {
      throw new Error(
        "The analysis API is outdated and did not return move explanations. Restart the backend and analyze the game again.",
      );
    }
    return {
      ply: move.ply,
      moveNumber: move.move_number,
      san: move.san,
      uci: move.uci,
      color: move.color,
      from: move.from,
      to: move.to,
      fenAfter: move.fen_after,
      fenBefore: move.fen_before ?? null,
      bestMove: move.best_move ?? null,
      centipawnLoss: move.centipawn_loss ?? 0,
      winProbDelta: move.win_prob_delta ?? 0,
      clock: move.clock ?? null,
      evaluation: move.evaluation,
      scoreAfter: move.score_after,
      classification: normalizeMoveClassification(move.classification),
      explanation: move.explanation,
      suggestion: move.suggestion,
    };
  });
  return {
    metadata: data.metadata,
    headers: data.headers,
    startFen: data.start_fen,
    moves,
    whiteAccuracy: data.white_accuracy,
    blackAccuracy: data.black_accuracy,
    summary: data.summary,
    finalScore: data.final_score,
    finalEvaluation: data.final_evaluation,
    termination: data.termination ?? null,
  };
}

export function parseSafeJson(source: string): unknown {
  return JSON.parse(source, (key: string, value: unknown) =>
    key === "__proto__" || key === "prototype" || key === "constructor" ? undefined : value,
  ) as unknown;
}

async function postAnalysis(
  path: string,
  body: BodyInit,
  headers?: HeadersInit,
): Promise<GameAnalysis> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: headers ?? {},
      body,
    });
  } catch {
    throw new Error(`Cannot connect to the analysis API at ${API_URL}.`);
  }
  return decodeAnalysisResponse(response);
}

export function analyzePgn(pgn: string, depth = 15): Promise<GameAnalysis> {
  if (!Number.isInteger(depth) || depth < 10 || depth > 20) {
    throw new Error("Analysis depth must be between 10 and 20.");
  }
  return postAnalysis(`/api/analyze?compact=true&depth=${depth}`, JSON.stringify({ pgn }), {
    "Content-Type": "application/json",
  });
}

export function analyzePgnFile(file: File, depth?: number): Promise<GameAnalysis> {
  if (depth !== undefined && (!Number.isInteger(depth) || depth < 10 || depth > 20)) {
    throw new Error("Analysis depth must be between 10 and 20.");
  }
  if (!/\.(pgn|fen|txt)$/i.test(file.name) || file.size > 1_000_000) {
    throw new Error("Choose a PGN, FEN, or TXT file no larger than 1 MB.");
  }
  const form = new FormData();
  form.append("file", file);
  const params = new URLSearchParams({ compact: "true" });
  if (depth !== undefined) params.set("depth", String(depth));
  const query = `?${params.toString()}`;
  return postAnalysis(`/api/analyze/file${query}`, form);
}

export async function checkAnalysisApiHealth(): Promise<{ status: string; engine: string }> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/health`);
  } catch {
    throw new Error(`Cannot connect to the analysis API at ${API_URL}.`);
  }
  if (!response.ok) throw new Error("The analysis API health check failed.");
  return (await response.json()) as { status: string; engine: string };
}

async function authHeaders(): Promise<HeadersInit> {
  const { supabase } = await import("@/supabase");
  if (!supabase) throw new Error("Sign in with Supabase Auth before starting a live game.");
  const { data, error } = await supabase.auth.getSession();
  if (error) throw new Error("Could not read the current sign-in session.");
  const token = data.session?.access_token;
  if (!token) throw new Error("Sign in with Supabase Auth before starting a live game.");
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

export async function createLiveGame(
  initialTimeSeconds = 300,
  incrementSeconds = 0,
): Promise<{ game_id: string }> {
  const headers = await authHeaders();
  const response = await fetch(`${API_URL}/api/games`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      initial_time_seconds: initialTimeSeconds,
      increment_seconds: incrementSeconds,
    }),
  });
  if (!response.ok) throw new Error("Could not create a live game.");
  return (await response.json()) as { game_id: string };
}

export async function joinLiveGame(gameId: string): Promise<void> {
  if (!/^[0-9a-f]{32}$/.test(gameId)) throw new Error("Invalid game ID.");
  const response = await fetch(`${API_URL}/api/games/join`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({ game_id: gameId }),
  });
  if (!response.ok) throw new Error("Could not join the live game.");
}

export async function validateLiveMove(
  gameId: string,
  uci: string,
): Promise<{ legal: boolean; san?: string; fen_before?: string; fen_after?: string }> {
  if (!/^[0-9a-f]{32}$/.test(gameId) || !/^[a-h][1-8][a-h][1-8][qrbn]?$/.test(uci)) {
    throw new Error("Invalid game or move data.");
  }
  const response = await fetch(`${API_URL}/api/move/validate`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({ game_id: gameId, uci }),
  });
  if (!response.ok) throw new Error("The move could not be validated.");
  return (await response.json()) as {
    legal: boolean;
    san?: string;
    fen_before?: string;
    fen_after?: string;
  };
}

export async function connectLiveGame(gameId: string): Promise<WebSocket> {
  if (!/^[0-9a-f]{32}$/.test(gameId)) throw new Error("Invalid game ID.");
  const { supabase } = await import("@/supabase");
  if (!supabase) throw new Error("Sign in with Supabase Auth before joining a live game.");
  const { data, error } = await supabase.auth.getSession();
  if (error || !data.session?.access_token) {
    throw new Error("Sign in with Supabase Auth before joining a live game.");
  }
  const socketUrl = new URL(API_URL);
  socketUrl.protocol = socketUrl.protocol === "https:" ? "wss:" : "ws:";
  socketUrl.pathname = `${socketUrl.pathname.replace(/\/$/, "")}/ws/game`;
  socketUrl.search = new URLSearchParams({ game_id: gameId }).toString();
  const socket = new WebSocket(socketUrl);
  socket.addEventListener(
    "open",
    () => socket.send(JSON.stringify({ type: "auth", token: data.session!.access_token })),
    { once: true },
  );
  return socket;
}

export function formatEval(value: number, score?: EngineScore | null): string {
  if (score?.type === "mate") {
    return `${score.value < 0 ? "-" : ""}M${Math.abs(score.value)}`;
  }
  if (value >= 19) return "M";
  if (value <= -19) return "-M";
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}`;
}
