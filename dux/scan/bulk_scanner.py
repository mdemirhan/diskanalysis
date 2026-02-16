from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import override

from dux.scan._base import ThreadedScannerBase


class BulkScanner(ThreadedScannerBase):
    """Threaded scanner using macOS getattrlistbulk (single syscall per dir batch)."""

    def __init__(self, workers: int = 8) -> None:
        if sys.platform != "darwin":
            msg = "BulkScanner requires macOS"
            raise RuntimeError(msg)
        super().__init__(workers=workers)

    @override
    def _scan_dir(self, path: str) -> tuple[Sequence[tuple[str, str, bool, int, int]], int]:
        from dux._walker import scan_dir_bulk  # type: ignore[import-not-found]

        return scan_dir_bulk(path)  # type: ignore[no-any-return]
