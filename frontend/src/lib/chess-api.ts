export type MoveClassification =
  | "book"
  | "brilliant"
  | "great"
  | "best"
  | "good"
  | "inaccuracy"
  | "mistake"
  | "blunder"
  | "missed_win";

export interface EngineScore {
  type: "cp" | "mate";
  value: number;
}

export interface EngineMove {
  san: string;
  uci: string;
}

export interface AnalyzedMove {
  ply: number;
  moveNumber: number;
  san: string;
  uci: string;
  color: "w" | "b";
  from: string;
  to: string;
  fenBefore: string;
  fenAfter: string;
  evaluationBefore: number;
  /** White-centric evaluation in pawns after the move. */
  evaluation: number;
  /** Engine score in centipawns or mate distance, from White's perspective. */
  scoreBefore: EngineScore;
  scoreAfter: EngineScore;
  /** Centipawn-equivalent loss in pawns from the mover's perspective. */
  loss: number;
  classification: MoveClassification;
  bestMove: EngineMove;
  bestAlternativeMove: EngineMove | null;
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
}

interface ApiMove extends Omit<
  AnalyzedMove,
  | "moveNumber"
  | "fenBefore"
  | "fenAfter"
  | "evaluationBefore"
  | "scoreBefore"
  | "scoreAfter"
  | "bestMove"
  | "bestAlternativeMove"
> {
  move_number: number;
  fen_before: string;
  fen_after: string;
  evaluation_before: number;
  score_before: EngineScore;
  score_after: EngineScore;
  best_move: EngineMove;
  best_alternative_move: EngineMove | null;
}

interface ApiAnalysis extends Omit<
  GameAnalysis,
  "startFen" | "whiteAccuracy" | "blackAccuracy" | "finalScore" | "finalEvaluation" | "moves"
> {
  start_fen: string;
  white_accuracy: number;
  black_accuracy: number;
  final_score: EngineScore | null;
  final_evaluation: number;
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
  const payload: unknown = await response.json().catch(() => null);
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
  return {
    metadata: data.metadata,
    headers: data.headers,
    startFen: data.start_fen,
    moves: data.moves.map((move) => ({
      ply: move.ply,
      moveNumber: move.move_number,
      san: move.san,
      uci: move.uci,
      color: move.color,
      from: move.from,
      to: move.to,
      fenBefore: move.fen_before,
      fenAfter: move.fen_after,
      evaluationBefore: move.evaluation_before,
      evaluation: move.evaluation,
      scoreBefore: move.score_before,
      scoreAfter: move.score_after,
      loss: move.loss,
      classification: move.classification,
      bestMove: move.best_move,
      bestAlternativeMove: move.best_alternative_move,
    })),
    whiteAccuracy: data.white_accuracy,
    blackAccuracy: data.black_accuracy,
    summary: data.summary,
    finalScore: data.final_score,
    finalEvaluation: data.final_evaluation,
  };
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

export function analyzePgn(pgn: string): Promise<GameAnalysis> {
  return postAnalysis("/api/analyze", JSON.stringify({ pgn }), {
    "Content-Type": "application/json",
  });
}

export function analyzePgnFile(file: File, depth?: number): Promise<GameAnalysis> {
  const form = new FormData();
  form.append("file", file);
  const query = depth === undefined ? "" : `?depth=${encodeURIComponent(depth)}`;
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
  return response.json();
}

export function formatEval(value: number, score?: EngineScore | null): string {
  if (score?.type === "mate") {
    return `${score.value < 0 ? "-" : ""}M${Math.abs(score.value)}`;
  }
  if (value >= 19) return "M";
  if (value <= -19) return "-M";
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}`;
}
