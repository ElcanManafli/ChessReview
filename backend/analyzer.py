from __future__ import annotations

import io
import math
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CLASSIFICATION_SYMBOLS: dict[str, str] = {
    "book": "📖",
    "brilliant": "!!",
    "great": "!",
    "best": "★",
    "excellent": "✔",
    "good": "",
    "inaccuracy": "?!",
    "mistake": "?",
    "blunder": "??",
    "miss": "❌",
    "Book": "📖",
    "Brilliant": "!!",
    "Great": "!",
    "Best": "★",
    "Excellent": "✔",
    "Good": "",
    "Inaccuracy": "?!",
    "Mistake": "?",
    "Blunder": "??",
    "Miss": "❌",
}


def _normalize_category(classification: str) -> str:
    key = classification.strip()
    if key in CLASSIFICATION_SYMBOLS:
        return key
    return key.lower()


def move_symbol(classification: str) -> str:
    key = _normalize_category(classification)
    return CLASSIFICATION_SYMBOLS.get(key, "")


def _move_feedback(
    *,
    classification: str,
    san: str,
    best_move_san: str,
    loss_cp: float,
    material_sacrifice: float,
    eval_after: float,
    is_best_move: bool,
    is_book: bool,
    missed_mate: bool,
    missed_tactical_sequence: bool,
    lost_forced_mate: bool,
    second_best_wdl_drop: float,
    depth: int,
) -> tuple[str, str]:
    loss = max(0.0, loss_cp) / 100
    loss_text = f"about {loss:.1f} pawns" if loss >= 0.25 else "very little"

    if is_book:
        return (
            "This move follows a recognized opening line, so the engine did not separately compare it with alternatives.",
            "Continue developing your pieces, contest the center, and keep your king safe.",
        )
    if classification == "Brilliant":
        why = (
            f"This is the engine's top move. It accepts a sacrifice of about "
            f"{material_sacrifice:.1f} material points while keeping your evaluation at "
            f"{eval_after:+.1f} pawns."
        )
    elif classification == "Great":
        why = (
            "This is the engine's critical top move; its second choice is substantially worse "
            "for your winning chances."
        )
    elif classification == "Best":
        why = "You played the engine's top-recommended move in this position."
    elif classification == "Excellent":
        why = (
            f"This is not the top move, but it keeps close to the best line, giving up "
            f"{loss_text} of evaluation."
        )
    elif classification == "Good":
        why = (
            f"This is a safe, playable move. The engine's top choice is stronger, but this move "
            f"gives up {loss_text} of evaluation."
        )
    elif classification == "Inaccuracy":
        why = (
            f"This move is playable, but it gives up {loss_text} of evaluation and makes the "
            "position easier for your opponent."
        )
    elif classification == "Mistake":
        why = (
            f"This move loses about {loss:.1f} pawns of evaluation, a significant setback "
            "that could give away material or a winning advantage."
        )
    elif classification == "Miss":
        if lost_forced_mate:
            why = "A forced checkmate was available for you, but this move missed it."
        elif missed_tactical_sequence:
            why = "A winning tactical sequence was available, but this move missed it."
        else:
            why = "This move missed a forcing opportunity identified by the engine."
    elif classification == "Blunder":
        if missed_mate:
            why = "This move allows a forced checkmate for your opponent."
        else:
            why = (
                f"This move is a serious error, giving up about {loss:.1f} pawns of evaluation "
                "and allowing a much stronger reply."
            )
    else:
        raise ValueError(f"Unsupported move classification: {classification}.")

    if is_best_move:
        suggestion = (
            f"Keep {san}. Stockfish found no stronger alternative at depth {depth}."
        )
    else:
        suggestion = (
            f"Prefer {best_move_san} instead. Stockfish ranked it above {san} at depth {depth}."
        )
    if classification == "Great" and second_best_wdl_drop > 0:
        why += (
            f" Its second choice is about {second_best_wdl_drop * 100:.0f} percentage "
            "points worse in estimated win probability."
        )
    return why, suggestion


def _score_to_wdl(score: chess.engine.Score) -> tuple[float, float, float]:
    cp = score.score(mate_score=100_000)
    if cp is None:
        mate = score.mate()
        if mate is not None:
            return (0.8, 0.1, 0.1) if mate > 0 else (0.1, 0.1, 0.8)
        return (0.5, 0.0, 0.5)

    x = cp / 100.0
    win = 1.0 / (1.0 + math.exp(-0.55 * x))
    draw = 0.35 / (1.0 + abs(x) * 0.9)
    loss = max(0.0, 1.0 - win - draw)
    if loss == 0.0 and win + draw < 1.0:
        draw = 1.0 - win
    s = win + draw + loss
    return win / s, draw / s, loss / s


