"""Two-lane in-process scheduler backed by the SQLite task store."""

from __future__ import annotations

import logging
from threading import Event, RLock, Thread
from typing import Optional

from backend.app.core.task_repository import LANES, TaskRepository, task_repository
from backend.app.services.task_dispatcher import TaskDispatcher, task_dispatcher

logger = logging.getLogger(__name__)


class TaskQueue:
    """Run one sequential worker per platform lane.

    The workers do not hold task state in memory.  They claim from SQLite on
    every iteration, so queued tasks survive process restarts and a task that
    was canceled before claim can never be executed.
    """

    def __init__(self, repository: TaskRepository = task_repository, dispatcher: TaskDispatcher = task_dispatcher):
        self.repository = repository
        self.dispatcher = dispatcher
        self._stop = Event()
        self._wake = Event()
        self._lock = RLock()
        self._threads: dict[str, Thread] = {}

    def start(self) -> None:
        with self._lock:
            self._stop.clear()
            for lane in sorted(LANES):
                current = self._threads.get(lane)
                if current and current.is_alive():
                    continue
                thread = Thread(target=self._run_lane, args=(lane,), name=f"creator-tools-{lane}-worker", daemon=True)
                self._threads[lane] = thread
                thread.start()
        self._wake.set()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._wake.set()
        with self._lock:
            threads = list(self._threads.values())
        for thread in threads:
            thread.join(timeout=max(timeout, 0.1))
        with self._lock:
            self._threads = {lane: thread for lane, thread in self._threads.items() if thread.is_alive()}

    def wake(self) -> None:
        self._wake.set()

    def submit(self, *_args, **_kwargs) -> bool:
        """Compatibility API: enqueue is durable, so waking the scheduler is enough."""

        self.start()
        self._wake.set()
        return True

    def run_once(self, lane: str) -> Optional[dict]:
        task = self.repository.claim_next(lane)
        if task is None:
            return None
        return self.dispatcher.dispatch(task)

    def _run_lane(self, lane: str) -> None:
        while not self._stop.is_set():
            try:
                task = self.run_once(lane)
            except Exception:
                logger.exception("Task lane %s failed while polling", lane)
                task = None
            if task is None:
                self._wake.wait(timeout=1.0)
                self._wake.clear()


task_queue = TaskQueue()
