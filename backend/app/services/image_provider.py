"""
image_provider.py
=================
Provider-agnostic image generation service.

Every provider in the default waterfall is FREE. No paid API key is required to
run this application end to end.

Waterfall (when IMAGE_PROVIDER="auto"):
  1. Local Stable Diffusion  — only if SD_WEBUI_URL is configured (free, offline,
                               needs an AUTOMATIC1111/Forge instance)
  2. Pollinations.ai         — free, keyless, no signup. The default path.
  3. Hugging Face Inference  — only if HUGGINGFACE_API_TOKEN is set (free tier)
  4. OpenAI DALL-E 3         — only if OPENAI_API_KEY is set (PAID; opt-in only)
  5. Generated SVG placeholder — always succeeds, so the flow never dead-ends

Set IMAGE_PROVIDER to a specific name to pin one provider and skip the waterfall.

Every successful generation is downloaded and stored under backend/generated/,
so the artwork survives even if the upstream service purges its cache.
"""

import base64
import html
import logging
import random
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

GENERATED_DIR = Path(__file__).parent.parent.parent / "generated"
GENERATED_DIR.mkdir(exist_ok=True)

# Pollinations occasionally returns a transient 5xx under load; a couple of
# quick retries is far cheaper than failing the user's generation.
#
# The numbers matter more than they look. A cold generation on the free tier
# measures ~45s, essentially all of it queue time — model and resolution barely
# move it. The old settings (3 retries x 180s) meant a bad run could hang for
# *nine minutes* before falling back to the placeholder, which read to the user
# as the app being frozen. These bound the worst case to a little over two
# minutes while still leaving generous headroom over the 45s norm.
HTTP_RETRIES = 2
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=90.0, write=15.0, pool=10.0)

# Hard ceiling across all attempts for a single provider, so retries can never
# stack into an unbounded wait.
PROVIDER_DEADLINE_SECONDS = 150.0

# Backoff between retries. Pollinations rate-limits anonymous callers, so an
# immediate retry tends to draw the same rejection.
RETRY_BACKOFF_SECONDS = 2.0

# One pooled client for the process. Building a fresh client per attempt threw
# away the connection and paid for a new TLS handshake every time.
_http_client: Optional[httpx.Client] = None
_http_client_lock = threading.Lock()


def _client() -> httpx.Client:
    global _http_client
    if _http_client is None:
        with _http_client_lock:
            if _http_client is None:
                _http_client = httpx.Client(
                    timeout=HTTP_TIMEOUT,
                    follow_redirects=True,
                    limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                    headers={"User-Agent": "Muse/1.0 (+local art synthesis app)"},
                )
    return _http_client


class ImageGenerationError(Exception):
    """Raised by a provider when it cannot produce an image."""


