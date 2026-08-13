import logging
import os
import threading
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.api.v1.router import api_router

logger = logging.getLogger(__name__)

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "uploads")
GENERATED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "generated")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(GENERATED_DIR, exist_ok=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    description="Muse — Guided Art Conversation & AI Artwork Synthesis API",
    version="1.0.0",
)

# CORS middleware
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        # Vercel gives every preview deployment its own hostname, so listing
        # them individually is impossible. Set BACKEND_CORS_ORIGIN_REGEX to
        # something like https://.*\.vercel\.app to admit them all; it stays
        # empty (and therefore inactive) for local development.
        allow_origin_regex=settings.BACKEND_CORS_ORIGIN_REGEX or None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Serve uploaded and generated files as static assets
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/generated", StaticFiles(directory=GENERATED_DIR), name="generated")

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.on_event("startup")
def startup_check():
    ollama_url = getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        with httpx.Client(timeout=3.0) as client:
            res = client.get(f"{ollama_url.rstrip('/')}/api/tags")
            if res.status_code == 200:
                logger.info(f"Startup check: Local Ollama instance connected at {ollama_url}.")
            else:
                logger.warning(f"Startup check: Ollama endpoint {ollama_url} returned status {res.status_code}.")
    except Exception as e:
        logger.warning(
            "\n"
            "======================================================================\n"
            " [STARTUP WARNING] UNABLE TO CONNECT TO OLLAMA AT %s\n"
            " Error: %s\n"
            " LLM conversation & critique generation will fall back to local heuristics\n"
            " until Ollama is started!\n"
            "======================================================================",
            ollama_url,
            e,
        )

    # Image generation needs no paid key: the default provider (Pollinations)
    # is free and keyless, so we only report which chain will be used.
    from app.services.image_provider import image_service

    chain = " -> ".join(name for name, _ in image_service._provider_chain())
    logger.info(f"Startup check: image generation provider chain: {chain}")

    _warm_up_chat_model(ollama_url)


def _warm_up_chat_model(ollama_url: str) -> None:
    """
    Ask Ollama to load the chat model in the background at boot.

    Otherwise the first person to open a conversation pays the model load on top
    of their own inference, and on a CPU-only host that is several seconds of
    unexplained wait tacked onto an already slow first question. Runs on a
    daemon thread so startup is not delayed, and failure is harmless — the model
    would simply load on first use, exactly as it did before.
    """
    model = getattr(settings, "OLLAMA_MODEL", "")
    if not model:
        return

    def warm() -> None:
        try:
            with httpx.Client(timeout=120.0) as client:
                client.post(
                    f"{ollama_url.rstrip('/')}/api/chat",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "hi"}],
                        "stream": False,
                        "keep_alive": "30m",
                        "options": {"num_predict": 1},
                    },
                )
            logger.info(f"Startup check: chat model '{model}' warmed and resident.")
        except Exception as exc:
            logger.info(f"Startup check: could not pre-warm '{model}' ({exc}); it will load on first use.")

    threading.Thread(target=warm, name="muse-model-warmup", daemon=True).start()


@app.get("/")
def root():
    return {
        "message": "Welcome to Muse API",
        "docs": "/docs",
        "health": f"{settings.API_V1_STR}/health",
    }
