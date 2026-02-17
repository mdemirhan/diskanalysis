from __future__ import annotations

from collections.abc import Callable
from typing import override

from dux.models.enums import NodeKind
from dux.models.scan import ScanNode
from dux.scan._base import ThreadedScannerBase
from dux.services.tree import LEAF_CHILDREN

# C extension calling convention:
#   (path, parent_node, leaf_sentinel, kind_dir, kind_file, ScanNode_class)
#   -> (dir_child_nodes, file_count, dir_count, error_count)
type _ScanFn = Callable[
    [str, ScanNode, tuple[()], NodeKind, NodeKind, type[ScanNode]],
    tuple[list[ScanNode], int, int, int],
]


_SCAN_FN_LABELS: dict[str, str] = {
    "scan_dir_nodes": "posix/readdir",
    "scan_dir_bulk_nodes": "macos/getattrlistbulk",
}


class NativeScanner(ThreadedScannerBase):
    """Threaded scanner delegating to a C extension scan function."""

    def __init__(self, scan_fn: _ScanFn, *, workers: int = 4) -> None:
        super().__init__(workers=workers)
        self._scan_fn = scan_fn
        self.label = _SCAN_FN_LABELS.get(getattr(scan_fn, "__name__", ""), "native")

    @override
    def _scan_dir(self, parent: ScanNode, path: str) -> tuple[list[ScanNode], int, int, int]:
        return self._scan_fn(path, parent, LEAF_CHILDREN, NodeKind.DIRECTORY, NodeKind.FILE, ScanNode)
