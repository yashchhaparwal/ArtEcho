"""
jobs.py
=======
A small in-process registry for the two operations slow enough that blocking an
HTTP request on them makes the app feel broken:

  * **image generation** — Pollinations queues anonymous requests, so a cold
    generation measures ~45s and can occasionally run into minutes;
  * **critique** — a vision pass over the generated image followed by a large
    single-shot LLM document, which on a CPU-only Ollama box is the slowest
    step in the whole app.

Holding a request open for that long is what made *everything* feel laggy
rather than just the artwork. A sync FastAPI endpoint occupies a threadpool
worker for its whole duration, and — far worse — the `Depends(get_db)` session
pins a pooled database connection the entire time. With SQLAlchemy's default
pool of five, two or three concurrent generations starve every other request in
the app, including plain page loads.

Jobs here run on a worker thread that does the slow network/model call holding
**no** database connection, then opens its own short-lived session purely to
persist the result.

The registry is deliberately in-memory. The durable record of a generation is
the `GeneratedArtwork` row; a job only carries the transient "is it done yet?"
state. If the server restarts mid-flight the client falls back to re-reading
the session result, which converges on the same end state.
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Finished jobs are kept around briefly so a client that polls a moment late
# still sees the terminal state instead of a confusing 404.
JOB_RETENTION_SECONDS = 15 * 60

# A job that outlives this is treated as dead. It is longer than the worst case
# the image provider allows for itself, so it only ever catches a genuine hang.
JOB_MAX_RUNTIME_SECONDS = 15 * 60

PENDING = "pending"
RUNNING = "running"
DONE = "done"
ERROR = "error"

TERMINAL_STATUSES = (DONE, ERROR)


@dataclass
class Job:
    """One unit of slow work, plus enough state to render a progress UI."""

    id: str
    kind: str  # "generate" | "critique"
    session_id: str
    user_id: str
    status: str = PENDING
    stage: str = "Queued"
    created_at: float = field(default_factory=time.monotonic)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    @property
    def elapsed_seconds(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return round(end - self.created_at, 2)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.id,
            "kind": self.kind,
            "session_id": self.session_id,
            "status": self.status,
            "stage": self.stage,
            "elapsed_seconds": self.elapsed_seconds,
            "result": self.result,
            "error": self.error,
        }


class JobRegistry:
    """Thread-safe job store. One instance per process is all this app needs."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    # ── lookup ───────────────────────────────────────────────────────────────

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def find_active(self, kind: str, session_id: str) -> Optional[Job]:
        """
        The in-flight job of this kind for this session, if there is one.

        Used to make submission idempotent: double-clicking "Generate" should
        attach to the running job rather than queue a second 45-second call.
        """
        with self._lock:
            for job in self._jobs.values():
                if (
                    job.kind == kind
                    and job.session_id == session_id
                    and not job.is_terminal
                    and job.elapsed_seconds < JOB_MAX_RUNTIME_SECONDS
                ):
                    return job
        return None

    # ── submission ───────────────────────────────────────────────────────────

    def submit(
        self,
        kind: str,
        session_id: str,
        user_id: str,
        work: Callable[[Callable[[str], None]], Dict[str, Any]],
        initial_stage: str = "Queued",
    ) -> Job:
        """
        Register a job and run `work` on a daemon thread.

        `work` is handed a `progress(stage)` callback so it can report which
        step it is on; whatever dict it returns becomes the job result.
        """
        self._evict_expired()

        job = Job(
            id=str(uuid.uuid4()),
            kind=kind,
            session_id=session_id,
            user_id=user_id,
            stage=initial_stage,
        )
        with self._lock:
            self._jobs[job.id] = job

        thread = threading.Thread(
            target=self._run,
            args=(job, work),
            name=f"muse-job-{kind}-{job.id[:8]}",
            daemon=True,
        )
        thread.start()
        return job

    def _run(
        self,
        job: Job,
        work: Callable[[Callable[[str], None]], Dict[str, Any]],
    ) -> None:
        def progress(stage: str) -> None:
            with self._lock:
                job.stage = stage
            logger.info(f"[job {job.id[:8]}] {job.kind}: {stage}")

        with self._lock:
            job.status = RUNNING
            job.started_at = time.monotonic()

        try:
            result = work(progress)
            with self._lock:
                job.result = result
                job.status = DONE
                job.stage = "Complete"
                job.finished_at = time.monotonic()
            logger.info(f"[job {job.id[:8]}] {job.kind} finished in {job.elapsed_seconds}s")
        except Exception as exc:  # noqa: BLE001 — the message is surfaced to the user
            with self._lock:
                job.status = ERROR
                job.stage = "Failed"
                job.error = str(exc) or exc.__class__.__name__
                job.finished_at = time.monotonic()
            logger.exception(f"[job {job.id[:8]}] {job.kind} failed: {exc}")

    # ── housekeeping ─────────────────────────────────────────────────────────

    def _evict_expired(self) -> None:
        now = time.monotonic()
        with self._lock:
            stale = [
                job_id
                for job_id, job in self._jobs.items()
                if job.finished_at is not None
                and now - job.finished_at > JOB_RETENTION_SECONDS
            ]
            for job_id in stale:
                del self._jobs[job_id]


job_registry = JobRegistry()
