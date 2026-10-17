from __future__ import annotations

import asyncio
import json
import secrets
import time
import uuid
from typing import Any

import chess
from redis.asyncio import Redis


GAME_TTL_SECONDS = 7 * 24 * 60 * 60
LOCK_TTL_MILLISECONDS = 5_000
MAX_GAME_PLIES = 500


class LiveGameError(Exception):
    pass


class GameNotFoundError(LiveGameError):
    pass


class GameAccessError(LiveGameError):
    pass


class InvalidMoveError(LiveGameError):
    pass


class GameStateConflictError(LiveGameError):
    pass


class LiveGameStore:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def create(
        self, user_id: str, initial_clock_ms: int, increment_ms: int
    ) -> dict[str, Any]:
        game_id = uuid.uuid4().hex
        state: dict[str, Any] = {
            "game_id": game_id,
            "players": {"w": user_id, "b": None},
            "start_fen": chess.STARTING_FEN,
            "fen": chess.STARTING_FEN,
            "moves_uci": [],
            "clocks_ms": {"w": initial_clock_ms, "b": initial_clock_ms},
            "increment_ms": increment_ms,
            "status": "waiting",
            "last_move_at": None,
            "version": 0,
            "termination": None,
        }
        await self._save(state)
        return await self._snapshot(state, time.time())

    async def join(self, game_id: str, user_id: str) -> dict[str, Any]:
        async with self._locked(game_id):
            state = await self._load(game_id)
            if state["status"] != "waiting":
                raise GameStateConflictError("This game is not waiting for a player.")
            if state["players"]["w"] == user_id:
                raise GameAccessError("The game creator cannot join as the opponent.")
            state["players"]["b"] = user_id
            state["status"] = "running"
            state["last_move_at"] = time.time()
            state["version"] += 1
            await self._save(state)
            return await self._snapshot(state, time.time())

    async def validate_move(
        self, game_id: str, user_id: str, uci: str
    ) -> dict[str, Any]:
        async with self._locked(game_id):
            state = await self._load(game_id)
            self._assert_member(state, user_id)
            board = self._board(state)
            now = time.time()
            self._check_clock(state, now)
            if state["status"] == "finished":
                await self._save(state)
                raise GameStateConflictError("The game has ended.")
            self._assert_player_turn(state, user_id, board)
            move = self._parse_legal_move(board, uci)
            next_board = board.copy(stack=True)
            next_board.push(move)
            return {
                "legal": True,
                "san": board.san(move),
                "fen_before": board.fen(),
                "fen_after": next_board.fen(),
            }

    async def play_move(
        self, game_id: str, user_id: str, uci: str
    ) -> dict[str, Any]:
        async with self._locked(game_id):
            state = await self._load(game_id)
            now = time.time()
            self._assert_member(state, user_id)
            board = self._board(state)
            self._check_clock(state, now)
            if state["status"] == "finished":
                await self._save(state)
                return await self._snapshot(state, now)
            self._assert_player_turn(state, user_id, board)
            if len(state["moves_uci"]) >= MAX_GAME_PLIES:
                state["status"] = "finished"
                state["last_move_at"] = None
                state["termination"] = {
                    "result": "1/2-1/2",
                    "reason": "maximum game length",
                    "winner": None,
                }
                state["version"] += 1
                await self._save(state)
                return await self._snapshot(state, now)
            move = self._parse_legal_move(board, uci)
            mover = board.turn
            elapsed_ms = max(0, int((now - state["last_move_at"]) * 1000))
            state["clocks_ms"]["w" if mover else "b"] -= elapsed_ms
            if state["clocks_ms"]["w" if mover else "b"] <= 0:
                state["clocks_ms"]["w" if mover else "b"] = 0
                self._finish_on_time(state, mover)
            else:
                state["clocks_ms"]["w" if mover else "b"] += state["increment_ms"]
                board.push(move)
                state["fen"] = board.fen()
                state["moves_uci"].append(move.uci())
                state["last_move_at"] = now
                state["version"] += 1
                outcome = board.outcome(claim_draw=False)
                if outcome is not None:
                    state["status"] = "finished"
                    state["termination"] = self._termination(outcome)
                    state["last_move_at"] = None
            await self._save(state)
            return await self._snapshot(state, now)

    async def claim_draw(self, game_id: str, user_id: str) -> dict[str, Any]:
        async with self._locked(game_id):
            state = await self._load(game_id)
            now = time.time()
            self._assert_member(state, user_id)
            board = self._board(state)
            self._check_clock(state, now)
            if state["status"] == "finished":
                await self._save(state)
                return await self._snapshot(state, now)
            self._assert_player_turn(state, user_id, board)
            if board.is_fifty_moves():
                reason = "50-move rule"
            elif board.can_claim_threefold_repetition():
                reason = "threefold repetition"
            else:
                raise GameStateConflictError("A draw cannot be claimed in this position.")
            state["status"] = "finished"
            state["termination"] = {"result": "1/2-1/2", "reason": reason, "winner": None}
            state["last_move_at"] = None
            state["version"] += 1
            await self._save(state)
            return await self._snapshot(state, now)

    async def snapshot(self, game_id: str, user_id: str) -> dict[str, Any]:
        async with self._locked(game_id):
            state = await self._load(game_id)
            if user_id not in state["players"].values():
                raise GameAccessError("You are not a player in this game.")
            now = time.time()
            self._check_clock(state, now)
            if state["status"] == "finished":
                await self._save(state)
            return await self._snapshot(state, now)

    async def _load(self, game_id: str) -> dict[str, Any]:
        if len(game_id) != 32 or any(char not in "0123456789abcdef" for char in game_id):
            raise GameNotFoundError("Game not found or expired.")
        try:
            encoded = await self.redis.get(self._key(game_id))
        except Exception as exc:
            raise GameStateConflictError("Live game storage is unavailable.") from exc
        if encoded is None:
            raise GameNotFoundError("Game not found or expired.")
        try:
            state = json.loads(encoded)
            self._board(state)
            return state
        except (TypeError, ValueError, KeyError) as exc:
            raise GameStateConflictError("Stored game state is invalid.") from exc

    async def _save(self, state: dict[str, Any]) -> None:
        try:
            await self.redis.set(
                self._key(state["game_id"]),
                json.dumps(state, separators=(",", ":")),
                ex=GAME_TTL_SECONDS,
            )
        except Exception as exc:
            raise GameStateConflictError("Live game storage is unavailable.") from exc

    async def _snapshot(
        self, state: dict[str, Any], now: float
    ) -> dict[str, Any]:
        clocks = dict(state["clocks_ms"])
        if state["status"] == "running" and state["last_move_at"] is not None:
            board = self._board(state)
            color = "w" if board.turn else "b"
            clocks[color] = max(
                0, clocks[color] - max(0, int((now - state["last_move_at"]) * 1000))
            )
        return {
            **state,
            "clocks_ms": clocks,
            "server_time": now,
        }

    def _check_clock(self, state: dict[str, Any], now: float) -> None:
        if state["status"] != "running" or state["last_move_at"] is None:
            return
        board = self._board(state)
        color = "w" if board.turn else "b"
        remaining = state["clocks_ms"][color] - max(
            0, int((now - state["last_move_at"]) * 1000)
        )
        if remaining <= 0:
            state["clocks_ms"][color] = 0
            self._finish_on_time(state, board.turn)

    @staticmethod
    def _finish_on_time(state: dict[str, Any], loser: chess.Color) -> None:
        state["status"] = "finished"
        state["last_move_at"] = None
        state["version"] += 1
        state["termination"] = {
            "result": "0-1" if loser == chess.WHITE else "1-0",
            "reason": "time forfeit",
            "winner": "b" if loser == chess.WHITE else "w",
        }

    @staticmethod
    def _assert_member(state: dict[str, Any], user_id: str) -> None:
        if user_id not in state["players"].values():
            raise GameAccessError("You are not a player in this game.")

    @staticmethod
    def _assert_player_turn(
        state: dict[str, Any], user_id: str, board: chess.Board
    ) -> None:
        LiveGameStore._assert_member(state, user_id)
        if state["status"] != "running":
            raise GameStateConflictError("The game is not active.")
        if state["players"]["w" if board.turn else "b"] != user_id:
            raise GameAccessError("It is not your turn.")

    @staticmethod
    def _parse_legal_move(board: chess.Board, uci: str) -> chess.Move:
        if not isinstance(uci, str) or len(uci) not in {4, 5}:
            raise InvalidMoveError("Move must be a valid UCI string.")
        try:
            move = chess.Move.from_uci(uci)
        except ValueError as exc:
            raise InvalidMoveError("Move must be a valid UCI string.") from exc
        if move not in board.legal_moves:
            raise InvalidMoveError("Move is not legal in the current position.")
        return move

    @staticmethod
    def _board(state: dict[str, Any]) -> chess.Board:
        board = chess.Board(state["start_fen"])
        for uci in state["moves_uci"]:
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                raise ValueError("Invalid stored game history.")
            board.push(move)
        if board.fen() != state["fen"]:
            raise ValueError("Stored game position does not match its history.")
        if not board.is_valid():
            raise ValueError("Invalid stored chess position.")
        return board

    @staticmethod
    def _termination(outcome: chess.Outcome) -> dict[str, Any]:
        names = {
            chess.Termination.CHECKMATE: "checkmate",
            chess.Termination.STALEMATE: "stalemate",
            chess.Termination.INSUFFICIENT_MATERIAL: "insufficient material",
            chess.Termination.SEVENTYFIVE_MOVES: "75-move rule",
            chess.Termination.FIVEFOLD_REPETITION: "fivefold repetition",
        }
        return {
            "result": outcome.result(),
            "reason": names.get(outcome.termination, "draw"),
            "winner": "w"
            if outcome.winner == chess.WHITE
            else "b"
            if outcome.winner == chess.BLACK
            else None,
        }

    @staticmethod
    def _key(game_id: str) -> str:
        return f"chessreview:game:{game_id}"

    class _GameLock:
        def __init__(self, store: LiveGameStore, game_id: str) -> None:
            self.store = store
            self.game_id = game_id
            self.token = secrets.token_urlsafe(24)

        async def __aenter__(self) -> None:
            key = f"chessreview:lock:{self.game_id}"
            for _ in range(30):
                if await self.store.redis.set(
                    key, self.token, nx=True, px=LOCK_TTL_MILLISECONDS
                ):
                    self.key = key
                    return None
                await asyncio.sleep(0.05)
            raise GameStateConflictError("Game is busy; retry the request.")

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            await self.store.redis.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] "
                "then return redis.call('del', KEYS[1]) else return 0 end",
                1,
                self.key,
                self.token,
            )

    def _locked(self, game_id: str) -> LiveGameStore._GameLock:
        return self._GameLock(self, game_id)
