# RealReel

- `frontend/` — Next.js UI (Vercel); proxies processing to the backend
- `backend/` — Python FastAPI processor (Railway): yt-dlp, ffmpeg, OpenAI, OCR, Gemini, Supabase
- `storage/` — Supabase storage pipeline

## Quick start (local)

```bash
# Terminal 1 — processor
cd backend && pip install -r requirements.txt && uvicorn main:app --reload --port 8000

# Terminal 2 — UI
cd frontend && npm install && npm run dev
```

- Secrets: `backend/.env.local`
- Frontend: `frontend/.env.local` with `PROCESSOR_URL=http://localhost:8000`

**Windows shortcuts:** `scripts/start-backend.ps1` then `scripts/start-frontend.ps1`
