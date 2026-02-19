from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from dux.models.enums import InsightCategory, NodeKind
from dux.models.insight import CategoryStats, Insight
from dux.models.scan import ScanNode, ScanStats
from dux.services.formatting import format_bytes, relative_path
from dux.services.tree import top_nodes


@dataclass(slots=True)
class DisplayRow:
    path: str
    name: str
    size_bytes: int
    type_label: str = ""
    category: str | None = None
    disk_usage: int = 0


_EMPTY_STATS = CategoryStats()


def _category_bytes(by_category: dict[InsightCategory, CategoryStats], cat: InsightCategory) -> tuple[int, int]:
    """Return (size_bytes, disk_usage) for a category."""
    cs = by_category.get(cat, _EMPTY_STATS)
    return cs.size_bytes, cs.disk_usage


def overview_rows(
    root: ScanNode,
    stats: ScanStats,
    by_category: dict[InsightCategory, CategoryStats],
    overview_top: int,
    root_prefix: str,
) -> list[DisplayRow]:
    temp_sz, temp_du = _category_bytes(by_category, InsightCategory.TEMP)
    cache_sz, cache_du = _category_bytes(by_category, InsightCategory.CACHE)
    build_sz, build_du = _category_bytes(by_category, InsightCategory.BUILD_ARTIFACT)

    rows: list[DisplayRow] = [
        DisplayRow(
            path="",
            name=f"Total Disk: {format_bytes(root.disk_usage)}",
            size_bytes=root.size_bytes,
            disk_usage=root.disk_usage,
        ),
        DisplayRow(path="", name=f"Files: {stats.files:,}", size_bytes=0),
        DisplayRow(path="", name=f"Directories: {stats.directories:,}", size_bytes=0),
        DisplayRow(path="", name=f"Temp: {format_bytes(temp_du)}", size_bytes=temp_sz, disk_usage=temp_du),
        DisplayRow(path="", name=f"Cache: {format_bytes(cache_du)}", size_bytes=cache_sz, disk_usage=cache_du),
        DisplayRow(
            path="", name=f"Build Artifacts: {format_bytes(build_du)}", size_bytes=build_sz, disk_usage=build_du
        ),
        DisplayRow(path="", name=f"─────── Largest {overview_top} directories ───────", size_bytes=0),
    ]

    for node in top_nodes(root, overview_top, NodeKind.DIRECTORY):
        rows.append(
            DisplayRow(
                path=node.path,
                name=relative_path(node.path, root_prefix),
                size_bytes=node.size_bytes,
                disk_usage=node.disk_usage,
            )
        )
    return rows


def browse_rows(
    browse_root: ScanNode,
    expanded: set[str],
) -> list[DisplayRow]:
    rows: list[DisplayRow] = []
    stack: list[tuple[ScanNode, int]] = [(browse_root, 0)]
    while stack:
        node, depth = stack.pop()
        if node.kind is NodeKind.DIRECTORY:
            marker = "▼" if node.path in expanded else "▶"
            label = f"{'  ' * depth}{marker} {node.name}"
        else:
            label = f"{'  ' * depth}  {node.name}"
        rows.append(
            DisplayRow(
                path=node.path,
                name=label,
                size_bytes=node.size_bytes,
                disk_usage=node.disk_usage,
            )
        )
        if node.kind is NodeKind.DIRECTORY and node.path in expanded:
            for child in reversed(node.children):
                stack.append((child, depth + 1))
    return rows


def insight_rows(
    insights: list[Insight],
    node_by_path: dict[str, ScanNode],
    root_prefix: str,
    predicate: Callable[[Insight], bool],
) -> list[DisplayRow]:
    rows: list[DisplayRow] = []
    for item in insights:
        if not predicate(item):
            continue
        node = node_by_path.get(item.path)
        type_label = "Dir" if node is not None and node.is_dir else "File"
        rows.append(
            DisplayRow(
                path=item.path,
                name=relative_path(item.path, root_prefix),
                size_bytes=item.size_bytes,
                category=item.category.label,
                type_label=type_label,
                disk_usage=item.disk_usage,
            )
        )
    return rows


def top_nodes_rows(
    root: ScanNode,
    limit: int,
    kind: NodeKind,
    root_prefix: str,
) -> list[DisplayRow]:
    rows: list[DisplayRow] = []
    for node in top_nodes(root, limit, kind):
        rows.append(
            DisplayRow(
                path=node.path,
                name=relative_path(node.path, root_prefix),
                size_bytes=node.size_bytes,
                disk_usage=node.disk_usage,
            )
        )
    return rows
