"""Small in-process queue for ordered Instagram publish batches.

The job and child-task state is persisted in the JSON store; this queue only
controls when the worker runs.  Keeping one worker preserves the existing
ordered-processing and pause-on-first-failure guarantees without adding Redis
or a separate worker service to this deployment.
"""

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from threading import RLock
from typing import Any, Callable

logger = logging.getLogger(__name__)


class InstagramPublishQueue:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="instagram-publish")
        self._lock = RLock()
        self._futures: dict[str, Future[Any]] = {}

    def submit(self, job_id: str, worker: Callable[..., Any], *args: Any) -> bool:
        """Queue a job once; return False when that job is already running."""
        with self._lock:
            current = self._futures.get(job_id)
            if current and not current.done():
                return False
            future = self._executor.submit(worker, job_id, *args)
            self._futures[job_id] = future
            future.add_done_callback(lambda completed: self._finish(job_id, completed))
            return True

    def _finish(self, job_id: str, future: Future[Any]) -> None:
        with self._lock:
            if self._futures.get(job_id) is future:
                self._futures.pop(job_id, None)
        try:
            future.result()
        except Exception:
            logger.exception("Instagram publish queue worker failed for job %s", job_id)


instagram_publish_queue = InstagramPublishQueue()
