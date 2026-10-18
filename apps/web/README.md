# Pulse Decision OS (web)

Next.js App Router UI: **Analyse · Holdings · Sync**.

## Run

```bash
# terminal 1 — API (repo root, Python 3.9 with deps)
/Applications/Xcode.app/Contents/Developer/usr/bin/python3 -m uvicorn backend.api.server:app --reload --host 127.0.0.1 --port 8000

# terminal 2 — this app
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) (rewrites `/api/*` → `:8000`).
