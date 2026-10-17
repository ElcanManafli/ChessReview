from __future__ import annotations

import os
import logging
from collections import deque
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)
ANALYZER_IMPORT_ERROR: str | None = None

try:
    try:
        from backend.analyzer import AnalysisBusyError, AnalysisError, ChessAnalyzer, EngineSettings
    except ModuleNotFoundError as exc:
        if exc.name != "backend":
            raise
        from analyzer import AnalysisBusyError, AnalysisError, ChessAnalyzer, EngineSettings
except ModuleNotFoundError as exc:
    if exc.name != "chess" and not (exc.name or "").startswith("chess."):
        raise
    ANALYZER_IMPORT_ERROR = "python-chess not installed. Install backend/requirements.txt."
    AnalysisBusyError = RuntimeError
    AnalysisError = ValueError
    ChessAnalyzer = None
    EngineSettings = None


def _positive_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}.")
    return value


MAX_REQUEST_BODY_BYTES = 1_100_000
COMPACT_MOVE_FIELDS = (
    "ply",
    "move_number",
    "san",
    "uci",
    "color",
    "from",
    "to",
    "fen_after",
    "evaluation",
    "score_after",
    "classification",
    "explanation",
    "suggestion",
)


class RequestBodyLimitMiddleware:
    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] not in {"/api/analyze", "/api/analyze/file"}
        ):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                response = JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header."},
                )
                await response(scope, receive, send)
                return

        buffered = deque()
        total_bytes = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                break
            total_bytes += len(message.get("body", b""))
            if total_bytes > self.max_bytes:
                await self._reject(scope, receive, send)
                return
            buffered.append(message)
            if not message.get("more_body", False):
                break

        async def replay_receive():
            if buffered:
                return buffered.popleft()
            return await receive()

        await self.app(scope, replay_receive, send)

    async def _reject(self, scope, receive, send) -> None:
        response = JSONResponse(
            status_code=413,
            content={"detail": "Request body exceeds the 1 MB limit."},
        )
        await response(scope, receive, send)


analyzer = None
if ANALYZER_IMPORT_ERROR is None:
    settings = EngineSettings(
        path=os.getenv("STOCKFISH_PATH", "stockfish.exe" if os.name == "nt" else "stockfish"),
        depth=_positive_int("STOCKFISH_DEPTH", 15, 10, 20),
        threads=_positive_int("STOCKFISH_THREADS", 2, 1, 64),
        hash_mb=_positive_int("STOCKFISH_HASH_MB", 256, 16, 4096),
        timeout_seconds=30.0,
    )
    analyzer = ChessAnalyzer(settings)

engine_ready = False
engine_error: str | None = ANALYZER_IMPORT_ERROR or "Stockfish engine has not been started."


@asynccontextmanager
async def lifespan(_: FastAPI):
    global engine_error, engine_ready
    if analyzer is not None:
        try:
            analyzer.start()
        except FileNotFoundError as exc:
            engine_error = f"Stockfish executable missing: {exc}"
            logger.error(engine_error)
        except Exception as exc:
            engine_error = f"Stockfish engine failed to start: {exc}"
            logger.exception(engine_error)
        else:
            engine_ready = True
            engine_error = None
    yield
    if analyzer is not None and engine_ready:
        try:
            analyzer.close()
        except Exception:
            logger.exception("Failed to close Stockfish cleanly.")
        finally:
            engine_ready = False
            engine_error = "Stockfish engine is not running."


app = FastAPI(
    title="ChessReview Analysis API",
    version="1.0.0",
    description="PGN and FEN analysis powered by python-chess and Stockfish.",
    lifespan=lifespan,
)

app.add_middleware(RequestBodyLimitMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)

cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        (
            "http://localhost:5173,http://127.0.0.1:5173,"
            "http://localhost:8080,http://127.0.0.1:8080,"
            "http://localhost:8081,http://127.0.0.1:8081"
        ),
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    pgn: str = Field(min_length=1, max_length=1_000_000)


def _run_analysis(text: str, depth: int | None, compact: bool = False) -> dict:
    _require_engine()
    try:
        result = analyzer.analyze(text, depth)
        return _compact_analysis(result) if compact else result
    except AnalysisBusyError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except AnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Chess engine analysis failed.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _compact_analysis(result: dict) -> dict:
    return {
        **result,
        "moves": [
            {field: move[field] for field in COMPACT_MOVE_FIELDS}
            for move in result["moves"]
        ],
    }


def _require_engine() -> None:
    if not engine_ready:
        raise HTTPException(
            status_code=503,
            detail=engine_error or "Chess analysis engine is unavailable.",
        )


@app.get("/api/health")
def health() -> dict[str, str]:
    _require_engine()
    return {"status": "ok", "engine": "stockfish"}


@app.post("/api/analyze")
def analyze_game(
    payload: AnalyzeRequest,
    depth: Annotated[int | None, Query(ge=10, le=20)] = None,
    compact: bool = Query(default=False),
) -> dict:
    return _run_analysis(payload.pgn, depth, compact)


@app.post("/api/analyze/file")
def analyze_file(
    request: Request,
    file: Annotated[UploadFile, File()],
    depth: Annotated[int | None, Query(ge=10, le=20)] = None,
    compact: bool = Query(default=False),
) -> dict:
    content_length = request.headers.get("content-length")
    try:
        request_size = int(content_length) if content_length else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Content-Length header.") from exc
    if request_size is not None and request_size > 1_100_000:
        raise HTTPException(status_code=413, detail="Upload exceeds the 1 MB limit.")
    contents = file.file.read(1_000_001)
    if len(contents) > 1_000_000:
        raise HTTPException(status_code=413, detail="Upload exceeds the 1 MB limit.")
    try:
        text = contents.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="PGN files must be UTF-8 encoded.") from exc
    return _run_analysis(text, depth, compact)