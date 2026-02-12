from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, override

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from diskanalysis.config.schema import AppConfig
from diskanalysis.models.enums import InsightCategory, NodeKind
from diskanalysis.models.insight import Insight, InsightBundle
from diskanalysis.models.scan import ScanNode, ScanSuccess
from diskanalysis.services.formatting import format_bytes, format_ts, relative_bar


TABS = ["overview", "browse", "insights", "temp", "cache"]


@dataclass(slots=True)
class DisplayRow:
    path: str
    name: str
    size_bytes: int
    right: str


class HelpOverlay(ModalScreen[None]):
    CSS = """
    HelpOverlay {
        align: center middle;
        background: rgba(0,0,0,0.45);
    }
    #help-box {
        width: 88%;
        height: 86%;
        background: #282a2e;
        border: solid #81a2be;
        padding: 1 2;
        color: #c5c8c6;
    }
    """

    @override
    def compose(self) -> ComposeResult:
        content = "\n".join(
            [
                "[b #81a2be]Navigation[/]",
                "  j/k or arrows: Move",
                "  gg / G / Home / End: Top/Bottom",
                "  PgUp/PgDn, Ctrl+U/Ctrl+D: Page",
                "",
                "[b #81a2be]Views[/]",
                "  Tab / Shift+Tab: Next/Previous view",
                "  o / b / i / t / c: Jump to view",
                "",
                "[b #81a2be]Browse[/]",
                "  h / Left: Collapse or parent",
                "  l / Right: Expand or drill in",
                "  Enter: Drill in",
                "  Backspace: Drill out",
                "  Space: Toggle expand/collapse",
                "",
                "[b #81a2be]Search[/]",
                "  /: Start search",
                "  n / N: Next/Prev match",
                "  Enter: Finish search",
                "  Esc: Clear search",
                "",
                "[b #81a2be]Other[/]",
                "  ?: Toggle help",
                "  q / Ctrl+C: Quit",
            ]
        )
        yield Static(content, id="help-box")

    def key_escape(self) -> None:
        self.dismiss()

    def key_q(self) -> None:
        self.dismiss()

    def key_question_mark(self) -> None:
        self.dismiss()