def _wdl_thresholds(current_win_prob: float) -> dict[str, float]:
    if current_win_prob >= 0.80:
        return {"good": 0.02, "inaccuracy": 0.04, "mistake": 0.09, "blunder": 0.18}
    if current_win_prob >= 0.65:
        return {"good": 0.03, "inaccuracy": 0.06, "mistake": 0.12, "blunder": 0.22}
    if current_win_prob >= 0.55:
        return {"good": 0.04, "inaccuracy": 0.08, "mistake": 0.15, "blunder": 0.28}
    if current_win_prob >= 0.45:
        return {"good": 0.05, "inaccuracy": 0.10, "mistake": 0.18, "blunder": 0.34}
    return {"good": 0.07, "inaccuracy": 0.12, "mistake": 0.22, "blunder": 0.42}


def classify_move(
    *,
    win_prob_delta: float,
    current_win_prob: float,
    material_sacrifice_cp: float = 0.0,
    eval_before: float = 0.0,
    eval_after: float = 0.0,
    is_tactical: bool = False,
    is_book: bool = False,
    is_best_move: bool = False,
    second_best_wdl_drop: float = 0.0,
    lost_forced_mate: bool = False,
    missed_mate: bool = False,
    missed_tactical_sequence: bool = False,
) -> str:
    if is_book:
        return "Book"

    if (
        is_best_move
        and material_sacrifice_cp >= BRILLIANT_MIN_SACRIFICE_CP
        and win_prob_delta <= 0.05
        and eval_after >= eval_before - 0.20
    ):
        return "Brilliant"

    if (
        is_best_move
        and second_best_wdl_drop >= 0.30
        and (eval_after >= 0.0 or current_win_prob >= 0.50)
        and eval_after >= eval_before - 0.10
    ):
        return "Great"

    if is_best_move:
        return "Best"

    if lost_forced_mate or missed_tactical_sequence:
        return "Miss"

    if missed_mate:
        return "Blunder"

    if win_prob_delta <= 0.020 and eval_after >= eval_before - 0.15:
        return "Excellent"

    thresholds = _wdl_thresholds(current_win_prob)
    if win_prob_delta <= thresholds["good"] and eval_after >= eval_before - 0.85:
        return "Good"
    if win_prob_delta <= thresholds["inaccuracy"]:
        return "Inaccuracy"
    if win_prob_delta <= thresholds["mistake"]:
        return "Mistake"
    return "Blunder"

import chess
import chess.engine
import chess.pgn
import chess.polyglot

MAX_PGN_CHARACTERS = 1_000_000
MAX_GAME_PLIES = 500
MATE_SCORE = 20.0
OPENING_BOOK_MAX_FULLMOVE = 10
BRILLIANT_MIN_SACRIFICE_CP = 300.0
OPENING_BOOK_LINES = (
    "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7",
    "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3 d6",
    "e4 e5 Nf3 Nc6 d4 exd4 Nxd4",
    "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3",
    "e4 e6 d4 d5 Nc3 Bb4",
    "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5",
    "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7",
    "d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4 e3 b5",
    "d4 Nf6 c4 e6 Nc3 Bb4",
    "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6",
    "c4 e5 Nc3 Nf6 g3 d5",
    "Nf3 d5 g3 Nf6 Bg2 e6 O-O Be7",
)


def _build_opening_book() -> dict[int, set[chess.Move]]:
    book: dict[int, set[chess.Move]] = {}
    for line in OPENING_BOOK_LINES:
        board = chess.Board()
        for san in line.split():
            move = board.parse_san(san)
            book.setdefault(chess.polyglot.zobrist_hash(board), set()).add(move)
            board.push(move)
    return book


OPENING_BOOK = _build_opening_book()


class AnalysisError(ValueError):
    """A user-supplied game cannot be analyzed."""


class AnalysisBusyError(RuntimeError):
    """The local engine is already analyzing another game."""


@dataclass(frozen=True)
class EngineSettings:
    path: str = "stockfish.exe" if os.name == "nt" else "stockfish"
    depth: int = 15
    threads: int = 2
    hash_mb: int = 256
    timeout_seconds: float = 30.0


