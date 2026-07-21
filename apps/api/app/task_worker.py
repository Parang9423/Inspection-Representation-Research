from __future__ import annotations

import queue
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable

TaskFunction = Callable[..., dict[str, Any] | None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BackgroundTaskWorker:
    """Single-process task queue for long-running filesystem operations.

    A single worker intentionally serializes scan/export jobs so that SQLite and
    the source filesystem are not saturated by competing bulk operations.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[str, TaskFunction, tuple[Any, ...], dict[str, Any]]] = queue.Queue()
        self._lock = threading.RLock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping.clear()
            self._thread = threading.Thread(target=self._run, name="aoi-background-worker", daemon=True)
            self._thread.start()

    def submit(
        self,
        task_type: str,
        function: TaskFunction,
        *args: Any,
        dedupe_key: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.start()
        with self._lock:
            if dedupe_key:
                for task in self._tasks.values():
                    if task.get("dedupe_key") == dedupe_key and task["status"] in {"queued", "running"}:
                        return deepcopy(task)

            task_id = uuid.uuid4().hex
            task = {
                "task_id": task_id,
                "task_type": task_type,
                "dedupe_key": dedupe_key,
                "status": "queued",
                "created_at": _now(),
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
            }
            self._tasks[task_id] = task
            self._queue.put((task_id, function, args, kwargs))
            return deepcopy(task)

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return deepcopy(task) if task else None

    def latest(self, task_type: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            tasks = list(self._tasks.values())
            if task_type:
                tasks = [task for task in tasks if task["task_type"] == task_type]
            if not tasks:
                return None
            return deepcopy(max(tasks, key=lambda task: task["created_at"]))

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                task_id, function, args, kwargs = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            with self._lock:
                task = self._tasks[task_id]
                task["status"] = "running"
                task["started_at"] = _now()

            try:
                result = function(*args, **kwargs) or {}
                with self._lock:
                    task = self._tasks[task_id]
                    task["status"] = "finished"
                    task["result"] = result
                    task["finished_at"] = _now()
            except Exception as exc:  # noqa: BLE001 - status is exposed to the UI
                with self._lock:
                    task = self._tasks[task_id]
                    task["status"] = "failed"
                    task["error"] = f"{type(exc).__name__}: {exc}"
                    task["finished_at"] = _now()
            finally:
                self._queue.task_done()


worker = BackgroundTaskWorker()
