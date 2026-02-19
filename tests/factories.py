from __future__ import annotations

from dux.models.scan import ScanNode


def make_file(path: str, du: int = 0) -> ScanNode:
    name = path.rsplit("/", 1)[-1]
    node = ScanNode.file(path, name, du, du)
    return node


def make_dir(path: str, du: int = 0, children: list[ScanNode] | None = None) -> ScanNode:
    name = path.rsplit("/", 1)[-1]
    node = ScanNode.directory(path, name)
    node.size_bytes = du
    node.disk_usage = du
    if children:
        node.children = children
    return node
