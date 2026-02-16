from __future__ import annotations

import heapq
from collections.abc import Iterator

from dux.models.enums import NodeKind
from dux.models.scan import ScanNode

# Shared empty list for file nodes — saves ~56 bytes per file vs a unique [].
# IMPORTANT: never append to this; only directory nodes get their own mutable [].
LEAF_CHILDREN: list[ScanNode] = []


def finalize_sizes(root: ScanNode) -> None:
    """Bottom-up pass: sum children sizes into directory nodes and sort by disk_usage."""
    stack: list[ScanNode] = []
    visit: list[ScanNode] = [root]
    while visit:
        node = visit.pop()
        if not node.is_dir:
            continue
        stack.append(node)
        visit.extend(node.children)
    for node in reversed(stack):
        node.size_bytes = sum(child.size_bytes for child in node.children)
        node.disk_usage = sum(child.disk_usage for child in node.children)
        node.children.sort(key=lambda x: x.disk_usage, reverse=True)


def iter_nodes(root: ScanNode) -> Iterator[ScanNode]:
    """Iterate all nodes in the tree rooted at *root* (depth-first)."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.children)


def top_nodes(root: ScanNode, n: int, kind: NodeKind | None = None) -> list[ScanNode]:
    """Return the *n* largest nodes, excluding *root*.

    When *kind* is given, only nodes of that kind are considered.
    """
    items = (node for node in iter_nodes(root) if node.path != root.path and (kind is None or node.kind is kind))
    return heapq.nlargest(n, items, key=lambda node: node.disk_usage)
