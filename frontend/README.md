# RealReel Frontend

Next.js UI for previewing and processing YouTube URLs.

Video processing runs on the **Python backend** (`../backend`). This app proxies requests so you can use one origin in local dev.

## Getting Started

**1. Backend** (terminal 1):

```bash
cd ../backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
# copy env: SUPABASE_*, OPENAI_API_KEY, GEMINI_API_KEY, etc. (see backend/README.md)
uvicorn main:app --reload --port 8000
```

**2. Frontend** (terminal 2):

```bash
npm install
```

`frontend/.env.local` should only contain:

```env
PROCESSOR_URL=http://localhost:8000
```

(API keys live in `backend/.env.local`.)

```bash
npm run dev
```

Open http://localhost:3000

Shortcut from repo root: `.\scripts\start-frontend.ps1` (with the backend already running).

## API proxy

`POST /api/process-youtube` forwards the request body to `${PROCESSOR_URL}/process-youtube` and streams NDJSON progress back to the browser.

Processing logic is not implemented in this folder anymore.
