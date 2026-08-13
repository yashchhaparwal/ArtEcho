# Deploying Muse

The frontend is a static Vite SPA and deploys to Vercel cleanly. The backend
does **not** — read "Why the backend can't go on Vercel" before planning around
it.

Both halves are required. Every screen in the app (library, auth, chat,
generation, gallery) is driven by the API, so a frontend deployed on its own
renders an empty shell.

---

## Why the backend can't go on Vercel

**Ollama.** The conversation, critique, and vision models all run against a
local Ollama server. Vercel Functions have no persistent process to keep a model
resident, and `qwen2.5:3b` alone is 1.9 GB against a 2 GB Hobby memory ceiling —
so it would exceed the limit *and* reload the model on every invocation.

Three further things break in a serverless runtime, all fixable if you ever move
off Ollama:

| What | Where | Why it breaks |
|---|---|---|
| Generated/uploaded images | `app/main.py` mounts `/uploads` and `/generated` from local disk | Serverless filesystems are ephemeral — images vanish between invocations |
| In-flight job state | `app/services/jobs.py` keeps jobs in memory | A poll for `/jobs/{id}` can land on a different instance and 404 |
| Postgres | `DATABASE_URL` | Needs a hosted database (Neon via the Vercel Marketplace is the easy path) |

Function *duration* is not a problem: Hobby allows 300s, which comfortably
covers the ~45s image generation.

So the backend needs a host that gives you a real process, a disk, and enough
RAM for Ollama — a small VM or container host (Render, Railway, Fly.io, or any
VPS). Budget ~4 GB RAM for `qwen2.5:3b` plus `moondream`; free tiers generally
cannot hold them.

---

## 1. Frontend on Vercel

The API origin is no longer hardcoded. It comes from `VITE_API_ORIGIN`
(see `frontend/src/config.ts`), which Vite inlines **at build time** — so it must
be set in the Vercel project before the build runs, not afterwards.

1. **New Project** → import `yashchhaparwal/ArtEcho` from GitHub.
2. Set **Root Directory** to `frontend`. Vercel then picks up
   `frontend/vercel.json`, which sets the Vite preset and the SPA rewrite that
   stops a hard refresh on `/library` from 404ing.
3. Add an environment variable:

   | Name | Value |
   |---|---|
   | `VITE_API_ORIGIN` | `https://<your-backend-host>` (no trailing slash) |

4. Deploy. Changing `VITE_API_ORIGIN` later requires a **redeploy**, because the
   value is baked into the bundle.

From the CLI instead:

```bash
cd frontend
vercel link
vercel env add VITE_API_ORIGIN production   # paste the backend URL
vercel --prod
```

## 2. Backend, wherever it lives

Point it at a hosted Postgres and tell it which origins may call it:

```bash
DATABASE_URL=postgresql://user:pass@host:5432/muse_db
SECRET_KEY=<a real random 32+ byte secret, not the checked-in default>
OLLAMA_BASE_URL=http://localhost:11434     # or wherever Ollama runs
OLLAMA_MODEL=qwen2.5:3b
BACKEND_CORS_ORIGINS=["https://your-app.vercel.app"]
BACKEND_CORS_ORIGIN_REGEX=https://.*\.vercel\.app
```

`BACKEND_CORS_ORIGIN_REGEX` exists because Vercel gives every preview deployment
its own hostname — listing them individually is impossible. Leave it empty for
local development.

Then, once per environment:

```bash
alembic upgrade head
python seed.py                # the 88-artwork public-domain library
python backfill_vision.py     # optional; pre-computes vision analysis
```

Serve it with `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

> `SECRET_KEY` ships with a placeholder default in `app/core/config.py`. It signs
> your JWTs — anyone who knows it can mint a token for any account. Set a real
> one before the app is publicly reachable.

## 3. Quick demo without hosting a backend

To share a link without paying for a box, keep the backend on your machine and
expose it through a tunnel:

```bash
cloudflared tunnel --url http://localhost:8000
```

Set `VITE_API_ORIGIN` to the tunnel's `https://…trycloudflare.com` URL and
redeploy the frontend. Free and immediate — but it only works while your machine
is awake with both Ollama and the backend running, so treat it as a demo rather
than a deployment.
