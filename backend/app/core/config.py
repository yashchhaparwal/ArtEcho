from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Muse API"
    API_V1_STR: str = "/api/v1"

    # LLM / AI providers — the defaults below are all free.
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b"
    # Vision model used to actually "look at" reference and generated artworks.
    # Any Ollama multimodal model works (llava, moondream, qwen2.5vl, llama3.2-vision).
    OLLAMA_VISION_MODEL: str = "moondream"
    VISION_ENABLED: bool = True

    # Image generation. "auto" runs the free-first waterfall in
    # app/services/image_provider.py; pin a name to use exactly one provider.
    # auto | pollinations | local_sd | huggingface | openai
    IMAGE_PROVIDER: str = "auto"
    IMAGE_WIDTH: int = 1024
    IMAGE_HEIGHT: int = 1024
    POLLINATIONS_MODEL: str = "flux"  # free, keyless
    SD_WEBUI_URL: str = ""  # e.g. http://localhost:7860 for a local AUTOMATIC1111
    SD_STEPS: int = 28
    HUGGINGFACE_API_TOKEN: str = ""  # optional, free tier
    HUGGINGFACE_IMAGE_MODEL: str = "black-forest-labs/FLUX.1-schnell"
    OPENAI_API_KEY: str = ""  # optional and PAID — never required

    # JWT Settings
    SECRET_KEY: str = "muse_super_secret_jwt_key_change_in_production_32bytes"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 4320

    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/muse_db"

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )


settings = Settings()
