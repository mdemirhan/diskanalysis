from __future__ import annotations

from collections.abc import Sequence
from typing import override

from dux.scan._base import ThreadedScannerBase


class NativeScanner(ThreadedScannerBase):
    def __init__(self, workers: int = 8) -> None:
        super().__init__(workers=workers)

    @override
    def _scan_dir(self, path: str) -> tuple[Sequence[tuple[str, str, bool, int, int]], int]:
        from dux._walker import scan_dir  # type: ignore[import-not-found]

        return scan_dir(path)  # type: ignore[no-any-return]
