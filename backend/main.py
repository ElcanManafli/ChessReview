from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from typing import Annotated, Any
from urllib.parse import urlsplit, urlunsplit

import chess
import jwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

try:
    from backend.analyzer import (
        AnalysisBusyError,
        AnalysisError,
        AnalysisTimeoutError,
        ChessAnalyzer,
        EngineUnavailableError,
        EngineSettings,
    )
    from backend.live_games import (
        GameAccessError,
        GameNotFoundError,
        GameStateConflictError,
        InvalidMoveError,
        LiveGameError,
        LiveGameStore,
    )
except ModuleNotFoundError as exc:
    if exc.name != "backend":
        raise
    from analyzer import (
        AnalysisBusyError,
        AnalysisError,
        AnalysisTimeoutError,
        ChessAnalyzer,
        EngineUnavailableError,
        EngineSettings,
    )
    from live_games import (
        GameAccessError,
        GameNotFoundError,
        GameStateConflictError,
        InvalidMoveError,
        LiveGameError,
        LiveGameStore,
    )


logger = logging.getLogger(__name__)
MAX_REQUEST_BODY_BYTES = 1_100_000
MAX_PGN_BYTES = 1_000_000
COMPACT_MOVE_FIELDS = (
    "ply",
    "move_number",
    "san",
    "uci",
    "color",
    "from",
    "to",
    "fen_before",
    "fen_after",
    "best_move",
    "evaluation",
    "score_after",
    "centipawn_loss",
    "win_prob_delta",
    "clock",
    "classification",
    "explanation",
    "suggestion",
)
ALLOWED_UPLOAD_EXTENSIONS = {".pgn", ".fen", ".txt"}
ALLOWED_UPLOAD_MIME_TYPES = {
    "application/octet-stream",
    "application/x-chess-pgn",
    "text/plain",
}
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _positive_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _normalize_supabase_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise RuntimeError("SUPABASE_URL must be an absolute HTTP(S) project URL.")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("SUPABASE_URL must use HTTPS outside localhost.")
    path = parsed.path.rstrip("/")
    if path.lower().endswith("/rest/v1"):
        path = path[: -len("/rest/v1")]
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")


def _parse_origins() -> list[str]:
    raw_origins = os.getenv(
        "CORS_ORIGINS",
        (
            "http://localhost:5173,http://127.0.0.1:5173,"
            "http://localhost:8080,http://127.0.0.1:8080,"
            "http://localhost:8081,http://127.0.0.1:8081"
        ),
    )
    origins = [origin.strip().rstrip("/") for origin in raw_origins.split(",") if origin.strip()]
    if not origins or "*" in origins:
        raise RuntimeError("CORS_ORIGINS must contain explicit origins and cannot contain '*'.")
    for origin in origins:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path:
            raise RuntimeError("Each CORS_ORIGINS entry must be an origin without a path.")
    return origins


cors_origins = _parse_origins()
supabase_url = _normalize_supabase_url(os.getenv("SUPABASE_URL"))
stockfish_path = os.getenv("STOCKFISH_PATH", "stockfish.exe" if os.name == "nt" else "stockfish")
settings = EngineSettings(
    path=stockfish_path,
    depth=_positive_int("STOCKFISH_DEPTH", 15, 10, 20),
    threads=_positive_int("STOCKFISH_THREADS", 2, 1, 64),
    hash_mb=_positive_int("STOCKFISH_HASH_MB", 256, 16, 4096),
    timeout_seconds=2.0,
    move_time_seconds=0.75,
    game_timeout_seconds=90.0,
)
analyzer = ChessAnalyzer(settings)
redis_client: Redis | None = None
live_games: LiveGameStore | None = None
redis_available = False
jwks_client: PyJWKClient | None = None
if supabase_url:
    jwks_client = PyJWKClient(
        f"{supabase_url}/auth/v1/.well-known/jwks.json",
        cache_jwk_set=True,
        lifespan=3600,
        timeout=5,
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
                await JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header."},
                )(scope, receive, send)
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
        await JSONResponse(
            status_code=413,
            content={"detail": "Request body exceeds the 1 MB limit."},
        )(scope, receive, send)


