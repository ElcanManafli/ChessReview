import asyncio

import pytest

from backend.live_games import InvalidMoveError, LiveGameStore


class MemoryRedis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, nx=False, px=None, ex=None):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    async def eval(self, script, numkeys, key, token):
        if self.values.get(key) == token:
            del self.values[key]
            return 1
        return 0


def test_move_validation_uses_redis_board_and_only_legal_moves():
    async def scenario():
        store = LiveGameStore(MemoryRedis())
        created = await store.create("white-user", 60_000, 0)
        await store.join(created["game_id"], "black-user")

        with pytest.raises(InvalidMoveError):
            await store.validate_move(created["game_id"], "white-user", "e2e5")

        validation = await store.validate_move(created["game_id"], "white-user", "e2e4")
        assert validation["san"] == "e4"
        assert validation["fen_before"] == created["fen"]

        played = await store.play_move(created["game_id"], "white-user", "e2e4")
        assert played["fen"] == validation["fen_after"]
        assert played["moves_uci"] == ["e2e4"]
        assert played["version"] == 2

    asyncio.run(scenario())


def test_live_game_detects_checkmate_and_preserves_full_history():
    async def scenario():
        store = LiveGameStore(MemoryRedis())
        created = await store.create("white-user", 60_000, 0)
        game_id = created["game_id"]
        await store.join(game_id, "black-user")
        line = [
            ("white-user", "e2e4"),
            ("black-user", "e7e5"),
            ("white-user", "f1c4"),
            ("black-user", "b8c6"),
            ("white-user", "d1h5"),
            ("black-user", "g8f6"),
            ("white-user", "h5f7"),
        ]
        for user_id, uci in line:
            result = await store.play_move(game_id, user_id, uci)

        assert result["status"] == "finished"
        assert result["termination"]["reason"] == "checkmate"
        assert result["termination"]["result"] == "1-0"
        assert len(result["moves_uci"]) == 7

    asyncio.run(scenario())


def test_threefold_claim_uses_persisted_move_history():
    async def scenario():
        store = LiveGameStore(MemoryRedis())
        created = await store.create("white-user", 60_000, 0)
        game_id = created["game_id"]
        await store.join(game_id, "black-user")
        cycle = [
            ("white-user", "g1f3"),
            ("black-user", "g8f6"),
            ("white-user", "f3g1"),
            ("black-user", "f6g8"),
        ]
        for _ in range(2):
            for user_id, uci in cycle:
                await store.play_move(game_id, user_id, uci)

        result = await store.claim_draw(game_id, "white-user")
        assert result["status"] == "finished"
        assert result["termination"]["reason"] == "threefold repetition"
        assert result["termination"]["result"] == "1/2-1/2"

    asyncio.run(scenario())
