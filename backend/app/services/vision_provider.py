"""
vision_provider.py
==================
Lets the app actually *look* at an artwork instead of only reading its title.

The client's brief requires the system to "understand the artwork and ask
specific, pointed questions about what about the artwork appeals to them".
For a user-uploaded image there is no metadata at all — without vision the
assistant is blind and can only ask generic questions.

Runs on a local Ollama multimodal model (moondream / llava / qwen2.5vl), so it
is free and offline. If no vision model is installed the call degrades to None
and every caller falls back to metadata-only behaviour.

Analysis is expensive on CPU, so results are persisted on the artwork row
(`visual_analysis`) and computed once per image.
"""

import base64
import io
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]

# Vision inference on CPU is slow; a generous ceiling avoids killing a call that
# is merely slow rather than stuck.
VISION_TIMEOUT = 300.0

# Wikimedia rejects generic/absent user agents with a 403, and most library
# artworks are hosted there. Their policy asks for an identifiable app name and
# a contact URL.
HTTP_HEADERS = {
    "User-Agent": "Muse-ArtEcho/1.0 (https://github.com/muse-artecho; educational art project)",
    "Accept": "image/jpeg,image/png,image/webp,image/*;q=0.8",
}

# Vision models downsample to a few hundred pixels internally, and a museum
# master file can be tens of megabytes — enough for Ollama to reject the request
# outright (413) and for CPU inference to crawl. Downscaling first costs nothing
# in analysis quality and makes the call viable on a laptop.
MAX_IMAGE_EDGE = 896
JPEG_QUALITY = 88

ANALYSIS_PROMPT = """Look at this artwork and describe what you actually see.

Respond with ONLY a raw JSON object, no markdown fences:
{
  "subject": "what is depicted — people, objects, setting, action",
  "dominant_colors": "the main colours and how they interact",
  "composition": "how the scene is arranged — focal point, balance, depth, perspective",
  "technique": "visible brushwork, line quality, texture, level of detail",
  "mood": "the emotional atmosphere the image creates",
  "distinctive_details": "two or three specific, concrete details a viewer would notice"
}

Be concrete and specific. Describe only what is visible."""

CRITIQUE_VISION_PROMPT = """Look at this artwork and note what a critic would judge:
its composition, use of colour, any symbolism, technical execution, and emotional
impact. Reply in 4-6 plain sentences describing only what you can actually see."""