class RequestSafetyMiddleware:
    def __init__(self, app) -> None:
        self.app = app
        self.requests: dict[tuple[str, str], deque[float]] = {}

    async def __call__(self, scope, receive, send) -> None:
        kind = scope["type"]
        if kind not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        supplied_id = headers.get(b"x-request-id", b"").decode("ascii", "ignore")
        request_id = supplied_id if REQUEST_ID_PATTERN.fullmatch(supplied_id) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        remote = scope.get("client")
        client_ip = remote[0] if remote else "unknown"
        path = scope.get("path", "")
        group = "analysis" if path.startswith("/api/analyze") else "api"
        max_requests = 10 if group == "analysis" else 60
        if not self._allow(client_ip, group, max_requests):
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 4429})
            else:
                await JSONResponse(
                    status_code=429,
                    headers={
                        "Retry-After": "60",
                        "X-Request-ID": request_id,
                        "X-Content-Type-Options": "nosniff",
                        "X-Frame-Options": "DENY",
                        "Referrer-Policy": "no-referrer",
                        "Content-Security-Policy": (
                            "default-src 'none'; frame-ancestors 'none'; "
                            "base-uri 'none'; form-action 'none'"
                        ),
                        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                    },
                    content={"detail": "Request rate limit exceeded.", "request_id": request_id},
                )(scope, receive, send)
            return

        if kind == "websocket":
            await self.app(scope, receive, send)
            return

        async def safety_send(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.extend(
                    [
                        (b"x-request-id", request_id.encode("ascii")),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    ]
                )
                if scope.get("scheme") == "https":
                    response_headers.append(
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                    )
                message["headers"] = response_headers
            await send(message)

        await self.app(scope, receive, safety_send)

    def _allow(self, ip: str, group: str, limit: int) -> bool:
        now = time.monotonic()
        key = (ip, group)
        bucket = self.requests.setdefault(key, deque())
        while bucket and now - bucket[0] >= 60:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        if len(self.requests) > 50_000:
            expired = [
                entry
                for entry, events in self.requests.items()
                if not events or now - events[-1] >= 60
            ]
            for entry in expired:
                self.requests.pop(entry, None)
        return True


@asynccontextmanager
async def lifespan(_: FastAPI):
    global redis_client, live_games, redis_available
    try:
        analyzer.start()
    except Exception:
        logger.exception("Stockfish startup failed.")
    try:
        redis_client = Redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            max_connections=100,
        )
        live_games = LiveGameStore(redis_client)
        await redis_client.ping()
        redis_available = True
    except (RedisError, ValueError) as exc:
        logger.warning("Redis is unavailable; live game endpoints will return 503.")
        redis_available = False
        if redis_client is not None:
            await redis_client.aclose()
        redis_client = None
        live_games = None
    yield
    if analyzer is not None:
        analyzer.close()
    if redis_client is not None:
        await redis_client.aclose()
    redis_available = False


