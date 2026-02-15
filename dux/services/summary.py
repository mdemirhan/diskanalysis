from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dux.config.schema import AppConfig
from dux.models.enums import NodeKind
from dux.models.insight import Insight, InsightBundle
from dux.models.scan import ScanNode, ScanStats
from dux.services.formatting import format_bytes
from dux.services.tree import top_nodes


def _stats_panel(root: ScanNode, stats: ScanStats) -> Panel:
    body = (
        f"Files: [bold]{stats.files}[/bold]\n"
        f"Directories: [bold]{stats.directories}[/bold]\n"
        f"Total Size: [bold]{format_bytes(root.size_bytes)}[/bold]\n"
        f"Access Errors: [bold]{stats.access_errors}[/bold]"
    )
    return Panel(body, title="Scan Summary", border_style="blue")


def _insights_table(title: str, insights: list[Insight], top_n: int) -> Table:
    table = Table(title=title, header_style="bold yellow")
    table.add_column("Path")
    table.add_column("Category")
    table.add_column("Size", justify="right")
    for item in insights[:top_n]:
        table.add_row(
            item.path,
            item.category.value,
            format_bytes(item.size_bytes),
        )
    return table


def _top_nodes_table(title: str, root: ScanNode, top_n: int, kind: NodeKind) -> Table:
    table = Table(title=title, header_style="bold yellow")
    table.add_column("Path")
    table.add_column("Size", justify="right")
    for node in top_nodes(root, top_n, kind):
        table.add_row(node.path, format_bytes(node.size_bytes))
    return table


def render_summary(
    console: Console,
    root: ScanNode,
    stats: ScanStats,
    bundle: InsightBundle,
    config: AppConfig,
) -> None:
    console.print(_stats_panel(root, stats))

    top_table = Table(title="Top Space Consumers", header_style="bold cyan")
    top_table.add_column("Path")
    top_table.add_column("Type", justify="center")
    top_table.add_column("Size", justify="right")

    for node in top_nodes(root, config.summary_top_count):
        top_table.add_row(
            node.path,
            "DIR" if node.kind is NodeKind.DIRECTORY else "FILE",
            format_bytes(node.size_bytes),
        )
    console.print(top_table)

    by_category: dict[str, tuple[int, int]] = {}
    for cat, count in bundle.category_counts.items():
        size = bundle.category_sizes.get(cat, 0)
        by_category[cat.value] = (count, size)

    cat_table = Table(title="Insights by Category", header_style="bold magenta")
    cat_table.add_column("Category")
    cat_table.add_column("Count", justify="right")
    cat_table.add_column("Size", justify="right")
    for category, (count, total) in sorted(
        by_category.items(), key=lambda x: x[1][1], reverse=True
    ):
        cat_table.add_row(category, str(count), format_bytes(total))
    console.print(cat_table)


def render_focused_summary(
    console: Console,
    root: ScanNode,
    stats: ScanStats,
    sections: list[tuple[str, list[Insight]]],
    top_n: int,
    top_folders: bool = False,
    top_files: bool = False,
) -> None:
    console.print(_stats_panel(root, stats))

    for title, insights in sections:
        console.print(_insights_table(title, insights, top_n))

    if top_folders:
        console.print(
            _top_nodes_table("Largest Folders", root, top_n, NodeKind.DIRECTORY)
        )
    if top_files:
        console.print(_top_nodes_table("Largest Files", root, top_n, NodeKind.FILE))
