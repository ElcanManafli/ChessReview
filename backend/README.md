# ChessReview FastAPI backend

## Setup

- Python 3.11 or newer
- Stockfish 16+ executable on `PATH` or configured by an absolute `STOCKFISH_PATH`
- Redis 5+ (optional; required only for live games)
- A Supabase project for authenticated live-game access

Copy `backend/.env.example` to `backend/.env`, then set local deployment values. The
backend loads that ignored file at startup. Never commit `.env`, a Supabase JWT
signing secret, a service-role key, or a Redis password. Current Supabase projects
should verify access tokens against the project's Auth JWKS endpoint; set
`SUPABASE_URL` to the project root URL. Tokens must include valid `sub`, `iss`,
`aud`, `exp`, and `role` claims; the accepted audience and role are both
`authenticated`. `SUPABASE_JWT_SECRET` is only for legacy HS256 projects; leave it
empty when using JWKS, and rotate it if it has been disclosed.

`STOCKFISH_PATH` is either a bare executable name resolved on `PATH` or an absolute
path to an executable regular file. The service never searches or executes a binary
from its current working directory by default. Configure `REDIS_URL` for the Redis
instance used by all backend workers. The default is local Redis at
`redis://localhost:6379/0`. Redis is optional: analysis continues if Redis is
missing or unreachable; live-game HTTP and WebSocket requests return a service
unavailable response instead.

On Windows:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r backend\requirements.txt
$env:STOCKFISH_PATH = "C:\tools\stockfish\stockfish-windows-x86-64-avx2.exe"
py -m uvicorn backend.main:app --port 8000
```

On macOS/Linux:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
STOCKFISH_PATH=/usr/bin/stockfish python -m uvicorn backend.main:app --port 8000
```

The analysis API remains available if Redis is down, but authenticated live-game
routes return HTTP 503 until Redis is available. If Stockfish is unavailable, health
checks report 503; the engine is restarted after protocol failures and health-check
failures.

## Analysis API

- `GET /api/health` checks Stockfish availability.
- `POST /api/analyze?depth=14&compact=true` accepts JSON:
  `{"pgn":"[White \"Player\"]..."}`. A single FEN string is also accepted.
- `POST /api/analyze/file?depth=14&compact=true` accepts a UTF-8 `.pgn`, `.fen`, or
  `.txt` multipart upload in field `file`.

Depth is bounded from 10 to 20. Input is limited to 1 MB, request bodies to 1.1 MB,
and games to 500 plies. Recursive PGN variations and non-clock comments are removed
before the parser builds its game tree. `%clk` annotations are retained. The server
detects checkmate, stalemate, insufficient material, the 50- and 75-move rules, and
threefold/fivefold repetition before asking Stockfish to analyze a position. Terminal
positions are scored without invoking the engine.

Each position analysis has a 0.75 second Stockfish time cap and each complete game
has a 90 second wall-clock deadline. Each API process runs one serialized engine;
concurrent work receives HTTP 429 instead of queueing indefinitely. Response errors
do not include engine exception text or filesystem paths and include a request ID.

The response contains per-move FEN before/after, best move, centipawn loss,
win-probability delta, clock annotation, evaluation, score, and move classification.
The Brilliant sacrifice threshold is 200 centipawns. Explanations and suggestions are
deterministic templates based on engine output.

## Authenticated live games

Live routes require a Supabase Auth access token with the `authenticated` audience.
The API verifies JWT signature, expiry, issuer, and subject using the project's JWKS
keys (or a configured legacy HS256 secret). The browser WebSocket authenticates with
its first JSON message; tokens are not placed in URLs.

- `POST /api/games` creates a waiting game. Optional JSON:
  `{"initial_time_seconds":300,"increment_seconds":0}`. Initial time is 60-3600
  seconds; increment is 0-60 seconds. The creator is White.
- `POST /api/games/join` accepts `{"game_id":"<32 hex characters>"}`. The joining
  authenticated user is Black.
- `POST /api/move/validate` accepts `{"game_id":"...","uci":"e2e4"}` and validates
  against Redis-backed server state without changing it.
- `POST /api/games/{game_id}/claim-draw` permits a current player to claim a
  threefold repetition or 50-move draw.
- `GET /ws/game?game_id=<id>` sends the initial state after the client sends
  `{"type":"auth","token":"<Supabase access token>"}`. Subsequent messages are
  `{"type":"move","uci":"e2e4"}` or `{"type":"claim_draw"}`.

The server alone owns FEN, legal move validation, side to move, and clock updates.
Clocks continue during disconnects. Reconnecting players receive the authoritative
position and remaining times from Redis. State expires after seven days; games are
drawn at a 500-ply service limit. Automatic checkmate, stalemate, insufficient
material, 75-move, and fivefold-repetition outcomes are enforced.

## Deployment controls

Set `CORS_ORIGINS` to exact frontend origins; wildcard origins are rejected. HTTP
analysis is unauthenticated by design, so add gateway authentication if analysis
should be private. The built-in IP limiter is per process; production deployments
with multiple workers should also enforce a distributed limit at the trusted ingress.
Terminate TLS at a trusted reverse proxy, enable trusted-proxy handling deliberately,
and restrict Redis and Stockfish process resources at the host/container level.
