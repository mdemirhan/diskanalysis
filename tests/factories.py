from __future__ import annotations

from dux.models.enums import NodeKind
from dux.models.scan import ScanNode
from dux.services.tree import LEAF_CHILDREN


def make_file(path: str, du: int = 0) -> ScanNode:
    return ScanNode(
        path=path,
        name=path.rsplit("/", 1)[-1],
        kind=NodeKind.FILE,
        size_bytes=du,
        disk_usage=du,
        children=LEAF_CHILDREN,
    )


def make_dir(path: str, du: int = 0, children: list[ScanNode] | None = None) -> ScanNode:
    return ScanNode(
        path=path,
        name=path.rsplit("/", 1)[-1],
        kind=NodeKind.DIRECTORY,
        size_bytes=du,
        disk_usage=du,
        children=children or [],
    )
