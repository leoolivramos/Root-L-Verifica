"""Background job manager (RNF-06): an asyncio loop in a daemon thread, with cancellation."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future

from reliability.pipeline import Deps, create_analysis, run_analysis
from reliability.schemas import Depth


class JobManager:
    def __init__(self, deps: Deps):
        self.deps = deps
        self._tasks: dict[int, asyncio.Task] = {}
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(target=self._run_loop, name="reliability-jobs", daemon=True)
        self.deps.repo.fail_orphans()
        self._thread.start()
        self._ready.wait(timeout=10)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    # ---------------------------------------------------------------- public API
    def submit(self, raw_input: str, depth: Depth = Depth.FAST) -> int:
        """Validate input (raises InvalidInput), create the record and start the job."""
        analysis_id = create_analysis(self.deps, raw_input, depth)
        assert self._loop is not None
        fut: Future = asyncio.run_coroutine_threadsafe(self._spawn(analysis_id), self._loop)
        fut.result(timeout=10)
        return analysis_id

    def cancel(self, analysis_id: int) -> bool:
        with self._lock:
            task = self._tasks.get(analysis_id)
        if task is None or self._loop is None:
            return False
        self._loop.call_soon_threadsafe(task.cancel)
        return True

    def is_running(self, analysis_id: int) -> bool:
        with self._lock:
            return analysis_id in self._tasks

    def wait(self, analysis_id: int, timeout: float = 30.0) -> bool:
        """Block until the job ends (used by tests / CLI). True if finished."""
        import time

        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not self.is_running(analysis_id):
                return True
            time.sleep(0.02)
        return False

    def shutdown(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)

    # ------------------------------------------------------------------ internals
    async def _spawn(self, analysis_id: int) -> None:
        task = asyncio.create_task(run_analysis(analysis_id, self.deps), name=f"analysis-{analysis_id}")
        with self._lock:
            self._tasks[analysis_id] = task

        def _done(_t: asyncio.Task) -> None:
            with self._lock:
                self._tasks.pop(analysis_id, None)

        task.add_done_callback(_done)
