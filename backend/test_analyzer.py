import asyncio
import hashlib
import io
import os
import tarfile
import time

import chess
import chess.engine
import jwt
import pytest
from fastapi import HTTPException

from backend import analyzer as analyzer_module
from backend import main as api
from backend.analyzer import (
    BRILLIANT_MIN_SACRIFICE_CP,
    AnalysisBusyError,
    AnalysisError,
    ChessAnalyzer,
    EngineSettings,
    classify_move,
    _move_feedback,
    _game_outcome,
    _resolve_engine_path,
    _strip_pgn_variations_and_comments,
    move_symbol,
)
from backend.main import RequestBodyLimitMiddleware, _compact_analysis


def test_official_stockfish_download_verifies_and_extracts_binary(tmp_path, monkeypatch):
    binary_contents = b"trusted-stockfish-binary"
    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
        member = tarfile.TarInfo("stockfish/stockfish-linux-x86-64")
        member.size = len(binary_contents)
        member.mode = 0o755
        archive.addfile(member, io.BytesIO(binary_contents))
    archive_contents = archive_buffer.getvalue()

    class FakeResponse(io.BytesIO):
        def __init__(self, contents):
            super().__init__(contents)
            self.headers = {"Content-Length": str(len(contents))}

    downloaded_urls = []

    def fake_urlopen(request, timeout):
        downloaded_urls.append((request.full_url, timeout))
        return FakeResponse(archive_contents)

    chmod_calls = []

    def fake_path_chmod(path, mode, *, follow_symlinks=True):
        chmod_calls.append(mode)

    monkeypatch.setattr(analyzer_module.sys, "platform", "linux")
    monkeypatch.setattr(analyzer_module.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(analyzer_module.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        analyzer_module,
        "_STOCKFISH_ARCHIVE_SHA256",
        hashlib.sha256(archive_contents).hexdigest(),
    )
    monkeypatch.setattr(analyzer_module, "urlopen", fake_urlopen)
    monkeypatch.setattr(analyzer_module.Path, "chmod", fake_path_chmod)
    monkeypatch.setattr(
        analyzer_module.os,
        "chmod",
        lambda path, mode, **kwargs: chmod_calls.append(mode),
    )

    executable = analyzer_module._download_official_linux_stockfish()

    assert executable.read_bytes() == binary_contents
    assert downloaded_urls == [(analyzer_module._STOCKFISH_ARCHIVE_URL, 30)]
    assert chmod_calls == [0o700, 0o700]


def test_resolve_engine_path_downloads_stockfish_when_missing_on_linux(tmp_path, monkeypatch):
    executable = tmp_path / "stockfish"
    executable.touch()
    monkeypatch.setattr(analyzer_module.sys, "platform", "linux")
    monkeypatch.setattr(analyzer_module.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(analyzer_module.shutil, "which", lambda *args, **kwargs: None)
    monkeypatch.setattr(analyzer_module, "_download_official_linux_stockfish", lambda: executable)

    assert _resolve_engine_path("stockfish") == str(executable)


def test_analyze_pgn_returns_opening_book_move_without_engine():
    analyzer = ChessAnalyzer(EngineSettings())

    result = analyzer._analyze_pgn("1. e4", depth=20)

    assert len(result["moves"]) == 1
    move = result["moves"][0]
    assert move["classification"] == "book"
    assert move["category"] == "book"
    assert move["centipawn_loss"] == 0
    assert move["win_prob_delta"] == 0.0
    assert "recognized opening line" in move["explanation"]
    assert "Continue developing" in move["suggestion"]


def test_analyze_pgn_scores_non_book_move_with_engine_results(monkeypatch):
    analyzer = ChessAnalyzer(EngineSettings())
    analyzer._engine = object()
    best_move = chess.Move.from_uci("e2e4")
    before_info = [
        {"score": chess.engine.PovScore(chess.engine.Cp(50), chess.WHITE), "pv": [best_move]},
        {
            "score": chess.engine.PovScore(chess.engine.Cp(20), chess.WHITE),
            "pv": [chess.Move.from_uci("d2d4")],
        },
        {
            "score": chess.engine.PovScore(chess.engine.Cp(10), chess.WHITE),
            "pv": [chess.Move.from_uci("g1f3")],
        },
    ]
    after_info = {
        "score": chess.engine.PovScore(chess.engine.Cp(30), chess.WHITE),
        "pv": [chess.Move.from_uci("e7e5")],
    }

    def fake_analyze(board, depth, multipv=1):
        return before_info if multipv > 1 else [after_info]

    monkeypatch.setattr(analyzer, "_engine_analyze", fake_analyze)

    result = analyzer.analyze("1. a3", depth=20)

    move = result["moves"][0]
    assert move["classification"] == "good"
    assert move["best_move"]["san"] == "e4"
    assert move["centipawn_loss"] == 20
    assert move["win_prob_delta"] > 0


def test_engine_analysis_normalizes_single_pv_result_to_list():
    class FakeEngine:
        def analyse(self, board, limit, multipv):
            return {"score": chess.engine.PovScore(chess.engine.Cp(25), chess.WHITE)}

    analyzer = ChessAnalyzer(EngineSettings())
    analyzer._engine = FakeEngine()

    result = analyzer._engine_analyze(chess.Board(), depth=18)

    assert len(result) == 1
    assert result[0]["score"].white().score() == 25


def test_default_analysis_depth_is_15_and_range_is_enforced(monkeypatch):
    analyzer = ChessAnalyzer(EngineSettings())
    analyzer._engine = object()
    analyzed_depths = []
    monkeypatch.setattr(
        analyzer,
        "_analyze_pgn",
        lambda pgn, depth: analyzed_depths.append(depth) or {"moves": []},
    )

    analyzer.analyze("1. e4")

    assert analyzed_depths == [15]
    with pytest.raises(AnalysisError, match="between 10 and 20"):
        analyzer.analyze("1. e4", depth=21)


def test_fen_analysis_reads_single_pv_engine_result(monkeypatch):
    analyzer = ChessAnalyzer(EngineSettings())
    score = chess.engine.PovScore(chess.engine.Cp(125), chess.WHITE)
    monkeypatch.setattr(analyzer, "_engine_score", lambda board, depth: score)

    result = analyzer._analyze_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 18)

    assert result is not None
    assert result["final_evaluation"] == 1.25


def test_invalid_fen_is_rejected_before_engine_analysis():
    analyzer = ChessAnalyzer(EngineSettings())

    with pytest.raises(AnalysisError, match="Invalid FEN"):
        analyzer._analyze_fen("8/8/8/8/8/8/8/8 w - - 0 1", depth=20)


def test_analyzer_rejects_concurrent_work_instead_of_queueing_unboundedly():
    analyzer = ChessAnalyzer(EngineSettings())
    analyzer._engine = object()
    analyzer._lock.acquire()

    try:
        with pytest.raises(AnalysisBusyError):
            analyzer.analyze("1. e4", depth=20)
    finally:
        analyzer._lock.release()


def test_request_body_limit_rejects_chunked_oversized_body():
    messages = iter(
        [
            {"type": "http.request", "body": b"1234", "more_body": True},
            {"type": "http.request", "body": b"5", "more_body": False},
        ]
    )
    sent = []

    async def downstream(scope, receive, send):
        raise AssertionError("Oversized body reached the application.")

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/analyze",
        "headers": [],
    }

    asyncio.run(RequestBodyLimitMiddleware(downstream, max_bytes=4)(scope, receive, send))

    assert sent[0]["status"] == 413


