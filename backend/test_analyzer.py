import asyncio

import chess
import chess.engine
import pytest

from backend.analyzer import (
    AnalysisBusyError,
    AnalysisError,
    ChessAnalyzer,
    EngineSettings,
    classify_move,
    _move_feedback,
    move_symbol,
)
from backend.main import RequestBodyLimitMiddleware, _compact_analysis


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
    assert "fen_before" not in compact["moves"][0]
    assert "best_move" not in compact["moves"][0]


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
        material_sacrifice_cp=299.0,
        eval_before=0.0,
        eval_after=2.0,
        is_tactical=True,
        is_book=False,
        is_best_move=True,
    ) == "Best"

    assert classify_move(
        win_prob_delta=0.0,
        current_win_prob=0.6,
        material_sacrifice_cp=300.0,
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
