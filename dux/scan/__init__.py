from __future__ import annotations

import sys
from typing import Protocol

from dux.models.scan import CancelCheck, ProgressCallback, ScanOptions, ScanResult
from dux.scan._base import ThreadedScannerBase, resolve_root
from dux.scan.python_scanner import PythonScanner


class Scanner(Protocol):
    def scan(
        self,
        path: str,
        options: ScanOptions,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ScanResult: ...


def default_scanner(workers: int = 4) -> ThreadedScannerBase:
    """Return the best available scanner for the current platform.

    macOS → NativeScanner (getattrlistbulk).
    GIL enabled → NativeScanner (C readdir, benefits from GIL release during I/O).
    GIL disabled → PythonScanner (true parallelism makes the C overhead negligible).
    """
    if sys.platform == "darwin":
        from dux._walker import scan_dir_bulk_nodes

        from dux.scan.native_scanner import NativeScanner

        return NativeScanner(scan_dir_bulk_nodes, workers=workers)

    if sys._is_gil_enabled():  # pyright: ignore[reportPrivateUsage]
        from dux._walker import scan_dir_nodes

        from dux.scan.native_scanner import NativeScanner

        return NativeScanner(scan_dir_nodes, workers=workers)

    return PythonScanner(workers=workers)


__all__ = [
    "PythonScanner",
    "Scanner",
    "ThreadedScannerBase",
    "default_scanner",
    "resolve_root",
]