def test_compact_analysis_keeps_only_fields_used_by_the_review_ui():
    result = {
        "metadata": {"white": "White", "black": "Black", "result": "*"},
        "moves": [
            {
                "ply": 0,
                "move_number": 1,
                "san": "e4",
                "uci": "e2e4",
                "color": "w",
                "from": "e2",
                "to": "e4",
                "fen_before": "before",
                "fen_after": "after",
                "evaluation_before": 0.0,
                "evaluation": 0.2,
                "score_before": {"type": "cp", "value": 0},
                "score_after": {"type": "cp", "value": 20},
                "classification": "good",
                "explanation": "A safe move.",
                "suggestion": "Try d4.",
                "best_move": {"san": "d4", "uci": "d2d4"},
            }
        ],
    }

    compact = _compact_analysis(result)

    assert compact["metadata"] == result["metadata"]
    assert compact["moves"][0]["fen_after"] == "after"
    assert compact["moves"][0]["explanation"] == "A safe move."
    assert compact["moves"][0]["suggestion"] == "Try d4."
    assert compact["moves"][0]["fen_before"] == "before"
    assert compact["moves"][0]["best_move"] == result["moves"][0]["best_move"]


def test_supabase_hs256_token_requires_standard_authenticated_claims(monkeypatch):
    secret = "test-only-signing-secret-for-hs256"
    issuer = "https://project.supabase.co/auth/v1"
    monkeypatch.setattr(api, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(api, "jwks_client", None)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", secret)

    token = jwt.encode(
        {
            "sub": "user-123",
            "iss": issuer,
            "aud": "authenticated",
            "exp": int(time.time()) + 60,
            "role": "authenticated",
        },
        secret,
        algorithm="HS256",
    )
    assert api._decode_user_token(token) == "user-123"

    wrong_role = jwt.encode(
        {
            "sub": "user-123",
            "iss": issuer,
            "aud": "authenticated",
            "exp": int(time.time()) + 60,
            "role": "service_role",
        },
        secret,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as error:
        api._decode_user_token(wrong_role)
    assert error.value.status_code == 401


def test_live_game_store_is_unavailable_when_redis_is_optional_and_offline(monkeypatch):
    monkeypatch.setattr(api, "redis_available", False)
    monkeypatch.setattr(api, "redis_client", None)
    monkeypatch.setattr(api, "live_games", None)

    with pytest.raises(HTTPException) as error:
        api._require_game_store()
    assert error.value.status_code == 503


def test_classify_move_categories_and_symbols():
    assert classify_move(
        win_prob_delta=0.0,
        current_win_prob=0.5,
        material_sacrifice_cp=0.0,
        eval_before=0.0,
        eval_after=0.0,
        is_tactical=False,
        is_book=False,
        is_best_move=True,
    ) == "Best"
    assert move_symbol("Best") == "★"

    assert classify_move(
        win_prob_delta=0.0,
        current_win_prob=0.5,
        eval_before=0.0,
        eval_after=0.0,
        is_tactical=False,
        is_book=False,
        is_best_move=False,
    ) == "Excellent"

    assert classify_move(
        win_prob_delta=0.06,
        current_win_prob=0.55,
        material_sacrifice_cp=0.0,
        eval_before=0.2,
        eval_after=-0.2,
        is_tactical=False,
        is_book=False,
    ) == "Inaccuracy"
    assert move_symbol("Inaccuracy") == "?!"

    assert classify_move(
        win_prob_delta=0.12,
        current_win_prob=0.6,
        material_sacrifice_cp=0.0,
        eval_before=0.3,
        eval_after=-0.8,
        is_tactical=False,
        is_book=False,
    ) == "Mistake"
    assert move_symbol("Mistake") == "?"

    assert classify_move(
        win_prob_delta=0.38,
        current_win_prob=0.4,
        material_sacrifice_cp=0.0,
        eval_before=0.1,
        eval_after=-2.5,
        is_tactical=False,
        is_book=False,
    ) == "Blunder"
    assert move_symbol("Blunder") == "??"

    assert classify_move(
        win_prob_delta=0.04,
        current_win_prob=0.6,
        material_sacrifice_cp=300.0,
        eval_before=-0.3,
        eval_after=2.0,
        is_tactical=True,
        is_book=False,
        is_best_move=True,
    ) == "Brilliant"
    assert move_symbol("Brilliant") == "!!"

    assert classify_move(
        win_prob_delta=0.0,
        current_win_prob=0.6,
        material_sacrifice_cp=0.0,
        eval_before=0.0,
        eval_after=2.0,
        is_tactical=True,
        is_book=False,
        is_best_move=True,
    ) == "Best"

    assert classify_move(
        win_prob_delta=0.0,
        current_win_prob=0.6,
        material_sacrifice_cp=200.0,
        eval_before=0.0,
        eval_after=2.0,
        is_tactical=True,
        is_book=False,
        is_best_move=True,
    ) == "Brilliant"

    assert classify_move(
        win_prob_delta=0.0,
        current_win_prob=0.6,
        material_sacrifice_cp=199.0,
        eval_before=0.0,
        eval_after=-0.25,
        is_tactical=True,
        is_book=False,
        is_best_move=True,
    ) == "Best"

    assert classify_move(
        win_prob_delta=0.04,
        current_win_prob=0.5,
        material_sacrifice_cp=300.0,
        eval_before=0.0,
        eval_after=0.2,
        is_tactical=True,
        is_book=False,
        is_best_move=True,
    ) == "Brilliant"

    assert classify_move(
        win_prob_delta=0.0,
        current_win_prob=0.6,
        material_sacrifice_cp=300.0,
        eval_before=0.0,
        eval_after=2.0,
        is_tactical=True,
        is_book=False,
        is_best_move=False,
    ) == "Excellent"

    assert classify_move(
        win_prob_delta=0.03,
        current_win_prob=0.5,
        material_sacrifice_cp=0.0,
        eval_before=-1.0,
        eval_after=0.4,
        is_tactical=False,
        is_book=False,
        is_best_move=True,
        second_best_wdl_drop=0.35,
    ) == "Great"
    assert move_symbol("Great") == "!"

    assert classify_move(
        win_prob_delta=0.015,
        current_win_prob=0.5,
        material_sacrifice_cp=0.0,
        eval_before=0.2,
        eval_after=0.4,
        is_tactical=False,
        is_book=False,
    ) == "Excellent"
    assert move_symbol("Excellent") == "✔"
    assert move_symbol("Good") == ""

    assert classify_move(
        win_prob_delta=0.3,
        current_win_prob=0.7,
        material_sacrifice_cp=0.0,
        eval_before=0.5,
        eval_after=0.0,
        is_tactical=False,
        is_book=False,
        missed_tactical_sequence=True,
    ) == "Miss"
    assert move_symbol("Miss") == "❌"


def test_top_engine_move_is_best_even_when_followup_score_differs():
    assert classify_move(
        win_prob_delta=0.2,
        current_win_prob=0.7,
        is_best_move=True,
    ) == "Best"


def test_large_non_tactical_evaluation_loss_is_blunder_not_miss():
    assert classify_move(
        win_prob_delta=0.6,
        current_win_prob=0.5,
        is_best_move=False,
    ) == "Blunder"


def test_miss_is_reserved_for_a_missed_tactical_opportunity():
    assert classify_move(
        win_prob_delta=0.6,
        current_win_prob=0.5,
        is_best_move=False,
        missed_tactical_sequence=True,
    ) == "Miss"


def test_missed_forced_mate_is_a_miss_not_a_blunder():
    assert classify_move(
        win_prob_delta=0.5,
        current_win_prob=0.8,
        is_best_move=False,
        lost_forced_mate=True,
    ) == "Miss"


def test_allowing_opponent_forced_mate_is_a_blunder():
    assert classify_move(
        win_prob_delta=0.5,
        current_win_prob=0.8,
        is_best_move=False,
        missed_mate=True,
    ) == "Blunder"


@pytest.mark.parametrize(
    ("classification", "is_best_move", "is_book", "expected_text"),
    [
        ("Brilliant", True, False, "engine's top move"),
        ("Great", True, False, "critical top move"),
        ("Best", True, False, "top-recommended move"),
        ("Excellent", False, False, "not the top move"),
        ("Good", False, False, "safe, playable move"),
        ("Book", True, True, "recognized opening line"),
        ("Inaccuracy", False, False, "easier for your opponent"),
        ("Mistake", False, False, "significant setback"),
        ("Miss", False, False, "missed a forcing opportunity"),
        ("Blunder", False, False, "serious error"),
    ],
)
def test_move_feedback_uses_fixed_templates_and_includes_a_suggestion(
    classification, is_best_move, is_book, expected_text
):
    explanation, suggestion = _move_feedback(
        classification=classification,
        san="a3",
        best_move_san="d4",
        loss_cp=85,
        material_sacrifice=3.0,
        eval_after=1.2,
        is_best_move=is_best_move,
        is_book=is_book,
        missed_mate=False,
        missed_tactical_sequence=False,
        lost_forced_mate=False,
        second_best_wdl_drop=0.35,
        depth=15,
    )

    assert expected_text in explanation
    if is_book:
        assert "engine did not separately compare" in explanation
        assert "Continue developing" in suggestion
    elif is_best_move:
        assert "Keep a3" in suggestion
        assert "depth 15" in suggestion
    else:
        assert "Prefer d4 instead" in suggestion
        assert "depth 15" in suggestion


def test_move_feedback_explains_forced_mate_miss_and_blunder():
    common = {
        "san": "a3",
        "best_move_san": "Qh7#",
        "loss_cp": 100_000,
        "material_sacrifice": 0,
        "eval_after": -20.0,
        "is_best_move": False,
        "is_book": False,
        "missed_tactical_sequence": False,
        "second_best_wdl_drop": 0,
        "depth": 15,
    }

    miss_explanation, _ = _move_feedback(
        classification="Miss",
        missed_mate=False,
        lost_forced_mate=True,
        **common,
    )
    blunder_explanation, _ = _move_feedback(
        classification="Blunder",
        missed_mate=True,
        lost_forced_mate=False,
        **common,
    )

    assert "checkmate was available for you" in miss_explanation
    assert "checkmate for your opponent" in blunder_explanation


def test_brilliant_threshold_is_exactly_two_hundred_centipawns():
    assert BRILLIANT_MIN_SACRIFICE_CP == 200.0
    assert classify_move(
        win_prob_delta=0.0,
        current_win_prob=0.6,
        material_sacrifice_cp=200.0,
        eval_before=0.0,
        eval_after=0.0,
        is_best_move=True,
    ) == "Brilliant"


def test_pgn_preprocessor_strips_nested_variations_and_keeps_clock_tags():
    cleaned = _strip_pgn_variations_and_comments(
        '[Event "Test"]\n1. e4 {main note} (1. d4 (1... Nf6)) e5 {[%clk 0:04:59]} ; tail\n'
    )

    assert "(1." not in cleaned
    assert "main note" not in cleaned
    assert "tail" not in cleaned
    assert "1. e4" in cleaned and "e5" in cleaned
    assert "[%clk 0:04:59]" in cleaned


@pytest.mark.parametrize(
    ("fen", "reason"),
    [
        ("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3", "checkmate"),
        ("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", "stalemate"),
        ("8/8/8/8/8/8/4k3/6K1 w - - 0 1", "insufficient material"),
        ("8/8/8/8/8/4k3/8/4K2R w - - 100 1", "50-move rule"),
        ("8/8/8/8/8/4k3/8/4K2R w - - 150 1", "75-move rule"),
    ],
)
def test_terminal_fen_skips_stockfish(fen, reason):
    result = ChessAnalyzer(EngineSettings())._analyze_fen(fen, depth=15)
    assert result is not None
    assert result["termination"]["reason"] == reason


def test_public_analysis_handles_terminal_fen_without_running_engine():
    analyzer = ChessAnalyzer(EngineSettings())

    result = analyzer.analyze("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")

    assert result["termination"]["reason"] == "stalemate"


def test_checkmating_pgn_move_skips_post_move_engine_analysis(monkeypatch):
    analyzer = ChessAnalyzer(EngineSettings())
    analyzer._engine = object()
    best_move = chess.Move.from_uci("d8h4")
    calls = []

    def fake_analyze(board, depth, multipv=1):
        calls.append(board.fen())
        return [
            {
                "score": chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE),
                "pv": [best_move],
            }
        ]

    monkeypatch.setattr(analyzer, "_engine_analyze", fake_analyze)
    pgn = (
        '[SetUp "1"]\n'
        '[FEN "rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq - 0 2"]\n\n'
        "2... Qh4#"
    )

    result = analyzer.analyze(pgn)

    assert len(calls) == 1
    assert result["termination"]["reason"] == "checkmate"
    assert result["final_evaluation"] <= -19.9


def test_mainline_is_bounded_before_python_chess_builds_a_tree():
    analyzer = ChessAnalyzer(EngineSettings())
    excessive_game = " ".join(["1. e4"] * 501)
    with pytest.raises(AnalysisError, match="500 plies"):
        analyzer._analyze_pgn(excessive_game, depth=15)


def test_terminal_pgn_without_moves_is_returned_without_engine_analysis():
    pgn = (
        '[SetUp "1"]\n'
        '[FEN "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"]\n'
        '[Result "*"]\n\n'
    )
    result = ChessAnalyzer(EngineSettings())._analyze_pgn(pgn, depth=15)

    assert result["termination"]["reason"] == "checkmate"
    assert result["metadata"]["result"] == "0-1"


def test_pgn_clock_annotations_are_returned_with_move_metadata():
    result = ChessAnalyzer(EngineSettings())._analyze_pgn(
        "1. e4 {[%clk 0:04:58]}", depth=15
    )

    assert result["moves"][0]["clock"] == "0:04:58"
    assert result["moves"][0]["fen_before"]
    assert result["moves"][0]["best_move"] == {"san": "e4", "uci": "e2e4"}


def test_automatic_fivefold_repetition_is_detected():
    board = chess.Board()
    cycle = ["g1f3", "g8f6", "f3g1", "f6g8"]
    for _ in range(4):
        for uci in cycle:
            board.push_uci(uci)

    outcome = _game_outcome(board)

    assert outcome is not None
    assert outcome.termination == chess.Termination.FIVEFOLD_REPETITION


def test_engine_path_resolution_never_falls_back_to_current_directory(
    tmp_path, monkeypatch
):
    local_engine = tmp_path / "stockfish-test"
    local_engine.write_text("not an executable engine")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(FileNotFoundError, match="PATH"):
        _resolve_engine_path("stockfish-test")


def test_black_brilliant_move_uses_mover_relative_evaluation(monkeypatch):
    analyzer = ChessAnalyzer(EngineSettings())
    analyzer._engine = object()
    best_move = chess.Move.from_uci("a7a6")
    before_info = [
        {"score": chess.engine.PovScore(chess.engine.Cp(-200), chess.WHITE), "pv": [best_move]},
        {
            "score": chess.engine.PovScore(chess.engine.Cp(-150), chess.WHITE),
            "pv": [chess.Move.from_uci("g8f6")],
        },
    ]
    after_info = {
        "score": chess.engine.PovScore(chess.engine.Cp(-250), chess.WHITE),
        "pv": [chess.Move.from_uci("e4e5")],
    }
    def fake_analyze(board, depth, multipv=1):
        return before_info if multipv > 1 else [after_info]

    def fake_material_balance(board, color):
        return 5.0 if board.ply() == 1 else 2.0

    monkeypatch.setattr(analyzer, "_engine_analyze", fake_analyze)
    monkeypatch.setattr("backend.analyzer._material_balance", fake_material_balance)

    result = analyzer.analyze(
        '[SetUp "1"]\n'
        '[FEN "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"]\n'
        "\n1... a6",
        depth=20,
    )

    assert result["moves"][0]["classification"] == "brilliant"
