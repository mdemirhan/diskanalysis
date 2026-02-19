# Threaded directory scanner — base class and work queue.
#
# Architecture:
#   ThreadedScannerBase uses the Template Method pattern: subclasses implement
#   _scan_dir (read one directory, create ScanNode children), while the base
#   class handles threading, work distribution, progress, cancellation, and
#   tree finalization.
#
# Thread safety model:
#   The scan tree is built concurrently, but each directory node is processed
#   by exactly one worker (guaranteed by the work queue).  Workers append
#   children to parent.children — since each parent is dequeued by one worker,
#   there is no concurrent mutation of the same list.  The shared ScanStats
#   counters are protected by stats_lock via local batching (see run_worker).
#
# Lifecycle (scan method):
#   1. Validate root path → create root ScanNode → enqueue it.
#   2. Workers loop: dequeue a directory, call _scan_dir, enqueue child dirs.
#   3. When _outstanding hits 0, all dirs are scanned → workers exit.
#   4. finalize_sizes aggregates child sizes bottom-up and sorts children.
#   5. Return frozen ScanSnapshot wrapping the completed tree.

from __future__ import annotations

import collections
import collections.abc
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass

from result import Err, Ok

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
    """Work queue item: a directory node to scan and its depth in the tree."""

    node: ScanNode
    depth: int


class _WorkQueue:
    """Lightweight work queue with a single lock.

    stdlib queue.Queue uses three Conditions (not_empty, not_full, all_tasks_done),
    each wrapping its own lock.  This queue is unbounded (no not_full) and uses a
    simple Event for completion (no all_tasks_done Condition), cutting lock
    contention in half for the producer-heavy scan workload.
    """

    __slots__ = ("_deque", "_lock", "_not_empty", "_outstanding", "_done", "_shutdown")

    def __init__(self) -> None:
        self._deque: collections.deque[_Task] = collections.deque()
        self._lock = threading.Lock()
        # Condition wraps _lock: `with self._not_empty` also acquires _lock.
        self._not_empty = threading.Condition(self._lock)
        # _outstanding tracks enqueued-but-not-done tasks.  When it drops to 0,
        # all work is complete (analogous to Queue.all_tasks_done).
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
            # tasks is often a generator (can't len()), so measure the
            # deque before/after to count how many were added.
            prev = len(self._deque)
            self._deque.extend(tasks)
            added = len(self._deque) - prev
            self._outstanding += added
            if added:
                self._not_empty.notify(added)

    def get(self) -> _Task | None:
        """Block until a task is available.  Returns None on shutdown (exit sentinel)."""
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
    """Template Method base for threaded directory scanners.

    Subclasses implement ``_scan_dir`` (how to read one directory); this class
    handles multi-threaded work distribution, depth limiting, progress
    reporting, cancellation, and tree finalization.
    """

    def __init__(self, workers: int = 4, fs: FileSystem = DEFAULT_FS) -> None:
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
        root_node = ScanNode.directory(resolved_root, root_name)

        q = _WorkQueue()
        q.put(_Task(root_node, 0))

        stats = ScanStats(files=0, directories=1, access_errors=0)
        stats_lock = threading.Lock()
        cancelled = threading.Event()

        def _is_cancelled() -> bool:
            # Once any worker detects cancellation, the Event is set so
            # subsequent checks are a fast Event.is_set() without calling
            # the user's cancel_check callback.
            if cancelled.is_set():
                return True
            if cancel_check is not None and cancel_check():
                cancelled.set()
                return True
            return False

        def emit_progress(current_path: str, local_files: int, local_dirs: int) -> None:
            """Report approximate totals: flushed global stats + unflushed local counts."""
            if progress_callback is None:
                return
            with stats_lock:
                f = stats.files + local_files
                d = stats.directories + local_dirs
            progress_callback(current_path, f, d)

        def run_worker() -> None:
            # Workers batch stat updates locally and flush under the shared lock
            # once per directory (in the finally block).  This reduces lock
            # contention from once-per-file to once-per-directory.
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

                    # Depth gate: the current directory is always scanned, but its
                    # subdirectories are only enqueued if we haven't hit max_depth.
                    within_depth = options.max_depth is None or task.depth < options.max_depth
                    if within_depth:
                        next_depth = task.depth + 1
                        q.put_many(_Task(n, next_depth) for n in dir_children)

                    # Emit progress roughly every 100 items (integer division
                    # trick: fires when the count crosses a 100-boundary).
                    new_total = local_files + local_dirs
                    if new_total // 100 > prev_total // 100:
                        emit_progress(task.node.path, local_files, local_dirs)
                except Exception:  # noqa: BLE001
                    # Broad catch is intentional: _scan_dir may raise on
                    # permission errors, broken symlinks, etc.  We count
                    # the error and keep the worker alive for other dirs.
                    local_errors += 1
                finally:
                    _flush_local()
                    q.task_done()

        num_workers = self._workers
        threads = [threading.Thread(target=run_worker, daemon=True) for _ in range(num_workers)]
        for thread in threads:
            thread.start()
        # join() waits until all enqueued tasks are done.  Only then do we
        # call shutdown() to unblock workers stuck in get().  Reversing this
        # order would let workers exit before all tasks are processed.
        q.join()
        q.shutdown()
        for thread in threads:
            # Defensive timeout — workers should already be exiting after
            # shutdown(); this prevents hanging if one gets stuck.
            thread.join(timeout=0.3)

        if cancelled.is_set():
            return Err(
                ScanError(
                    code=ScanErrorCode.CANCELLED,
                    path=resolved_root,
                    message="Scan cancelled",
                )
            )

        # All workers are done.  Aggregate child sizes bottom-up and sort
        # children by disk_usage descending, then freeze into a snapshot.
        finalize_sizes(root_node)
        return Ok(ScanSnapshot(root=root_node, stats=stats))