class DiskAnalyzerApp(App[None]):
    CSS_PATH = "app.tcss"

    def __init__(
        self,
        scan: ScanSuccess,
        bundle: InsightBundle,
        config: AppConfig,
        initial_view: str = "overview",
    ) -> None:
        super().__init__()
        self.scan = scan
        self.bundle = bundle
        self.config = config
        self.current_view = initial_view if initial_view in TABS else "overview"

        self.node_by_path: dict[str, ScanNode] = {}
        self.parent_by_path: dict[str, str] = {}
        self._index_tree(self.scan.root, parent=None)

        self.browse_root_path = self.scan.root.path
        self.expanded: set[str] = {self.scan.root.path}

        self.rows: list[DisplayRow] = []
        self.selected_index = 0
        self.search_mode = False
        self.search_query = ""
        self.search_matches: list[int] = []
        self.search_match_cursor = -1
        self.pending_g = False
        self._rows_cache: dict[str, list[DisplayRow]] = {}
        self._browse_cache_version = 0
        self._browse_cached_signature: tuple[str, int] | None = None
        self._browse_cached_rows: list[DisplayRow] | None = None

    def _index_tree(self, node: ScanNode, parent: str | None) -> None:
        self.node_by_path[node.path] = node
        if parent is not None:
            self.parent_by_path[node.path] = parent
        for child in node.children:
            self._index_tree(child, node.path)

    @override
    def compose(self) -> ComposeResult:
        yield Container(
            Static(id="header-row"),
            Static(id="path-row"),
            Static(id="tabs-row"),
            Static(id="breadcrumb-row"),
            Static("─" * 200, id="separator-top"),
            DataTable(id="content-table"),
            Static("─" * 200, id="separator-bottom"),
            Static(id="info-row"),
            Static(id="status-row"),
            id="app-grid",
        )

    def on_mount(self) -> None:
        table = self.query_one("#content-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.focus()
        self._refresh_all()

    def _refresh_all(self) -> None:
        self._render_header_rows()
        self._render_content_table()
        self._render_footer_rows()

    def _invalidate_rows(self, view: str) -> None:
        self._rows_cache.pop(view, None)

    def _invalidate_browse_rows(self) -> None:
        self._browse_cache_version += 1
        self._browse_cached_signature = None
        self._browse_cached_rows = None
        self._invalidate_rows("browse")

    def _render_header_rows(self) -> None:
        self.query_one("#header-row", Static).update(
            Text.from_markup(
                (
                    "[bold #8abeb7]DiskAnalysis[/]  [#969896]Terminal Disk Intelligence[/]"
                    f"    [bold #f0c674]Total:[/] [bold #de935f]{format_bytes(self.scan.root.size_bytes)}[/]"
                )
            )
        )
        self.query_one("#path-row", Static).update(Text.from_markup(f"[#81a2be]Path:[/] {self.scan.root.path}"))

        tab_items: list[str] = []
        for tab in TABS:
            label = tab.capitalize()
            if tab == self.current_view:
                tab_items.append(f"[bold #1d1f21 on #b5bd68] {label} [/] ")
            else:
                tab_items.append(f"[#c5c8c6 on #373b41] {label} [/] ")
        self.query_one("#tabs-row", Static).update(Text.from_markup(" ".join(tab_items)))

        if self.current_view == "browse":
            rel = (
                Path(self.browse_root_path).relative_to(Path(self.scan.root.path))
                if self.browse_root_path != self.scan.root.path
                else Path(".")
            )
            depth = 0 if str(rel) == "." else len(rel.parts)
            crumbs = [part for part in rel.parts if part not in {"."}]
            crumb_text = " / ".join(crumbs) if crumbs else "/"
            self.query_one("#breadcrumb-row", Static).update(
                Text.from_markup(f"[#8abeb7]Browse:[/] {crumb_text}    [#969896]Depth {depth}[/]")
            )
        else:
            self.query_one("#breadcrumb-row", Static).update(Text.from_markup(f"[#8abeb7]View:[/] {self.current_view.capitalize()}"))

    def _render_content_table(self) -> None:
        table = self.query_one("#content-table", DataTable)
        right_header = "MODIFIED" if self.current_view == "browse" else "CATEGORY"
        table.clear(columns=True)
        table.add_columns("NAME", "SIZE", "BAR", right_header)

        self.rows = self._build_rows_for_current_view()
        if not self.rows:
            self.rows = [DisplayRow(path=".", name="(no data)", size_bytes=0, right="-")]

        total = max(1, self.rows[0].size_bytes if self.current_view == "browse" else self.scan.root.size_bytes)
        for row in self.rows:
            table.add_row(row.name, format_bytes(row.size_bytes), relative_bar(row.size_bytes, total, 18), row.right)

        self.selected_index = max(0, min(self.selected_index, len(self.rows) - 1))
        table.move_cursor(row=self.selected_index, animate=False)

    def _render_footer_rows(self) -> None:
        total_rows = len(self.rows)
        cursor = min(total_rows, self.selected_index + 1)
        info = (
            f"Safe to delete: {format_bytes(self.bundle.safe_reclaimable_bytes)}"
            + f"    Reclaimable: {format_bytes(self.bundle.reclaimable_bytes)}"
            + f"    Row {cursor}/{total_rows}"
        )
        self.query_one("#info-row", Static).update(Text.from_markup(f"[#b5bd68]{info}[/]"))

        if self.search_mode:
            status = f"SEARCH: /{self.search_query}  (Enter: keep, Esc: clear)"
        else:
            status = "q quit | ? help | Tab views | / search | n/N next/prev | j/k move"
            if self.current_view == "browse":
                status += " | h/l collapse-expand | Enter drill-in | Backspace drill-out"
        self.query_one("#status-row", Static).update(Text.from_markup(f"[#969896]{status}[/]"))

    def _build_rows_for_current_view(self) -> list[DisplayRow]:
        cached = self._rows_cache.get(self.current_view)
        if cached is not None:
            return cached

        if self.current_view == "overview":
            rows = self._overview_rows()
        elif self.current_view == "browse":
            rows = self._browse_rows()
        elif self.current_view == "insights":
            rows = self._insight_rows(lambda _: True)
        elif self.current_view == "temp":
            rows = self._insight_rows(lambda i: i.category in {InsightCategory.TEMP, InsightCategory.BUILD_ARTIFACT})
        else:
            rows = self._insight_rows(lambda i: i.category is InsightCategory.CACHE)

        self._rows_cache[self.current_view] = rows
        return rows

    def _overview_rows(self) -> list[DisplayRow]:
        rows: list[DisplayRow] = [
            DisplayRow(path="stats.files", name=f"Files: {self.scan.stats.files}", size_bytes=0, right="STAT"),
            DisplayRow(path="stats.dirs", name=f"Directories: {self.scan.stats.directories}", size_bytes=0, right="STAT"),
            DisplayRow(path="stats.insights", name=f"Insights: {len(self.bundle.insights)}", size_bytes=0, right="STAT"),
            DisplayRow(
                path="stats.safe",
                name=f"Safe to delete: {format_bytes(self.bundle.safe_reclaimable_bytes)}",
                size_bytes=self.bundle.safe_reclaimable_bytes,
                right="STAT",
            ),
            DisplayRow(
                path="stats.reclaim",
                name=f"Reclaimable: {format_bytes(self.bundle.reclaimable_bytes)}",
                size_bytes=self.bundle.reclaimable_bytes,
                right="STAT",
            ),
        ]

        top_items = sorted(self.node_by_path.values(), key=lambda x: x.size_bytes, reverse=True)
        for node in [item for item in top_items if item.path != self.scan.root.path][: self.config.top_n]:
            typ = "DIR" if node.kind is NodeKind.DIRECTORY else "FILE"
            rows.append(DisplayRow(path=node.path, name=f"{node.name}", size_bytes=node.size_bytes, right=typ))
        return rows

    def _browse_rows(self) -> list[DisplayRow]:
        signature = (self.browse_root_path, self._browse_cache_version)
        if self._browse_cached_signature == signature and self._browse_cached_rows is not None:
            return self._browse_cached_rows

        root = self.node_by_path.get(self.browse_root_path, self.scan.root)
        rows: list[DisplayRow] = []

        def walk(node: ScanNode, depth: int) -> None:
            if node.kind is NodeKind.DIRECTORY:
                marker = "▼" if node.path in self.expanded else "▶"
                label = f"{'  ' * depth}{marker} {node.name}"
            else:
                label = f"{'  ' * depth}  {node.name}"
            rows.append(DisplayRow(path=node.path, name=label, size_bytes=node.size_bytes, right=format_ts(node.modified_ts)))

            if node.kind is NodeKind.DIRECTORY and node.path in self.expanded:
                for child in node.children:
                    walk(child, depth + 1)

        walk(root, 0)
        self._browse_cached_signature = signature
        self._browse_cached_rows = rows
        return rows

    def _insight_rows(self, predicate: Callable[[Insight], bool]) -> list[DisplayRow]:
        rows: list[DisplayRow] = []
        for item in [x for x in self.bundle.insights if predicate(x)]:
            rows.append(
                DisplayRow(
                    path=item.path,
                    name=item.path,
                    size_bytes=item.size_bytes,
                    right=item.category.value,
                )
            )
        return rows

    def _set_view(self, view: str) -> None:
        if view not in TABS:
            return
        self.current_view = view
        self.selected_index = 0
        self.pending_g = False
        self._refresh_all()

    def _move_selection(self, delta: int) -> None:
        if not self.rows:
            return
        new_index = max(0, min(len(self.rows) - 1, self.selected_index + delta))
        self.selected_index = new_index
        table = self.query_one("#content-table", DataTable)
        table.move_cursor(row=new_index, animate=False)
        self._render_footer_rows()

    def _move_top(self) -> None:
        if not self.rows:
            return
        self.selected_index = 0
        table = self.query_one("#content-table", DataTable)
        table.move_cursor(row=0, animate=False)
        self._render_footer_rows()

    def _move_bottom(self) -> None:
        if not self.rows:
            return
        self.selected_index = max(0, len(self.rows) - 1)
        table = self.query_one("#content-table", DataTable)
        table.move_cursor(row=self.selected_index, animate=False)
        self._render_footer_rows()

    def _sync_selection_from_table(self) -> None:
        if not self.rows:
            self.selected_index = 0
            return
        table = self.query_one("#content-table", DataTable)
        cursor_row = table.cursor_row
        if cursor_row is None:
            return
        self.selected_index = max(0, min(len(self.rows) - 1, cursor_row))

    def _selected_path(self) -> str | None:
        self._sync_selection_from_table()
        if not self.rows:
            return None
        return self.rows[self.selected_index].path

    def _toggle_expand(self) -> None:
        if self.current_view != "browse":
            return
        path = self._selected_path()
        if path is None:
            return
        node = self.node_by_path.get(path)
        if node is None or node.kind is not NodeKind.DIRECTORY:
            return
        if path in self.expanded:
            self.expanded.remove(path)
        else:
            self.expanded.add(path)
        self._invalidate_browse_rows()
        self._refresh_all()

    def _collapse_or_parent(self) -> None:
        if self.current_view != "browse":
            return
        path = self._selected_path()
        if path is None:
            return

        node = self.node_by_path.get(path)
        if node is not None and node.kind is NodeKind.DIRECTORY and path in self.expanded and path != self.browse_root_path:
            self.expanded.remove(path)
            self._invalidate_browse_rows()
            self._refresh_all()
            return

        parent = self.parent_by_path.get(path)
        if parent is None:
            return
        for index, row in enumerate(self.rows):
            if row.path == parent:
                self.selected_index = index
                break
        self._refresh_all()

    def _expand_or_drill(self) -> None:
        if self.current_view != "browse":
            return
        path = self._selected_path()
        if path is None:
            return
        node = self.node_by_path.get(path)
        if node is None or node.kind is not NodeKind.DIRECTORY:
            return

        if path not in self.expanded:
            self.expanded.add(path)
            self._invalidate_browse_rows()
            self._refresh_all()
            return

        self.browse_root_path = path
        self.expanded.add(path)
        self.selected_index = 0
        self._invalidate_browse_rows()
        self._refresh_all()

    def _drill_out(self) -> None:
        if self.current_view != "browse":
            return
        if self.browse_root_path == self.scan.root.path:
            return
        parent = self.parent_by_path.get(self.browse_root_path)
        if parent is None:
            return
        old_root = self.browse_root_path
        self.browse_root_path = parent
        self.selected_index = 0
        self._invalidate_browse_rows()
        self._refresh_all()
        for idx, row in enumerate(self.rows):
            if row.path == old_root:
                self.selected_index = idx
                break
        self._refresh_all()

    def _update_search_matches(self) -> None:
        query = self.search_query.strip().lower()
        if not query:
            self.search_matches = []
            self.search_match_cursor = -1
            return

        self.search_matches = [
            idx
            for idx, row in enumerate(self.rows)
            if query in row.name.lower() or query in row.path.lower()
        ]
        self.search_match_cursor = 0 if self.search_matches else -1
        if self.search_match_cursor >= 0:
            self.selected_index = self.search_matches[self.search_match_cursor]

    def _goto_next_match(self, backward: bool = False) -> None:
        if not self.search_matches:
            return
        if backward:
            self.search_match_cursor = (self.search_match_cursor - 1) % len(self.search_matches)
        else:
            self.search_match_cursor = (self.search_match_cursor + 1) % len(self.search_matches)
        self.selected_index = self.search_matches[self.search_match_cursor]
        self._refresh_all()

    @on(DataTable.RowSelected)
    def _on_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.cursor_row != self.selected_index:
            self.selected_index = event.cursor_row
            self._render_footer_rows()

    @on(DataTable.RowHighlighted)
    def _on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row != self.selected_index:
            self.selected_index = event.cursor_row
            self._render_footer_rows()

    @override
    def on_key(self, event) -> None:  # type: ignore[override]
        key = event.key
        char = event.character or ""

        if self.search_mode:
            if key == "enter":
                self.search_mode = False
                self._refresh_all()
                event.stop()
                return
            if key == "escape":
                self.search_mode = False
                self.search_query = ""
                self.search_matches = []
                self.search_match_cursor = -1
                self._refresh_all()
                event.stop()
                return
            if key == "backspace":
                self.search_query = self.search_query[:-1]
                self._update_search_matches()
                self._refresh_all()
                event.stop()
                return
            if event.character and event.is_printable:
                self.search_query += event.character
                self._update_search_matches()
                self._refresh_all()
                event.stop()
                return

        if key in {"q", "ctrl+c"}:
            self.exit()
            return
        if key == "question_mark":
            self.push_screen(HelpOverlay())
            return
        if key == "tab":
            self._set_view(TABS[(TABS.index(self.current_view) + 1) % len(TABS)])
            return
        if key in {"shift+tab", "backtab"}:
            self._set_view(TABS[(TABS.index(self.current_view) - 1) % len(TABS)])
            return
        if key in {"o", "b", "i", "t", "c"}:
            mapping = {"o": "overview", "b": "browse", "i": "insights", "t": "temp", "c": "cache"}
            self._set_view(mapping[key])
            return

        if key == "j":
            self._move_selection(1)
            return
        if key == "k":
            self._move_selection(-1)
            return
        if key == "ctrl+d":
            self._move_selection(10)
            return
        if key == "ctrl+u":
            self._move_selection(-10)
            return
        if key in {"pagedown"}:
            self._move_selection(10)
            return
        if key in {"pageup"}:
            self._move_selection(-10)
            return
        if key in {"home", "ctrl+home"}:
            self._move_top()
            return
        if key in {"end", "ctrl+end"}:
            self._move_bottom()
            return
        if key == "g" or char == "g":
            if self.pending_g:
                self.pending_g = False
                self._move_top()
            else:
                self.pending_g = True
                self.set_timer(0.5, lambda: setattr(self, "pending_g", False))
            return
        if key in {"G", "shift+g"} or char == "G":
            self._move_bottom()
            return

        if key == "/":
            self.search_mode = True
            self.search_query = ""
            self.search_matches = []
            self.search_match_cursor = -1
            self._refresh_all()
            return

        if (key in {"n", "N", "shift+n"} or char in {"n", "N"}) and self.search_query:
            self._goto_next_match(backward=(key in {"N", "shift+n"} or char == "N"))
            return

        if self.current_view == "browse":
            if key in {"h", "left"}:
                self._collapse_or_parent()
                return
            if key in {"l", "right"}:
                self._expand_or_drill()
                return
            if key == "space":
                self._toggle_expand()
                return
            if key == "enter":
                self._expand_or_drill()
                return
            if key == "backspace":
                self._drill_out()
                return

        if key == "escape" and self.search_query:
            self.search_query = ""
            self.search_matches = []
            self.search_match_cursor = -1
            self._refresh_all()