app = FastAPI(
    title="ChessReview API",
    version="2.0.0",
    description="Chess game analysis and authenticated Redis-backed live games.",
    lifespan=lifespan,
)
app.add_middleware(RequestBodyLimitMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)
app.add_middleware(RequestSafetyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    pgn: str = Field(min_length=1, max_length=MAX_PGN_BYTES)


class CreateGameRequest(BaseModel):
    initial_time_seconds: int = Field(default=300, ge=60, le=3600)
    increment_seconds: int = Field(default=0, ge=0, le=60)


class MoveRequest(BaseModel):
    game_id: str = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")
    uci: str = Field(min_length=4, max_length=5, pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")


class GameJoinRequest(BaseModel):
    game_id: str = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")


bearer_scheme = HTTPBearer(auto_error=False)


def _request_id(request: Request) -> str:
    return request.scope.get("state", {}).get("request_id", "unknown")


def _require_analyzer() -> ChessAnalyzer:
    return analyzer


def _decode_user_token(token: str) -> str:
    if not supabase_url:
        raise HTTPException(status_code=503, detail="Authentication is not configured.")
    try:
        legacy_secret = os.getenv("SUPABASE_JWT_SECRET")
        if legacy_secret:
            claims = jwt.decode(
                token,
                legacy_secret,
                algorithms=["HS256"],
                audience="authenticated",
                issuer=f"{supabase_url}/auth/v1",
                options={"require": ["exp", "sub", "aud", "iss", "role"]},
            )
        else:
            if jwks_client is None:
                raise jwt.InvalidTokenError("Signing key provider is unavailable.")
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256", "EdDSA"],
                audience="authenticated",
                issuer=f"{supabase_url}/auth/v1",
                options={"require": ["exp", "sub", "aud", "iss", "role"]},
            )
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise jwt.InvalidTokenError("Missing subject.")
        if claims.get("role") != "authenticated":
            raise jwt.InvalidTokenError("Invalid role.")
        return subject
    except (jwt.PyJWTError, OSError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired access token.") from exc


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer access token required.")
    return await run_in_threadpool(_decode_user_token, credentials.credentials)


def _require_game_store() -> LiveGameStore:
    if not redis_available or live_games is None or redis_client is None:
        raise HTTPException(status_code=503, detail="Live game service is unavailable.")
    return live_games


def _run_analysis(text: str, depth: int | None, compact: bool = False) -> dict[str, Any]:
    try:
        result = _require_analyzer().analyze(text, depth)
        return _compact_analysis(result) if compact else result
    except AnalysisBusyError as exc:
        raise HTTPException(status_code=429, detail="The analysis engine is busy; retry shortly.") from exc
    except AnalysisTimeoutError as exc:
        raise HTTPException(status_code=504, detail="Chess analysis exceeded its time limit.") from exc
    except EngineUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Chess analysis service is unavailable.") from exc
    except AnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Chess analysis failed.")
        raise HTTPException(status_code=500, detail="Chess analysis failed.") from exc


def _compact_analysis(result: dict[str, Any]) -> dict[str, Any]:
    return {
        **result,
        "moves": [
            {field: move[field] for field in COMPACT_MOVE_FIELDS if field in move}
            for move in result["moves"]
        ],
    }


def _safe_game_error(exc: LiveGameError) -> HTTPException:
    if isinstance(exc, GameNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, GameAccessError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, InvalidMoveError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, GameStateConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail="The game request could not be completed.")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = str(exc.detail) if exc.status_code < 500 else "Service is unavailable."
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={"detail": detail, "request_id": _request_id(request)},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = _request_id(request)
    logger.exception("Unhandled request failure; request_id=%s", request_id)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error.", "request_id": request_id},
    )


@app.exception_handler(RedisError)
async def redis_exception_handler(request: Request, exc: RedisError) -> JSONResponse:
    logger.warning("Redis request failed; request_id=%s", _request_id(request))
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Live game service is unavailable.",
            "request_id": _request_id(request),
        },
    )


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Request validation failed.",
            "request_id": _request_id(request),
        },
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    try:
        if not analyzer.health_check():
            raise RuntimeError("Stockfish health check failed.")
    except Exception as exc:
        logger.exception("Stockfish health check failed.")
        raise HTTPException(status_code=503, detail="Chess analysis service is unavailable.") from exc
    return {"status": "ok", "engine": "stockfish"}


@app.post("/api/analyze")
def analyze_game(
    payload: AnalyzeRequest,
    depth: Annotated[int | None, Query(ge=10, le=20)] = None,
    compact: bool = Query(default=False),
) -> dict[str, Any]:
    return _run_analysis(payload.pgn, depth, compact)


@app.post("/api/analyze/file")
def analyze_file(
    request: Request,
    file: Annotated[UploadFile, File()],
    depth: Annotated[int | None, Query(ge=10, le=20)] = None,
    compact: bool = Query(default=False),
) -> dict[str, Any]:
    if "\x00" in (file.filename or ""):
        raise HTTPException(status_code=400, detail="Invalid upload filename.")
    filename = re.split(r"[/\\]", file.filename or "")[-1]
    extension = os.path.splitext(filename)[1].lower()
    mime_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Upload must be a PGN, FEN, or TXT file.")
    if mime_type not in ALLOWED_UPLOAD_MIME_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported upload media type.")

    content_length = request.headers.get("content-length")
    try:
        request_size = int(content_length) if content_length else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Content-Length header.") from exc
    if request_size is not None and request_size > MAX_REQUEST_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds the 1 MB limit.")
    contents = file.file.read(MAX_PGN_BYTES + 1)
    if len(contents) > MAX_PGN_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds the 1 MB limit.")
    if b"\x00" in contents:
        raise HTTPException(status_code=422, detail="Uploaded files cannot contain null bytes.")
    try:
        text = contents.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="Uploads must be UTF-8 encoded.") from exc
    return _run_analysis(text, depth, compact)


@app.post("/api/games")
async def create_game(
    payload: CreateGameRequest,
    user_id: Annotated[str, Depends(current_user)],
) -> dict[str, Any]:
    try:
        return await _require_game_store().create(
            user_id,
            payload.initial_time_seconds * 1000,
            payload.increment_seconds * 1000,
        )
    except LiveGameError as exc:
        raise _safe_game_error(exc) from exc


