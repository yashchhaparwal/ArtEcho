# Muse

A chat-based app where users pick or upload iconic public-domain artworks, have a guided
conversation about what draws them to them, and get an AI-generated artwork inspired by that
conversation — plus a critique of both the original and the co-created piece.

**Everything runs on free software. No paid API key is required anywhere in the stack.**

## Project Structure

```
ArtEcho/
├── backend/          # FastAPI (Python) backend
│   ├── app/data/artworks.json   # the 88-work public-domain library
│   ├── seed.py                  # loads the library into Postgres
│   └── backfill_vision.py       # pre-computes vision analysis for the library
└── frontend/         # React + Vite + TypeScript frontend
```

## How It Works

1. **Pick or upload references.** Browse 88 public-domain masterpieces, or upload your own
   images. Several references can be combined into one blended piece.
2. **Muse looks at them.** A local vision model reads each image — subject, palette,
   composition, technique, mood — so the assistant can ask pointed questions about what is
   actually in the picture rather than generic ones. This matters most for uploads, which have
   no title or artist to work from.
3. **Have a conversation.** The assistant alternates between visual preferences and personal
   context. **You decide how long it runs** — there is no turn limit, and generating is always
   available once you've given it something to work with.
4. **Generate.** The conversation is synthesised into an image prompt and rendered.
5. **Read the critique.** Both the reference and your generated piece are critiqued across
   composition, colour theory, symbolism, emotional impact, strengths and weaknesses, plus a
   comparison. The critique of your piece is grounded in the vision model's reading of the
   image that was actually produced, not just the prompt that requested it.

## AI Providers (all free)

| Purpose | Provider | Cost | Notes |
|---|---|---|---|
| Conversation & critique | **Ollama** (`qwen2.5:7b`) | Free, local | Runs offline on your machine |
| Understanding artworks | **Ollama vision** (`moondream`) | Free, local | Any multimodal Ollama model works |
| Image generation | **Pollinations.ai** (`flux`) | Free, **no API key, no signup** | Default; ~5–15s per image |

Optional alternatives, all off by default and configured in `.env`:

- `SD_WEBUI_URL` — a local AUTOMATIC1111/Forge instance (free, fully offline, needs a GPU)
- `HUGGINGFACE_API_TOKEN` — Hugging Face Inference free tier
- `OPENAI_API_KEY` — DALL·E 3. **Paid, and never required.** Only used if you set a key.

If every provider is unreachable, a clearly-labelled placeholder is saved rather than passing
off an existing painting as generated work.

## Copyright

The library is **public domain only**, per the project brief. Every entry is by an artist who
died before 1955, with the work created before 1930, and image URLs resolve to Wikimedia
Commons.

Three works seeded by an earlier version were **not** public domain and have been removed:
Dalí's *The Persistence of Memory* (Dalí d. 1989), Hopper's *Nighthawks* (US copyright to 2038)
and Kahlo's *Self-Portrait with Thorn Necklace* (US copyright to 2036). `seed.py` deletes them
from any existing database on every run.

User uploads are stored with `is_public_domain = false` and are only ever visible to the
uploader.

## How to Run Locally

### Prerequisites
- Python 3.13+
- Node.js 18+
- PostgreSQL 14+ running locally
- [Ollama](https://ollama.com) running locally

### 1. Install the models (free, one-time)

```bash
ollama pull qwen2.5:7b     # conversation + critique  (~4.7 GB)
ollama pull moondream      # vision / image understanding  (~1.7 GB)
```

On a CPU-only machine `qwen2.5:3b` is a much faster substitute — set `OLLAMA_MODEL=qwen2.5:3b`.

### 2. Backend

```bash
cd backend

python -m venv venv
.\venv\Scripts\activate      # Windows
# source venv/bin/activate   # Mac/Linux

pip install -r requirements.txt

copy ..\.env.example .env    # then edit DATABASE_URL / SECRET_KEY

# Create the database (in psql):  CREATE DATABASE muse_db;
alembic upgrade head

python seed.py               # load the 88-artwork library
python backfill_vision.py    # pre-analyse the library (optional, see below)

uvicorn app.main:app --reload --port 8000
```

Backend: http://localhost:8000 · API docs: http://localhost:8000/docs

**About `backfill_vision.py`:** vision analysis is cached per artwork, so it only runs once per
image. Running the backfill up front means a user's first conversation about any artwork starts
instantly; skip it and the first session on each artwork queues the analysis in the background
instead. Budget 20–40s per artwork on CPU. It's safe to interrupt and re-run — finished
artworks are skipped.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend: http://localhost:5173

## Performance Notes

The local models are CPU-bound on a machine without a GPU. Measured on this hardware with
`qwen2.5:7b`:

- Conversation turns stream token-by-token, so text starts appearing after a few seconds
  instead of after the whole reply is written.
- Image generation is ~5–15s (it runs on Pollinations' hardware, not yours).
- The critique is the slowest step — it produces a large structured document in one pass.

To speed things up materially: use `qwen2.5:3b`, or run Ollama on a machine with a GPU.

## Configuration

All settings live in `backend/.env` — see `.env.example` for the full annotated list.
