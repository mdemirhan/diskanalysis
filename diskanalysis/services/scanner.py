from __future__ import annotations

import asyncio
import os
import queue
import stat as statmod
import threading
from dataclasses import dataclass
from pathlib import Path

from diskanalysis.models.enums import NodeKind
from diskanalysis.models.scan import CancelCheck, ProgressCallback, ScanFailure, ScanNode, ScanOptions, ScanResult, ScanStats, ScanSuccess
from diskanalysis.services.patterns import matches_glob


@dataclass(slots=True)
class _Task:
    path: str
    depth: int
    node: ScanNode


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def _is_glob_pattern(value: str) -> bool:
    return any(ch in value for ch in "*?[]{}")


def _is_excluded(path: str, name: str, options: ScanOptions) -> bool:
    normalized = _norm(path)
    for pattern in options.exclude_paths:
        raw = _norm(pattern)
        if not _is_glob_pattern(raw):
            raw = raw.rstrip("/")
            if normalized == raw or normalized.startswith(f"{raw}/"):
                return True
        if matches_glob(pattern, normalized, name):
            return True
    return False


def _finalize_sizes(node: ScanNode) -> int:
    if not node.is_dir:
        return node.size_bytes

    total = 0
    for child in node.children:
        total += _finalize_sizes(child)
    node.children.sort(key=lambda x: x.size_bytes, reverse=True)
    node.size_bytes = total
    return total


def scan_path(
    path: str | Path,
    options: ScanOptions,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    workers: int = 4,
) -> ScanResult:
    root_path = Path(path).expanduser()
    if not root_path.exists():
        return ScanFailure(path=str(root_path), message="Path does not exist")
    if not root_path.is_dir():
        return ScanFailure(path=str(root_path), message="Path is not a directory")

    resolved_root = str(root_path.resolve())
    try:
        root_stat = root_path.stat(follow_symlinks=options.follow_symlinks)
    except OSError as exc:
        return ScanFailure(path=resolved_root, message=f"Cannot stat root: {exc}")

    root_node = ScanNode(
        path=resolved_root,
        name=root_path.name or resolved_root,
        kind=NodeKind.DIRECTORY,
        size_bytes=0,
        modified_ts=root_stat.st_mtime,
        children=[],
    )

    q: queue.Queue[_Task | None] = queue.Queue()
    q.put(_Task(path=resolved_root, depth=0, node=root_node))

    stats = ScanStats(files=0, directories=1, bytes_total=0, access_errors=0)
    stats_lock = threading.Lock()
    cancelled = threading.Event()

    def emit_progress(current_path: str) -> None:
        if progress_callback is None:
            return
        with stats_lock:
            progress_callback(current_path, stats.files, stats.directories)

    def run_worker() -> None:
        while True:
            task = q.get()
            if task is None:
                q.task_done()
                break

            if cancelled.is_set():
                q.task_done()
                continue

            if cancel_check is not None and cancel_check():
                cancelled.set()
                q.task_done()
                continue

            try:
                with os.scandir(task.path) as entries:
                    for entry in entries:
                        if cancelled.is_set():
                            break
                        if cancel_check is not None and cancel_check():
                            cancelled.set()
                            break

                        entry_path = entry.path
                        entry_name = entry.name
                        if _is_excluded(entry_path, entry_name, options):
                            continue

                        try:
                            stat_result = entry.stat(follow_symlinks=options.follow_symlinks)
                        except OSError:
                            with stats_lock:
                                stats.access_errors += 1
                            continue

                        is_dir = statmod.S_ISDIR(stat_result.st_mode)
                        node = ScanNode(
                            path=entry_path,
                            name=entry_name,
                            kind=NodeKind.DIRECTORY if is_dir else NodeKind.FILE,
                            size_bytes=0 if is_dir else stat_result.st_size,
                            modified_ts=stat_result.st_mtime,
                            children=[],
                        )
                        task.node.children.append(node)

                        if is_dir:
                            with stats_lock:
                                stats.directories += 1
                            within_depth = options.max_depth is None or task.depth < options.max_depth
                            if within_depth:
                                q.put(_Task(path=node.path, depth=task.depth + 1, node=node))
                        else:
                            with stats_lock:
                                stats.files += 1
                                stats.bytes_total += node.size_bytes
                        emit_progress(node.path)
            except OSError:
                with stats_lock:
                    stats.access_errors += 1
            finally:
                q.task_done()

    num_workers = max(1, workers)
    threads = [threading.Thread(target=run_worker, daemon=True) for _ in range(num_workers)]
    for thread in threads:
        thread.start()
    q.join()
    for _ in threads:
        q.put(None)
    q.join()
    for thread in threads:
        thread.join(timeout=0.3)

    if cancelled.is_set():
        return ScanFailure(path=resolved_root, message="Scan cancelled")

    _finalize_sizes(root_node)
    stats.bytes_total = root_node.size_bytes
    return ScanSuccess(root=root_node, stats=stats)


async def scan_path_async(
    path: str | Path,
    options: ScanOptions,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    workers: int = 4,
) -> ScanResult:
    return await asyncio.to_thread(
        scan_path,
        path,
        options,
        progress_callback,
        cancel_check,
        workers,
    )
