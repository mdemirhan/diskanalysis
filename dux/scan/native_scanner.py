from __future__ import annotations

from collections.abc import Callable
from typing import override

from dux.models.enums import NodeKind
from dux.models.scan import ScanNode
from dux.scan._base import ThreadedScannerBase
from dux.services.tree import LEAF_CHILDREN

type _ScanFn = Callable[
    [str, ScanNode, list[ScanNode], NodeKind, NodeKind, type[ScanNode]],
    tuple[list[ScanNode], int, int, int],
]


class NativeScanner(ThreadedScannerBase):
    """Threaded scanner delegating to a C extension scan function."""

    def __init__(self, scan_fn: _ScanFn, *, workers: int = 8) -> None:
        super().__init__(workers=workers)
        self._scan_fn = scan_fn

    @override
    def _scan_dir(self, parent: ScanNode, path: str) -> tuple[list[ScanNode], int, int, int]:
        return self._scan_fn(path, parent, LEAF_CHILDREN, NodeKind.DIRECTORY, NodeKind.FILE, ScanNode)
