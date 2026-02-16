from __future__ import annotations

import collections
import collections.abc
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass

from result import Err, Ok

from dux.models.enums import NodeKind
from dux.models.scan import (
    CancelCheck,
    ProgressCallback,
    ScanError,
    ScanErrorCode,
    ScanNode,
    ScanOptions,
    ScanResult,
    ScanSnapshot,
    ScanStats,
)
from dux.services.fs import DEFAULT_FS, FileSystem
from dux.services.tree import finalize_sizes


@dataclass(slots=True, frozen=True)
class _Task:
    node: ScanNode
    depth: int


class _WorkQueue:
    """Lightweight work queue with a single lock (vs 3 in queue.Queue)."""

    __slots__ = ("_deque", "_lock", "_not_empty", "_outstanding", "_done", "_shutdown")

    def __init__(self) -> None:
        self._deque: collections.deque[_Task] = collections.deque()
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._outstanding = 0
        self._done = threading.Event()
        self._shutdown = False

    def put(self, task: _Task) -> None:
        with self._lock:
            self._deque.append(task)
            self._outstanding += 1
            self._not_empty.notify(1)

    def put_many(self, tasks: collections.abc.Iterable[_Task]) -> None:
        with self._lock:
            prev = len(self._deque)
            self._deque.extend(tasks)
            added = len(self._deque) - prev
            self._outstanding += added
            if added:
                self._not_empty.notify(added)

    def get(self) -> _Task | None:
        with self._not_empty:
            while not self._deque:
                if self._shutdown:
                    return None
                self._not_empty.wait()
            return self._deque.popleft()

    def task_done(self) -> None:
        with self._lock:
            self._outstanding -= 1
            if self._outstanding == 0:
                self._done.set()

    def join(self) -> None:
        self._done.wait()

    def shutdown(self) -> None:
        with self._lock:
            self._shutdown = True
            self._not_empty.notify_all()


def resolve_root(path: str, fs: FileSystem) -> str | ScanError:
    """Validate and resolve a scan root path.

    Returns the resolved absolute path, or a ``ScanError`` on failure.
    """
    expanded = fs.expanduser(path)
    if not fs.exists(expanded):
        return ScanError(
            code=ScanErrorCode.NOT_FOUND,
            path=expanded,
            message="Path does not exist",
        )

    resolved = fs.absolute(expanded)
    try:
        root_stat = fs.stat(resolved)
    except OSError as exc:
        return ScanError(
            code=ScanErrorCode.ROOT_STAT_FAILED,
            path=resolved,
            message=f"Cannot stat root: {exc}",
        )
    if not root_stat.is_dir:
        return ScanError(
            code=ScanErrorCode.NOT_DIRECTORY,
            path=resolved,
            message="Path is not a directory",
        )
    return resolved


class ThreadedScannerBase(ABC):
    def __init__(self, workers: int = 8, fs: FileSystem = DEFAULT_FS) -> None:
        self._workers = max(1, workers)
        self._fs = fs

    @abstractmethod
    def _scan_dir(self, parent: ScanNode, path: str) -> tuple[list[ScanNode], int, int, int]:
        """Read a directory, create nodes, and append them to *parent*.children.

        Returns ``(dir_child_nodes, file_count, dir_count, error_count)``.
        """

    def scan(
        self,
        path: str,
        options: ScanOptions,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ScanResult:
        resolved = resolve_root(path, self._fs)
        if isinstance(resolved, ScanError):
            return Err(resolved)
        resolved_root = resolved

        root_name = resolved_root.rsplit("/", 1)[-1] or resolved_root
        root_node = ScanNode(
            path=resolved_root,
            name=root_name,
            kind=NodeKind.DIRECTORY,
            size_bytes=0,
            disk_usage=0,
            children=[],
        )

        q = _WorkQueue()
        q.put(_Task(root_node, 0))

        stats = ScanStats(files=0, directories=1, access_errors=0)
        stats_lock = threading.Lock()
        cancelled = threading.Event()

        def _is_cancelled() -> bool:
            if cancelled.is_set():
                return True
            if cancel_check is not None and cancel_check():
                cancelled.set()
                return True
            return False

        def emit_progress(current_path: str, local_files: int, local_dirs: int) -> None:
            if progress_callback is None:
                return
            with stats_lock:
                f = stats.files + local_files
                d = stats.directories + local_dirs
            progress_callback(current_path, f, d)

        def run_worker() -> None:
            local_files = 0
            local_dirs = 0
            local_errors = 0

            def _flush_local() -> None:
                nonlocal local_files, local_dirs, local_errors
                if local_files or local_dirs or local_errors:
                    with stats_lock:
                        stats.files += local_files
                        stats.directories += local_dirs
                        stats.access_errors += local_errors
                    local_files = local_dirs = local_errors = 0

            while True:
                task = q.get()
                if task is None:
                    _flush_local()
                    break

                if _is_cancelled():
                    q.task_done()
                    continue

                try:
                    dir_children, files, dirs, errs = self._scan_dir(task.node, task.node.path)
                    prev_total = local_files + local_dirs
                    local_files += files
                    local_dirs += dirs
                    local_errors += errs

                    within_depth = options.max_depth is None or task.depth < options.max_depth
                    if within_depth:
                        next_depth = task.depth + 1
                        q.put_many(_Task(n, next_depth) for n in dir_children)

                    new_total = local_files + local_dirs
                    if new_total // 100 > prev_total // 100:
                        emit_progress(task.node.path, local_files, local_dirs)
                except Exception:  # noqa: BLE001
                    local_errors += 1
                finally:
                    _flush_local()
                    q.task_done()

        num_workers = self._workers
        threads = [threading.Thread(target=run_worker, daemon=True) for _ in range(num_workers)]
        for thread in threads:
            thread.start()
        q.join()
        q.shutdown()
        for thread in threads:
            thread.join(timeout=0.3)

        if cancelled.is_set():
            return Err(
                ScanError(
                    code=ScanErrorCode.CANCELLED,
                    path=resolved_root,
                    message="Scan cancelled",
                )
            )

        finalize_sizes(root_node)
        return Ok(ScanSnapshot(root=root_node, stats=stats))