@app.post("/api/games/join")
async def join_game(
    payload: GameJoinRequest,
    user_id: Annotated[str, Depends(current_user)],
) -> dict[str, Any]:
    try:
        return await _require_game_store().join(payload.game_id, user_id)
    except LiveGameError as exc:
        raise _safe_game_error(exc) from exc


@app.post("/api/move/validate")
async def validate_move(
    payload: MoveRequest,
    user_id: Annotated[str, Depends(current_user)],
) -> dict[str, Any]:
    try:
        return await _require_game_store().validate_move(
            payload.game_id, user_id, payload.uci
        )
    except LiveGameError as exc:
        raise _safe_game_error(exc) from exc


@app.post("/api/games/{game_id}/claim-draw")
async def claim_draw(
    game_id: str,
    user_id: Annotated[str, Depends(current_user)],
) -> dict[str, Any]:
    try:
        return await _require_game_store().claim_draw(game_id, user_id)
    except LiveGameError as exc:
        raise _safe_game_error(exc) from exc


@app.websocket("/ws/game")
async def game_socket(websocket: WebSocket, game_id: str = Query(min_length=32, max_length=32)) -> None:
    origin = websocket.headers.get("origin", "").rstrip("/")
    if origin not in cors_origins:
        await websocket.close(code=4403, reason="Origin not allowed.")
        return
    await websocket.accept()
    try:
        auth_message = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        if len(auth_message.encode("utf-8")) > 4096:
            await websocket.close(code=4400, reason="Invalid authentication message.")
            return
        auth = json.loads(auth_message)
        if (
            not isinstance(auth, dict)
            or auth.get("type") != "auth"
            or not isinstance(auth.get("token"), str)
        ):
            await websocket.close(code=4401, reason="Authentication required.")
            return
        user_id = await asyncio.to_thread(_decode_user_token, auth["token"])
        store = _require_game_store()
        state = await store.snapshot(game_id, user_id)
        await websocket.send_json({"type": "state", "game": state})
        last_version = state["version"]
        last_clock_update = time.monotonic()
        action_times: deque[float] = deque()
        while True:
            try:
                message_text = await asyncio.wait_for(websocket.receive_text(), timeout=0.5)
            except TimeoutError:
                message_text = ""
            if message_text:
                if len(message_text.encode("utf-8")) > 4096:
                    await websocket.send_json({"type": "error", "detail": "Message exceeds size limit."})
                    continue
                action_now = time.monotonic()
                while action_times and action_now - action_times[0] >= 60:
                    action_times.popleft()
                if len(action_times) >= 30:
                    await websocket.send_json({"type": "error", "detail": "Game action rate limit exceeded."})
                    continue
                action_times.append(action_now)
                try:
                    message = json.loads(message_text)
                    if not isinstance(message, dict):
                        raise ValueError
                    if message.get("type") == "move":
                        state = await store.play_move(game_id, user_id, message.get("uci"))
                    elif message.get("type") == "claim_draw":
                        state = await store.claim_draw(game_id, user_id)
                    else:
                        await websocket.send_json({"type": "error", "detail": "Unsupported game action."})
                        continue
                except (ValueError, TypeError):
                    await websocket.send_json({"type": "error", "detail": "Invalid game message."})
                    continue
                except LiveGameError as exc:
                    await websocket.send_json({"type": "error", "detail": str(exc)})
                    continue

            now = time.monotonic()
            if message_text or now - last_clock_update >= 1:
                try:
                    state = await store.snapshot(game_id, user_id)
                except LiveGameError as exc:
                    await websocket.send_json({"type": "error", "detail": str(exc)})
                    await websocket.close(code=4403)
                    return
                if state["version"] != last_version or now - last_clock_update >= 1:
                    await websocket.send_json({"type": "state", "game": state})
                    last_version = state["version"]
                    last_clock_update = now
    except WebSocketDisconnect:
        return
    except TimeoutError:
        await websocket.close(code=4408, reason="Authentication timed out.")
    except HTTPException as exc:
        await websocket.close(code=4401 if exc.status_code == 401 else 4403)
    except RedisError:
        logger.warning("Redis unavailable during live game socket operation.")
        await websocket.close(code=1013, reason="Live game service is unavailable.")
    except Exception:
        logger.exception("Live game socket failed.")
        await websocket.close(code=1011, reason="Live game service error.")