class VisionProvider:
    def __init__(self):
        self.base_url = (settings.OLLAMA_BASE_URL or "http://localhost:11434").strip().rstrip("/")
        self.model = (settings.OLLAMA_VISION_MODEL or "moondream").strip()
        self.enabled = bool(settings.VISION_ENABLED)

    # ── public API ───────────────────────────────────────────────────────────

    def analyze_artwork(self, image_ref: str) -> Optional[Dict[str, Any]]:
        """
        Return a structured visual analysis of the image, or None if vision is
        unavailable. `image_ref` may be an http(s) URL or a server-relative
        path such as /uploads/x.jpg or /generated/y.png.
        """
        if not self.enabled:
            return None

        image_b64 = self._load_image_b64(image_ref)
        if not image_b64:
            return None

        try:
            raw = self._call_vision(ANALYSIS_PROMPT, image_b64, want_json=True)
        except Exception as exc:
            logger.warning(f"Vision analysis failed for {image_ref}: {exc}")
            return None

        parsed = self._parse_json(raw)
        if not parsed:
            # Some small vision models ignore the JSON instruction and answer in
            # prose. That prose is still useful context, so keep it.
            text = (raw or "").strip()
            return {"description": text} if text else None
        return parsed

    def describe_for_critique(self, image_ref: str) -> Optional[str]:
        """Free-form visual reading of an image, used to ground the critique."""
        if not self.enabled:
            return None
        image_b64 = self._load_image_b64(image_ref)
        if not image_b64:
            return None
        try:
            return (self._call_vision(CRITIQUE_VISION_PROMPT, image_b64, want_json=False) or "").strip() or None
        except Exception as exc:
            logger.warning(f"Vision critique read failed for {image_ref}: {exc}")
            return None

    def is_available(self) -> bool:
        """True when the configured vision model is actually installed."""
        if not self.enabled:
            return False
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.get(f"{self.base_url}/api/tags")
                res.raise_for_status()
                installed = {m.get("name", "") for m in res.json().get("models", [])}
        except Exception:
            return False
        base = self.model.split(":")[0]
        return any(name == self.model or name.split(":")[0] == base for name in installed)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _call_vision(self, prompt: str, image_b64: str, want_json: bool) -> str:
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
            "keep_alive": "10m",
            "options": {"temperature": 0.2, "num_predict": 400},
        }
        if want_json:
            payload["format"] = "json"

        with httpx.Client(timeout=VISION_TIMEOUT) as client:
            res = client.post(f"{self.base_url}/api/generate", json=payload)
            res.raise_for_status()
            return res.json().get("response", "")

    def _load_image_b64(self, image_ref: str) -> Optional[str]:
        if not image_ref:
            return None
        try:
            if image_ref.startswith(("http://", "https://")):
                content = self._get_remote(image_ref)
            else:
                path = BASE_DIR / image_ref.lstrip("/")
                if not path.exists():
                    logger.warning(f"Vision: local image not found at {path}")
                    return None
                content = path.read_bytes()
        except Exception as exc:
            logger.warning(f"Vision: could not load image {image_ref}: {exc}")
            return None

        content = self._downscale(content)
        return base64.b64encode(content).decode("ascii")

    @staticmethod
    def _downscale(content: bytes) -> bytes:
        """Shrink to MAX_IMAGE_EDGE and re-encode as JPEG. Returns the original
        bytes unchanged if the image cannot be decoded."""
        try:
            with Image.open(io.BytesIO(content)) as img:
                img = img.convert("RGB")
                if max(img.size) > MAX_IMAGE_EDGE:
                    img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.LANCZOS)
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
                return buffer.getvalue()
        except Exception as exc:
            logger.warning(f"Vision: could not downscale image ({exc}); sending as-is")
            return content

    @staticmethod
    def _get_remote(url: str) -> bytes:
        """
        Fetch a remote image, tolerating Wikimedia's thumbnail restrictions.

        Wikimedia now serves only a fixed set of thumbnail widths per file and
        answers 400 for anything else, so on failure we retry against the
        original file (drop the `/thumb/` segment and the `NNNpx-` prefix).
        """
        candidates = [url]
        if "/thumb/" in url:
            base, _, _ = url.rpartition("/")
            candidates.append(base.replace("/thumb/", "/", 1))

        last_error: Optional[Exception] = None
        with httpx.Client(timeout=90.0, follow_redirects=True, headers=HTTP_HEADERS) as client:
            for candidate in candidates:
                try:
                    res = client.get(candidate)
                    res.raise_for_status()
                    if res.content:
                        return res.content
                    last_error = RuntimeError("empty body")
                except Exception as exc:
                    last_error = exc
        raise RuntimeError(str(last_error))

    @staticmethod
    def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
        if not raw:
            return None
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                return None
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        return parsed if isinstance(parsed, dict) and parsed else None


def summarize_analysis(analysis: Optional[Dict[str, Any]]) -> str:
    """Flatten a stored analysis into a short block for an LLM prompt."""
    if not analysis:
        return ""
    if set(analysis) == {"description"}:
        return str(analysis["description"])[:600]
    labels = {
        "subject": "Subject",
        "dominant_colors": "Colours",
        "composition": "Composition",
        "technique": "Technique",
        "mood": "Mood",
        "distinctive_details": "Notable details",
    }
    lines = []
    for key, label in labels.items():
        value = analysis.get(key)
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value)
        if value:
            lines.append(f"{label}: {str(value).strip()}")
    return "\n".join(lines)[:900]


vision_service = VisionProvider()