class ImageProvider:
    def __init__(self):
        self.provider = (settings.IMAGE_PROVIDER or "auto").strip().lower()
        self.width = settings.IMAGE_WIDTH
        self.height = settings.IMAGE_HEIGHT
        self.pollinations_model = (settings.POLLINATIONS_MODEL or "flux").strip()
        self.sd_webui_url = (settings.SD_WEBUI_URL or "").strip().rstrip("/")
        self.hf_token = (settings.HUGGINGFACE_API_TOKEN or "").strip()
        self.hf_model = (settings.HUGGINGFACE_IMAGE_MODEL or "").strip()
        self.openai_api_key = (settings.OPENAI_API_KEY or "").strip()
        if self.openai_api_key.startswith("sk-placeholder"):
            self.openai_api_key = ""

    # ── public API ───────────────────────────────────────────────────────────

    def generate(
        self,
        prompt: str,
        context_summary: Optional[Dict[str, Any]] = None,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Generate an image from the given prompt.

        `seed` varies the output for the same prompt — this is what makes the
        "Regenerate" button produce a genuinely different piece rather than a
        byte-identical cached one.

        Returns
        -------
        dict with keys:
          - image_url: str   (relative /generated/<filename> path)
          - model_provider: str
          - prompt_used: str
          - resolution: str
          - error: str | None
        """
        if seed is None:
            seed = random.randint(1, 2_000_000_000)

        errors: List[str] = []
        for name, fn in self._provider_chain():
            try:
                result = fn(prompt, seed)
                logger.info(f"Image generated via '{name}' (seed={seed})")
                return result
            except Exception as exc:
                message = str(exc)
                errors.append(f"{name}: {message}")
                # A content-policy rejection is the user's problem to fix, not a
                # transport failure — surface it instead of silently falling
                # through to a provider that would happily render it.
                if self._is_content_policy_error(message):
                    return {
                        "image_url": None,
                        "model_provider": name,
                        "prompt_used": prompt,
                        "resolution": f"{self.width}x{self.height}",
                        "error": (
                            "Your image prompt was flagged by the content safety system. "
                            "Try adjusting your artistic preferences or mood description and regenerate."
                        ),
                    }
                logger.warning(f"Image provider '{name}' failed: {message}")

        logger.error(f"All image providers failed: {'; '.join(errors)}")
        return self._svg_placeholder(prompt, context_summary, errors)

    # ── provider selection ───────────────────────────────────────────────────

    def _provider_chain(self) -> List[tuple[str, Callable[[str, int], Dict[str, Any]]]]:
        available: Dict[str, Callable[[str, int], Dict[str, Any]]] = {
            "pollinations": self._call_pollinations,
        }
        if self.sd_webui_url:
            available["local_sd"] = self._call_local_sd
        if self.hf_token:
            available["huggingface"] = self._call_huggingface
        if self.openai_api_key:
            available["openai"] = self._call_dalle3

        if self.provider != "auto":
            if self.provider in available:
                return [(self.provider, available[self.provider])]
            logger.warning(
                f"IMAGE_PROVIDER='{self.provider}' is not configured "
                f"(available: {', '.join(available)}). Falling back to auto."
            )

        # Free-first ordering. A configured local instance wins because it costs
        # nothing per call and keeps data on the user's machine.
        order = ["local_sd", "pollinations", "huggingface", "openai"]
        return [(name, available[name]) for name in order if name in available]

    @staticmethod
    def _is_content_policy_error(message: str) -> bool:
        lowered = message.lower()
        return "content_policy" in lowered or "safety system" in lowered

    # ── providers ────────────────────────────────────────────────────────────

    def _call_pollinations(self, prompt: str, seed: int) -> Dict[str, Any]:
        """Free, keyless text-to-image. The default path for this project."""
        url = (
            f"https://image.pollinations.ai/prompt/{quote(prompt, safe='')}"
            f"?width={self.width}&height={self.height}&seed={seed}"
            f"&model={self.pollinations_model}&nologo=true&private=true"
        )
        content = self._fetch_bytes(url)
        return self._store(
            content,
            provider=f"pollinations/{self.pollinations_model}",
            prompt=prompt,
            seed=seed,
            ext=".jpg",
        )

    def _call_local_sd(self, prompt: str, seed: int) -> Dict[str, Any]:
        """AUTOMATIC1111 / Forge compatible txt2img endpoint."""
        payload = {
            "prompt": prompt,
            "negative_prompt": "text, watermark, signature, blurry, lowres, deformed",
            "width": self.width,
            "height": self.height,
            "steps": settings.SD_STEPS,
            "cfg_scale": 7,
            "seed": seed,
            "sampler_name": "DPM++ 2M Karras",
        }
        res = _client().post(f"{self.sd_webui_url}/sdapi/v1/txt2img", json=payload)
        res.raise_for_status()
        images = res.json().get("images") or []
        if not images:
            raise ImageGenerationError("local SD returned no images")
        return self._store(
            base64.b64decode(images[0]),
            provider="local-stable-diffusion",
            prompt=prompt,
            seed=seed,
            ext=".png",
        )

    def _call_huggingface(self, prompt: str, seed: int) -> Dict[str, Any]:
        """Hugging Face Inference API — free tier, rate limited."""
        url = f"https://api-inference.huggingface.co/models/{self.hf_model}"
        headers = {"Authorization": f"Bearer {self.hf_token}"}
        payload = {
            "inputs": prompt,
            "parameters": {"width": self.width, "height": self.height, "seed": seed},
        }
        res = _client().post(url, headers=headers, json=payload)
        if not res.is_success:
            raise ImageGenerationError(f"HTTP {res.status_code}: {res.text[:200]}")
        content = res.content
        if not content.startswith(b"\xff\xd8") and not content.startswith(b"\x89PNG"):
            raise ImageGenerationError(f"unexpected response: {content[:200]!r}")
        return self._store(
            content,
            provider=f"huggingface/{self.hf_model}",
            prompt=prompt,
            seed=seed,
            ext=".jpg",
        )

    def _call_dalle3(self, prompt: str, seed: int) -> Dict[str, Any]:
        """PAID. Only reachable when the operator opts in with an API key."""
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "dall-e-3",
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
            "quality": "standard",
            "response_format": "url",
        }
        res = _client().post(
            "https://api.openai.com/v1/images/generations", headers=headers, json=payload
        )
        if not res.is_success:
            error_data = res.json().get("error", {})
            raise ImageGenerationError(
                f"{error_data.get('code', 'unknown')}: {error_data.get('message', res.text)}"
            )
        image_url = res.json()["data"][0]["url"]

        return self._store(
            self._fetch_bytes(image_url),
            provider="openai/dall-e-3",
            prompt=prompt,
            seed=seed,
            ext=".png",
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _fetch_bytes(url: str) -> bytes:
        last_error: Optional[Exception] = None
        deadline = time.monotonic() + PROVIDER_DEADLINE_SECONDS

        for attempt in range(HTTP_RETRIES):
            if time.monotonic() >= deadline:
                logger.warning("Image fetch deadline exceeded; giving up early")
                break
            try:
                res = _client().get(url)
                res.raise_for_status()
                if not res.content:
                    raise ImageGenerationError("empty response body")
                return res.content
            except Exception as exc:
                last_error = exc
                remaining = deadline - time.monotonic()
                if attempt < HTTP_RETRIES - 1 and remaining > RETRY_BACKOFF_SECONDS:
                    logger.info(f"Image fetch attempt {attempt + 1} failed ({exc}); retrying")
                    time.sleep(RETRY_BACKOFF_SECONDS)

        raise ImageGenerationError(str(last_error) if last_error else "image fetch timed out")

    def _store(
        self, content: bytes, provider: str, prompt: str, seed: int, ext: str
    ) -> Dict[str, Any]:
        filename = f"{uuid.uuid4()}{ext}"
        (GENERATED_DIR / filename).write_bytes(content)
        return {
            "image_url": f"/generated/{filename}",
            "model_provider": provider,
            "prompt_used": prompt,
            "resolution": f"{self.width}x{self.height}",
            "seed": seed,
            "error": None,
        }

    def _svg_placeholder(
        self,
        prompt: str,
        context_summary: Optional[Dict[str, Any]],
        errors: List[str],
    ) -> Dict[str, Any]:
        """
        Last resort when every provider is unreachable (e.g. the machine is
        offline). Renders a mood-tinted gradient card rather than a stock
        painting — passing off someone else's artwork as the user's generated
        piece would be dishonest.
        """
        palette = self._palette_for(context_summary)
        message = html.escape((prompt or "")[:110])
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" viewBox="0 0 1024 1024">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{palette[0]}"/>
      <stop offset="55%" stop-color="{palette[1]}"/>
      <stop offset="100%" stop-color="{palette[2]}"/>
    </linearGradient>
  </defs>
  <rect width="1024" height="1024" fill="url(#g)"/>
  <circle cx="512" cy="430" r="200" fill="#ffffff" fill-opacity="0.07"/>
  <text x="512" y="880" text-anchor="middle" font-family="Georgia, serif" font-size="34" fill="#ffffff" fill-opacity="0.85">Artwork unavailable</text>
  <text x="512" y="928" text-anchor="middle" font-family="Georgia, serif" font-size="20" fill="#ffffff" fill-opacity="0.6">No image service could be reached — try regenerating</text>
  <text x="512" y="968" text-anchor="middle" font-family="Georgia, serif" font-size="15" fill="#ffffff" fill-opacity="0.35">{message}</text>
</svg>"""
        filename = f"{uuid.uuid4()}.svg"
        (GENERATED_DIR / filename).write_text(svg, encoding="utf-8")
        return {
            "image_url": f"/generated/{filename}",
            "model_provider": "placeholder",
            "prompt_used": prompt,
            "resolution": f"{self.width}x{self.height}",
            "error": None,
            "warning": (
                "No image generation service could be reached, so a placeholder was "
                "saved instead. Check your internet connection and regenerate. "
                f"({'; '.join(errors)[:300]})"
            ),
        }

    @staticmethod
    def _palette_for(context_summary: Optional[Dict[str, Any]]) -> tuple[str, str, str]:
        notes = ((context_summary or {}).get("color_palette_notes") or "").lower()
        palettes = {
            "blue": ("#0b1d3a", "#1d4e89", "#4a90d9"),
            "gold": ("#3b2b0a", "#8a6d1f", "#d4af37"),
            "red": ("#3a0b0b", "#8a1f1f", "#d95f5f"),
            "green": ("#0b2a1d", "#1f6b4a", "#5fd9a0"),
            "orange": ("#3a1c0b", "#a35a1f", "#f0a35e"),
            "purple": ("#26093a", "#5d1f8a", "#a86fd9"),
        }
        for key, palette in palettes.items():
            if key in notes:
                return palette
        return ("#1a1230", "#3b2a5e", "#6f5b9e")


image_service = ImageProvider()
