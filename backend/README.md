# ChessReview FastAPI backend

## Requirements

- Python 3.11 or newer
- A Stockfish 16+ executable available on `PATH` or specified with `STOCKFISH_PATH`

Download a Stockfish build for your operating system from [stockfishchess.org/download](https://stockfishchess.org/download/), extract it, and point `STOCKFISH_PATH` to the executable. On Windows, for example:

```powershell
$env:STOCKFISH_PATH = "C:\tools\stockfish\stockfish-windows-x86-64-avx2.exe"
```

Install and run from the repository root:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r backend\requirements.txt
py -m uvicorn backend.main:app --reload --port 8000
```

On macOS/Linux, activate with `source .venv/bin/activate` and use `python -m uvicorn backend.main:app --reload --port 8000`. The API starts Stockfish once and reuses its UCI process; a missing or invalid binary prevents startup. Set `STOCKFISH_DEPTH` (8-24), `STOCKFISH_THREADS`, `STOCKFISH_HASH_MB`, and comma-separated `CORS_ORIGINS` to configure deployment. Keep the allowed origins restricted to the actual frontend origins in production.

## Endpoints

- `GET /api/health` checks that the API is serving.
- `POST /api/analyze?depth=14` accepts JSON: `{"pgn":"[White \\\"Player\\\"]..."}`. The `pgn` field also accepts a single FEN string for a static evaluation.
- `POST /api/analyze/file?depth=14` accepts multipart form data with a `file` field containing a UTF-8 PGN.
- `GET /docs` provides the interactive OpenAPI reference.

Depth is optional and bounded from 8 to 24. The service limits input to 1 MB and games to 500 plies. Engine access is serialized because a single UCI process cannot safely serve concurrent searches.

Each move returns FEN before and after, SAN/UCI, white-centric evaluations and score objects (`{"type":"cp","value":34}` or `{"type":"mate","value":3}`), centipawn loss from the mover's perspective, a classification, and the engine's best move. `best_alternative_move` is populated for mistakes and blunders. Common opening lines are recognized with Polyglot position hashes through full move 10; matching moves are classified as `book` with zero loss and are not sent to Stockfish for evaluation.

## Frontend integration

Set `VITE_ANALYSIS_API_URL` in the frontend environment, without a trailing slash, to the API origin (for local development, `http://localhost:8000`). Send PGN text as JSON:

```ts
const response = await fetch(`${import.meta.env.VITE_ANALYSIS_API_URL}/api/analyze`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ pgn }),
});
if (!response.ok) throw new Error((await response.json()).detail ?? "Analysis failed");
const analysis = await response.json();
```

For file imports, put the file in `FormData` under `file` and POST it to `/api/analyze/file`. The existing frontend uses the JSON route, stores the returned analysis in session storage, and renders it without running chess evaluation in the browser.