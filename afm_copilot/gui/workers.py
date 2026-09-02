"""
Background work, so the window never freezes.

Every Gwyddion call crosses a subprocess boundary and takes seconds; a recipe
over a folder takes minutes. Running any of that on the UI thread would leave
Windows drawing the "not responding" ghost over the app. So all of it goes
through here: a task runs on a worker thread and reports back with signals,
which Qt delivers on the UI thread where widgets may safely be touched.

Nothing in this module knows what the work *is* -- callers pass a plain
callable. That keeps the panels free to add new long-running operations
without touching the threading code.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class TaskSignals(QObject):
    """Signals a task emits. Separate object because QRunnable is not a QObject."""

    started = Signal(str)          # description
    finished = Signal(str)         # description
    result = Signal(object)        # whatever the callable returned
    failed = Signal(str, str)      # description, message
    progress = Signal(str)         # a line for the log


class Task(QRunnable):
    """One unit of background work."""

    def __init__(self, description: str, fn: Callable[..., Any],
                 *args: Any, **kwargs: Any):
        super().__init__()
        self.description = description
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = TaskSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit(self.description)
        try:
            value = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            # The traceback goes to the log; the message goes to the user.
            detail = traceback.format_exc(limit=3)
            self.signals.progress.emit(detail)
            self.signals.failed.emit(self.description, str(exc))
        else:
            self.signals.result.emit(value)
            self.signals.finished.emit(self.description)


class TaskRunner:
    """
    Runs tasks on a thread pool and keeps them alive while they run.

    Qt deletes a QRunnable once it finishes, but the signals object must
    outlive the connections, so tasks are held until they report back.
    """

    def __init__(self, max_threads: int = 2):
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(max_threads)
        self._live: list[Task] = []

    def submit(
        self,
        description: str,
        fn: Callable[..., Any],
        *args: Any,
        on_result: Callable[[Any], None] | None = None,
        on_started: Callable[[str], None] | None = None,
        on_finished: Callable[[str], None] | None = None,
        on_failed: Callable[[str, str], None] | None = None,
        on_progress: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> Task:
        task = Task(description, fn, *args, **kwargs)
        if on_result:
            task.signals.result.connect(on_result)
        if on_started:
            task.signals.started.connect(on_started)
        if on_progress:
            task.signals.progress.connect(on_progress)
        if on_failed:
            task.signals.failed.connect(on_failed)

        def _done(desc: str) -> None:
            if on_finished:
                on_finished(desc)
            self._retire(task)

        def _died(desc: str, msg: str) -> None:
            self._retire(task)

        task.signals.finished.connect(_done)
        task.signals.failed.connect(_died)

        self._live.append(task)
        self._pool.start(task)
        return task

    def _retire(self, task: Task) -> None:
        if task in self._live:
            self._live.remove(task)

    @property
    def busy(self) -> bool:
        return bool(self._live)

    def wait(self, msecs: int = 5000) -> bool:
        """Block until the pool drains. Only for shutdown."""
        return self._pool.waitForDone(msecs)
