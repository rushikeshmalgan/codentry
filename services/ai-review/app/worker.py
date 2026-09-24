"""The single in-process review worker: a DB-polling job runner.

No new infrastructure. The `review_runs` table is the queue; this thread
claims one due job at a time (a compare-and-swap in the store), executes it
(app/review_runner.py), and periodically sweeps stuck webhook deliveries
(app/ingest.py). Consequences, all covered by tests/test_worker.py:

- A job survives a process restart: it is a row, not an in-memory task. A
  worker that dies mid-job leaves a `running` row whose lease expires, and the
  next poll reclaims it (attempts is incremented; exhausted -> `failed`).
- One job at a time keeps memory bounded on a free-tier instance.
- If the service scales to more than one instance, the conditional-update
  claim keeps two workers off the same job; `attempts` fences a stale one out
  of finalizing.

Honest limits: on a host that sleeps when idle (Render free tier) the worker
sleeps with it, so a job enqueued just before sleep waits for the next
request/wake-up; and nothing here helps an event that never reached this
service (see app/ingest.py "KNOWN REMAINING GAP").
"""

from __future__ import annotations

import logging
import threading
import time

from app.config import Settings, get_settings
from app.ingest import sweep_deliveries
from app.review_runner import execute_review_run
from app.store import ReviewStore

logger = logging.getLogger("codentry.ai_review.worker")

DELIVERY_SWEEP_INTERVAL_SECONDS = 30.0


class ReviewWorker:
    def __init__(self, store: ReviewStore, settings: Settings | None = None) -> None:
        self._store = store
        self._settings = settings or get_settings()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_sweep = 0.0

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def run_once(self) -> bool:
        """One poll: maybe sweep deliveries, then claim and execute at most one
        job. Returns True if a job was executed. Never raises."""
        try:
            now = time.monotonic()
            if now - self._last_sweep >= DELIVERY_SWEEP_INTERVAL_SECONDS:
                self._last_sweep = now
                sweep_deliveries(self._store)

            run = self._store.claim_next_review_run(self._settings.job_lease_seconds)
            if run is None:
                return False
            execute_review_run(self._store, run, self._settings)
            return True
        except Exception:
            logger.exception("worker_poll_failed")
            return False

    def _loop(self) -> None:
        logger.info("review_worker_started poll=%ss", self._settings.worker_poll_seconds)
        while not self._stop.is_set():
            worked = self.run_once()
            if not worked:
                self._stop.wait(self._settings.worker_poll_seconds)
        logger.info("review_worker_stopped")

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="review-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
