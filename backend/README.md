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

On macOS/Linux, activate with `source .venv/bin/activate` and use `python -m uvicorn backend.main:app --reload --port 8000`. The API starts Stockfish once and reuses its UCI process; a missing or invalid binary prevents startup. Set `STOCKFISH_DEPTH` (10-20, default 15), `STOCKFISH_THREADS`, `STOCKFISH_HASH_MB`, and comma-separated `CORS_ORIGINS` to configure deployment. `CORS_ORIGINS` defaults to localhost development origins; set it to the exact frontend origins in production.

## Endpoints

- `GET /api/health` checks that the API is serving.
- `POST /api/analyze?depth=14` accepts JSON: `{"pgn":"[White \\\"Player\\\"]..."}`. The `pgn` field also accepts a single FEN string for a static evaluation.
- `POST /api/analyze/file?depth=14` accepts multipart form data with a `file` field containing a UTF-8 PGN.
- `GET /docs` provides the interactive OpenAPI reference.

Depth is optional, defaults to 15, and is bounded from 10 to 20. The service limits PGN input to 1 MB, HTTP request bodies to 1.1 MB, and games to 500 plies. Each API process runs one persistent UCI engine; concurrent analysis submissions receive HTTP 429 rather than accumulating in an unbounded engine wait queue. MultiPV is limited to the two leading moves needed for classification.

The default response includes full per-move details, including FEN before and after, evaluations, score objects, centipawn loss, best-move alternatives, and deterministic, rule-based `explanation` and `suggestion` text for each move. These explanations use fixed templates and engine results; they do not call an AI service or consume language-model tokens. Add `?compact=true` to either analysis endpoint to return only fields needed for move playback and move feedback; the frontend uses this mode. Common opening lines are recognized with Polyglot position hashes through full move 10; matching moves are classified as `book` with zero loss and are not sent to Stockfish for evaluation.

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