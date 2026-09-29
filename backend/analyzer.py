from __future__ import annotations

import io
import math
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chess
import chess.engine
import chess.pgn
import chess.polyglot

MAX_PGN_CHARACTERS = 1_000_000
MAX_GAME_PLIES = 500
MATE_SCORE = 20.0
OPENING_BOOK_MAX_FULLMOVE = 10
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


@dataclass(frozen=True)
class EngineSettings:
    path: str = "stockfish.exe" if os.name == "nt" else "stockfish"
    depth: int = 14
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

        selected_depth = depth or self.settings.depth
        if not 8 <= selected_depth <= 24:
            raise AnalysisError("Analysis depth must be between 8 and 24.")

        with self._lock:
            fen_analysis = self._analyze_fen(raw_input.strip(), selected_depth)
            if fen_analysis is not None:
                return fen_analysis
            return self._analyze_pgn(raw_input, selected_depth)

    def _analyze_fen(self, raw_input: str, depth: int) -> dict[str, Any] | None:
        if "\n" in raw_input or "/" not in raw_input:
            return None
        try:
            board = chess.Board(raw_input)
        except ValueError:
            return None
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
                before_info = self._engine_analyze(board, depth)
                best_move = before_info.get("pv", [None])[0]
                if best_move is None:
                    raise RuntimeError("Stockfish did not return a principal variation.")

                best_score = before_info["score"].pov(mover).score(mate_score=100_000)
                if best_score is None:
                    raise RuntimeError("Stockfish returned an unscorable position.")

                before_white_score = before_info["score"].pov(chess.WHITE)
                before_eval = _score_to_pawns(before_white_score)
                board.push(move)
                after_info = self._engine_analyze(board, depth)
                actual_score_obj = after_info["score"].pov(mover)
                actual_score = actual_score_obj.score(mate_score=100_000)
                if actual_score is None:
                    raise RuntimeError("Stockfish returned an unscorable position.")

                loss = max(0.0, (best_score - actual_score) / 100.0)
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
                before_mate = before_info["score"].pov(mover).mate()
                actual_mate = actual_score_obj.mate()
                classification = _classify(
                    loss=loss,
                    material_sacrifice=material_sacrifice,
                    gain=gain,
                    lost_forced_mate=(
                        before_mate is not None
                        and before_mate > 0
                        and (actual_mate is None or actual_mate <= 0)
                    ),
                    missed_mate=actual_score <= -99_000 and best_score > -99_000,
                )

            fen_after = board.fen()

            alternative = None
            if classification in {"mistake", "blunder"}:
                alternative = {
                    "san": chess.Board(fen_before).san(best_move),
                    "uci": best_move.uci(),
                }

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
                    "classification": classification,
                    "best_move": {
                        "san": chess.Board(fen_before).san(best_move),
                        "uci": best_move.uci(),
                    },
                    "best_alternative_move": alternative,
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

    def _engine_analyze(self, board: chess.Board, depth: int) -> dict[str, Any]:
        return self._engine.analyse(
            board,
            chess.engine.Limit(depth=depth),
        )

    def _engine_score(self, board: chess.Board, depth: int) -> chess.engine.Score:
        return self._engine_analyze(board, depth)["score"]


def _score_to_pawns(score: chess.engine.Score) -> float:
    centipawns = score.score(mate_score=int(MATE_SCORE * 100))
    return round(max(-MATE_SCORE, min(MATE_SCORE, (centipawns or 0) / 100)), 2)


def _score_to_json(score: chess.engine.Score) -> dict[str, int | str]:
    mate = score.mate()
    if mate is not None:
        return {"type": "mate", "value": mate}
    return {"type": "cp", "value": score.score() or 0}


def _classify(
    *,
    loss: float,
    material_sacrifice: float,
    gain: float,
    lost_forced_mate: bool,
    missed_mate: bool,
) -> str:
    if missed_mate or lost_forced_mate or loss > 3.0:
        return "blunder"
    if loss > 1.0:
        return "mistake"
    if loss > 0.5:
        return "inaccuracy"
    if material_sacrifice >= 3.0 and gain >= 0.5 and loss <= 0.1:
        return "brilliant"
    if loss <= 0.2:
        return "best"
    return "good"


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