class ChessAnalyzer:
    """Owns one Stockfish process and serializes access to its UCI protocol."""

    def __init__(self, settings: EngineSettings) -> None:
        self.settings = settings
        self._engine: chess.engine.SimpleEngine | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._engine is not None:
            return

        executable_path = _resolve_engine_path(self.settings.path)

        engine: chess.engine.SimpleEngine | None = None
        try:
            engine = chess.engine.SimpleEngine.popen_uci(
                executable_path,
                timeout=self.settings.timeout_seconds,
            )
            options: dict[str, int] = {}
            if "Threads" in engine.options:
                options["Threads"] = self.settings.threads
            if "Hash" in engine.options:
                options["Hash"] = self.settings.hash_mb
            if options:
                engine.configure(options)
            self._engine = engine
        except (OSError, chess.engine.EngineError, chess.engine.EngineTerminatedError) as exc:
            if engine is not None:
                try:
                    engine.quit()
                except (OSError, chess.engine.EngineError, chess.engine.EngineTerminatedError):
                    pass
            raise RuntimeError(
                f"Could not start Stockfish executable at {executable_path!r}: {exc}"
            ) from exc

    def close(self) -> None:
        if self._engine is not None:
            self._engine.quit()
            self._engine = None

    def analyze(self, raw_input: str, depth: int | None = None) -> dict[str, Any]:
        if len(raw_input) > MAX_PGN_CHARACTERS:
            raise AnalysisError("Input exceeds the 1 MB limit.")
        if not raw_input.strip():
            raise AnalysisError("Provide a PGN game or FEN position.")
        if self._engine is None:
            raise RuntimeError("Stockfish is not running.")

        selected_depth = self.settings.depth if depth is None else depth
        if not 10 <= selected_depth <= 20:
            raise AnalysisError("Analysis depth must be between 10 and 20.")

        if not self._lock.acquire(blocking=False):
            raise AnalysisBusyError("The analysis engine is busy. Try again shortly.")
        try:
            fen_analysis = self._analyze_fen(raw_input.strip(), selected_depth)
            if fen_analysis is not None:
                return fen_analysis
            return self._analyze_pgn(raw_input, selected_depth)
        finally:
            self._lock.release()

    def _analyze_fen(self, raw_input: str, depth: int) -> dict[str, Any] | None:
        if "\n" in raw_input or "/" not in raw_input:
            return None
        try:
            board = chess.Board(raw_input)
        except ValueError:
            return None
        if not board.is_valid():
            raise AnalysisError("Invalid FEN position.")
        score = self._engine_score(board, depth).pov(chess.WHITE)
        evaluation = _score_to_pawns(score)
        return {
            "metadata": {"white": "White", "black": "Black", "result": "*"},
            "headers": {},
            "start_fen": board.fen(),
            "moves": [],
            "white_accuracy": 100.0,
            "black_accuracy": 100.0,
            "summary": f"Static FEN position. Stockfish evaluates it at {_format_eval(evaluation)}.",
            "final_score": _score_to_json(score),
            "final_evaluation": evaluation,
        }

    def _analyze_pgn(self, raw_input: str, depth: int) -> dict[str, Any]:
        game = chess.pgn.read_game(io.StringIO(raw_input))
        if game is None:
            raise AnalysisError("Could not parse a PGN game. Check the headers and move list.")
        if game.errors:
            details = str(game.errors[0])
            raise AnalysisError(f"Invalid PGN: {details[:240]}")

        san_moves = list(game.mainline_moves())
        if not san_moves:
            raise AnalysisError("No moves found in the PGN game.")
        if len(san_moves) > MAX_GAME_PLIES:
            raise AnalysisError(f"Games are limited to {MAX_GAME_PLIES} plies.")

        headers = dict(game.headers)
        board = game.board()
        start_fen = board.fen()
        analyzed_moves: list[dict[str, Any]] = []
        white_losses: list[float] = []
        black_losses: list[float] = []

        for ply, move in enumerate(san_moves):
            fen_before = board.fen()
            mover = board.turn
            san = board.san(move)
            uci = move.uci()
            is_book_move = (
                board.fullmove_number <= OPENING_BOOK_MAX_FULLMOVE
                and move in OPENING_BOOK.get(chess.polyglot.zobrist_hash(board), set())
            )
            centipawn_loss = 0.0
            win_prob_delta = 0.0

            if is_book_move:
                before_white_score = chess.engine.Cp(0)
                after_white_score = before_white_score
                before_eval = 0.0
                after_eval = 0.0
                loss = 0.0
                best_move = move
                classification = "book"
                board.push(move)
            else:
                multipv_info = self._engine_analyze(board, depth, multipv=2)
                best_info = multipv_info[0]
                best_move = best_info.get("pv", [None])[0]
                if best_move is None:
                    raise RuntimeError("Stockfish did not return a principal variation.")

                second_best_wdl_drop = 0.0
                if len(multipv_info) > 1:
                    second_best = multipv_info[1]
                    first_wdl = _score_to_wdl(best_info["score"].pov(mover))
                    second_wdl = _score_to_wdl(second_best["score"].pov(mover))
                    second_best_wdl_drop = max(0.0, first_wdl[0] - second_wdl[0])

                best_score = best_info["score"].pov(mover).score(mate_score=100_000)
                if best_score is None:
                    raise RuntimeError("Stockfish returned an unscorable position.")

                before_white_score = best_info["score"].pov(chess.WHITE)
                before_eval = _score_to_pawns(before_white_score)
                board.push(move)
                after_info = self._engine_analyze(board, depth)[0]
                actual_score_obj = after_info["score"].pov(mover)
                actual_score = actual_score_obj.score(mate_score=100_000)
                if actual_score is None:
                    raise RuntimeError("Stockfish returned an unscorable position.")

                centipawn_loss = max(0.0, float(best_score - actual_score))
                loss = centipawn_loss / 100.0
                after_white_score = after_info["score"].pov(chess.WHITE)
                after_eval = _score_to_pawns(after_white_score)
                gain = (after_eval - before_eval) * (1 if mover == chess.WHITE else -1)
                reply_board = board.copy()
                opponent_reply = after_info.get("pv", [None])[0]
                if opponent_reply is not None and opponent_reply in reply_board.legal_moves:
                    reply_board.push(opponent_reply)
                material_sacrifice = (
                    _material_balance(chess.Board(fen_before), mover)
                    - _material_balance(reply_board, mover)
                )
                before_mate = best_info["score"].pov(mover).mate()
                actual_mate = actual_score_obj.mate()
                best_wdl = _score_to_wdl(best_info["score"].pov(mover))
                played_wdl = _score_to_wdl(actual_score_obj)
                win_prob_delta = max(0.0, best_wdl[0] - played_wdl[0])
                current_win_prob = best_wdl[0]
                material_sacrifice_cp = max(0.0, material_sacrifice * 100)
                is_best_move = move == best_move or move.uci() == best_move.uci()
                classification = classify_move(
                    win_prob_delta=win_prob_delta,
                    current_win_prob=current_win_prob,
                    material_sacrifice_cp=material_sacrifice_cp,
                    eval_before=before_eval * (1 if mover == chess.WHITE else -1),
                    eval_after=after_eval * (1 if mover == chess.WHITE else -1),
                    is_tactical=material_sacrifice_cp >= 250.0 or gain >= 0.5,
                    is_best_move=is_best_move,
                    second_best_wdl_drop=second_best_wdl_drop,
                    lost_forced_mate=(
                        before_mate is not None
                        and before_mate > 0
                        and (actual_mate is None or actual_mate <= 0)
                    ),
                    missed_mate=actual_score <= -99_000 and best_score > -99_000,
                    missed_tactical_sequence=best_score >= 500 and win_prob_delta >= 0.15,
                )

            fen_after = board.fen()
            category = _normalize_category(classification)

            best_move_san = chess.Board(fen_before).san(best_move)
            feedback, suggestion = _move_feedback(
                classification=category,
                san=san,
                best_move_san=best_move_san,
                loss_cp=centipawn_loss,
                material_sacrifice=material_sacrifice if not is_book_move else 0.0,
                eval_after=(
                    after_eval * (1 if mover == chess.WHITE else -1)
                    if not is_book_move
                    else 0.0
                ),
                is_best_move=(move == best_move),
                is_book=is_book_move,
                missed_mate=(
                    not is_book_move
                    and actual_score <= -99_000
                    and best_score > -99_000
                ),
                missed_tactical_sequence=(
                    not is_book_move and best_score >= 500 and win_prob_delta >= 0.15
                ),
                lost_forced_mate=(
                    not is_book_move
                    and before_mate is not None
                    and before_mate > 0
                    and (actual_mate is None or actual_mate <= 0)
                ),
                second_best_wdl_drop=second_best_wdl_drop if not is_book_move else 0.0,
                depth=depth,
            )

            move_number = (ply // 2) + 1
            analyzed_moves.append(
                {
                    "ply": ply,
                    "move_number": move_number,
                    "san": san,
                    "uci": uci,
                    "color": "w" if mover == chess.WHITE else "b",
                    "from": chess.square_name(move.from_square),
                    "to": chess.square_name(move.to_square),
                    "fen_before": fen_before,
                    "fen_after": fen_after,
                    "evaluation_before": before_eval,
                    "evaluation": after_eval,
                    "score_before": _score_to_json(before_white_score),
                    "score_after": _score_to_json(after_white_score),
                    "loss": round(loss, 2),
                    "centipawn_loss": int(round(centipawn_loss)),
                    "classification": category.lower(),
                    "category": category,
                    "symbol": CLASSIFICATION_SYMBOLS.get(category, ""),
                    "explanation": feedback,
                    "suggestion": suggestion,
                    "win_prob_delta": round(win_prob_delta, 4),
                    "best_move": {
                        "san": best_move_san,
                        "uci": best_move.uci(),
                    },
                    "best_alternative_move": (
                        {"san": best_move_san, "uci": best_move.uci()}
                        if category.lower() in {"mistake", "blunder"}
                        else None
                    ),
                }
            )
            (white_losses if mover == chess.WHITE else black_losses).append(loss)

        white_accuracy = _accuracy(white_losses)
        black_accuracy = _accuracy(black_losses)
        final_score = analyzed_moves[-1]["score_after"]
        final_eval = analyzed_moves[-1]["evaluation"]
        leader = "White" if final_eval > 0.6 else "Black" if final_eval < -0.6 else None
        summary = (
            f"{leader} finished with a Stockfish evaluation of {_format_eval(final_eval)}."
            if leader
            else f"The final position is close to equal ({_format_eval(final_eval)})."
        )

        return {
            "metadata": {
                "white": headers.get("White", "White"),
                "black": headers.get("Black", "Black"),
                "result": headers.get("Result", "*"),
            },
            "headers": headers,
            "start_fen": start_fen,
            "moves": analyzed_moves,
            "white_accuracy": white_accuracy,
            "black_accuracy": black_accuracy,
            "summary": summary,
            "final_score": final_score,
            "final_evaluation": final_eval,
        }

    def _engine_analyze(
        self,
        board: chess.Board,
        depth: int,
        multipv: int = 1,
    ) -> list[dict[str, Any]]:
        result = self._engine.analyse(
            board,
            chess.engine.Limit(depth=depth),
            multipv=multipv,
        )
        return result if isinstance(result, list) else [result]

    def _engine_score(self, board: chess.Board, depth: int) -> chess.engine.Score:
        return self._engine_analyze(board, depth)[0]["score"]


def _score_to_pawns(score: chess.engine.Score) -> float:
    centipawns = score.score(mate_score=int(MATE_SCORE * 100))
    return round(max(-MATE_SCORE, min(MATE_SCORE, (centipawns or 0) / 100)), 2)


def _score_to_json(score: chess.engine.Score) -> dict[str, int | str]:
    mate = score.mate()
    if mate is not None:
        return {"type": "mate", "value": mate}
    return {"type": "cp", "value": score.score() or 0}


def _accuracy(losses: list[float]) -> float:
    if not losses:
        return 100.0
    scores = [max(10.0, min(100.0, 103.2 * math.exp(-0.55 * loss) - 3.2)) for loss in losses]
    return round(sum(scores) / len(scores), 1)


def _material_balance(board: chess.Board, color: chess.Color) -> float:
    piece_values = {
        chess.PAWN: 1.0,
        chess.KNIGHT: 3.0,
        chess.BISHOP: 3.25,
        chess.ROOK: 5.0,
        chess.QUEEN: 9.0,
    }
    balance = 0.0
    for piece_type, value in piece_values.items():
        balance += len(board.pieces(piece_type, color)) * value
        balance -= len(board.pieces(piece_type, not color)) * value
    return balance


def _format_eval(value: float) -> str:
    return f"{value:+.1f}"


def _resolve_engine_path(configured_path: str) -> str:
    candidate = Path(configured_path).expanduser()

    if candidate.is_absolute() or candidate.parent != Path("."):
        if candidate.is_file():
            return str(candidate.resolve())
        raise FileNotFoundError(
            f"Stockfish executable {str(candidate)!r} does not exist. "
            "Check STOCKFISH_PATH."
        )

    local_candidate = Path.cwd() / candidate
    if local_candidate.is_file():
        return str(local_candidate.resolve())

    path_candidate = shutil.which(configured_path)
    if path_candidate:
        return str(Path(path_candidate).resolve())

    raise FileNotFoundError(
        f"Stockfish executable {configured_path!r} was not found in the current "
        f"directory ({Path.cwd()}) or on PATH. Place it in the current directory "
        "or set STOCKFISH_PATH to its full path."
    )