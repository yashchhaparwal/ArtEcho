"""
Lightweight request-stage profiler.

Used to attribute latency across the chat pipeline (auth, DB, prompt build,
Ollama call, response parsing, DB writes). Adds no behavioural change — it only
measures and logs.

Enable/disable with the PROFILE_CHAT env var (default: on in development).
"""
import logging
import os
import time
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PROFILING_ENABLED = os.getenv("PROFILE_CHAT", "1").lower() not in {"0", "false", "no"}


class StageTimer:
    """Accumulates named stage durations for a single request."""

    def __init__(self, label: str):
        self.label = label
        self._start = time.perf_counter()
        self._stages: List[Tuple[str, float]] = []
        self._notes: Dict[str, object] = {}

    @contextmanager
    def stage(self, name: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self._stages.append((name, time.perf_counter() - t0))

    def record(self, name: str, seconds: float) -> None:
        """Record a stage measured elsewhere (e.g. inside the LLM provider)."""
        self._stages.append((name, seconds))

    def note(self, key: str, value: object) -> None:
        """Attach a non-timing diagnostic (token counts, prompt size, ...)."""
        self._notes[key] = value

    @property
    def total(self) -> float:
        return time.perf_counter() - self._start

    def report(self) -> str:
        total = self.total
        width = max((len(n) for n, _ in self._stages), default=0)
        lines = [f"[PROFILE] {self.label}", f"  TOTAL: {total:.2f}s"]
        for name, secs in self._stages:
            pct = (secs / total * 100) if total > 0 else 0.0
            lines.append(f"  {name.ljust(width)}: {secs:8.2f}s  ({pct:5.1f}%)")
        # Sub-stages are prefixed with "|-" and are nested inside a parent
        # stage, so they must not be counted again in the residual.
        accounted = sum(s for n, s in self._stages if "|-" not in n)
        lines.append(f"  {'unaccounted'.ljust(width)}: {total - accounted:8.2f}s")
        if self._notes:
            lines.append("  --- diagnostics ---")
            for key, value in self._notes.items():
                lines.append(f"  {key}: {value}")
        return "\n".join(lines)

    def emit(self) -> None:
        if PROFILING_ENABLED:
            logger.warning(self.report())


@contextmanager
def profile_request(label: str):
    timer = StageTimer(label)
    try:
        yield timer
    finally:
        timer.emit()


# Set by the LLM provider on each call so the endpoint can fold provider-side
# timings (HTTP, Ollama's own prompt-eval/generation split) into its report.
_last_llm_metrics: Optional[Dict[str, object]] = None


def set_llm_metrics(metrics: Dict[str, object]) -> None:
    global _last_llm_metrics
    _last_llm_metrics = metrics


def pop_llm_metrics() -> Optional[Dict[str, object]]:
    global _last_llm_metrics
    metrics, _last_llm_metrics = _last_llm_metrics, None
    return metrics
