from __future__ import annotations

from io import StringIO

from rich.console import Console

from dux.models.enums import InsightCategory, NodeKind
from dux.models.insight import CategoryStats, Insight, InsightBundle
from dux.models.scan import ScanNode, ScanStats
from dux.services.summary import (
    _append_size,
    _insights_table,
    _top_nodes_table,
    _trim,
    render_focused_summary,
    render_summary,
)
from dux.services.tree import LEAF_CHILDREN


def _dir(path: str, name: str, children: list[ScanNode] | None = None, du: int = 0) -> ScanNode:
    return ScanNode(
        path=path, name=name, kind=NodeKind.DIRECTORY, size_bytes=du, disk_usage=du, children=children or []
    )


def _file(path: str, name: str, du: int = 0) -> ScanNode:
    return ScanNode(path=path, name=name, kind=NodeKind.FILE, size_bytes=du, disk_usage=du, children=LEAF_CHILDREN)


def _console() -> Console:
    return Console(file=StringIO(), force_terminal=True, width=200)


def _output(c: Console) -> str:
    f = c.file
    assert isinstance(f, StringIO)
    return f.getvalue()


class TestTrim:
    def test_prefix_match(self) -> None:
        assert _trim("/root/foo/bar.txt", "/root/foo/") == "bar.txt"

    def test_prefix_mismatch(self) -> None:
        assert _trim("/other/bar.txt", "/root/foo/") == "/other/bar.txt"

    def test_escapes_rich_markup(self) -> None:
        result = _trim("/root/[bold]file", "/root/")
        assert "[" not in result or "\\[" in result or "&" in result


class TestAppendSize:
    def test_apparent_size_true(self) -> None:
        row: list[str] = []
        _append_size(row, 1024, True)
        assert len(row) == 1
        assert "1.0 KB" in row[0]

    def test_apparent_size_false(self) -> None:
        row: list[str] = []
        _append_size(row, 1024, False)
        assert len(row) == 0


class TestInsightsTable:
    def _make_insight(self, path: str, cat: InsightCategory, kind: NodeKind = NodeKind.FILE, du: int = 100) -> Insight:
        return Insight(path=path, size_bytes=du, category=cat, summary="test", kind=kind, disk_usage=du)

    def test_basic_table(self) -> None:
        insights = [self._make_insight("/r/a.log", InsightCategory.TEMP)]
        table = _insights_table("Test", insights, 10, "/r/", apparent_size=False)
        assert table.title == "Test"
        assert table.row_count == 1

    def test_apparent_size_adds_column(self) -> None:
        insights = [self._make_insight("/r/a.log", InsightCategory.TEMP)]
        table = _insights_table("Test", insights, 10, "/r/", apparent_size=True)
        col_names = [c.header for c in table.columns]
        assert any("Size" in str(h) for h in col_names)

    def test_dir_type_label(self) -> None:
        insights = [self._make_insight("/r/dir", InsightCategory.CACHE, kind=NodeKind.DIRECTORY)]
        table = _insights_table("Test", insights, 10, "/r/")
        # Row has "DIR" in type column
        assert table.row_count == 1

    def test_top_n_slicing(self) -> None:
        insights = [self._make_insight(f"/r/{i}", InsightCategory.TEMP) for i in range(10)]
        table = _insights_table("Test", insights, 3, "/r/")
        assert table.row_count == 3


class TestTopNodesTable:
    def test_basic(self) -> None:
        f1 = _file("/r/a", "a", du=100)
        f2 = _file("/r/b", "b", du=200)
        root = _dir("/r", "root", [f1, f2], du=300)
        table = _top_nodes_table("Top", root, 10, NodeKind.FILE, "/r/")
        assert table.row_count == 2

    def test_apparent_size(self) -> None:
        f1 = _file("/r/a", "a", du=100)
        root = _dir("/r", "root", [f1], du=100)
        table = _top_nodes_table("Top", root, 10, NodeKind.FILE, "/r/", apparent_size=True)
        col_names = [c.header for c in table.columns]
        assert any("Size" in str(h) for h in col_names)


class TestRenderSummary:
    def test_outputs_table(self) -> None:
        f1 = _file("/r/a.txt", "a.txt", du=1024)
        root = _dir("/r", "root", [f1], du=1024)
        stats = ScanStats(files=1, directories=1)
        c = _console()
        render_summary(c, root, stats, "/r/")
        out = _output(c)
        assert "Top Level Summary" in out
        assert "a.txt" in out

    def test_apparent_size(self) -> None:
        root = _dir("/r", "root", [], du=0)
        stats = ScanStats()
        c = _console()
        render_summary(c, root, stats, "/r/", apparent_size=True)
        out = _output(c)
        assert "Top Level Summary" in out


class TestRenderFocusedSummary:
    def _bundle(self) -> InsightBundle:
        insights = [
            Insight("/r/tmp/a", 100, InsightCategory.TEMP, "tmp", disk_usage=100),
            Insight("/r/.cache/b", 200, InsightCategory.CACHE, "cache", disk_usage=200),
        ]
        by_cat = {
            InsightCategory.TEMP: CategoryStats(count=1, size_bytes=100, disk_usage=100, paths={"/r/tmp/a"}),
            InsightCategory.CACHE: CategoryStats(count=1, size_bytes=200, disk_usage=200, paths={"/r/.cache/b"}),
            InsightCategory.BUILD_ARTIFACT: CategoryStats(),
        }
        return InsightBundle(insights=insights, by_category=by_cat)

    def test_top_temp(self) -> None:
        root = _dir("/r", "root", [], du=300)
        c = _console()
        render_focused_summary(c, root, self._bundle(), 10, "/r/", top_temp=True)
        out = _output(c)
        assert "Temporary" in out

    def test_top_cache(self) -> None:
        root = _dir("/r", "root", [], du=300)
        c = _console()
        render_focused_summary(c, root, self._bundle(), 10, "/r/", top_cache=True)
        out = _output(c)
        assert "Cache" in out

    def test_top_dirs(self) -> None:
        sub = _dir("/r/sub", "sub", [], du=100)
        root = _dir("/r", "root", [sub], du=100)
        c = _console()
        render_focused_summary(c, root, self._bundle(), 10, "/r/", top_dirs=True)
        out = _output(c)
        assert "Directories" in out

    def test_top_files(self) -> None:
        f = _file("/r/big.bin", "big.bin", du=500)
        root = _dir("/r", "root", [f], du=500)
        c = _console()
        render_focused_summary(c, root, self._bundle(), 10, "/r/", top_files=True)
        out = _output(c)
        assert "Files" in out

    def test_no_flags_produces_no_output(self) -> None:
        root = _dir("/r", "root", [], du=0)
        c = _console()
        render_focused_summary(c, root, self._bundle(), 10, "/r/")
        assert _output(c) == ""
