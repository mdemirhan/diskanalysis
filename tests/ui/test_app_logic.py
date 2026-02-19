from __future__ import annotations

from dux.config.schema import AppConfig
from dux.models.enums import InsightCategory, NodeKind
from dux.models.insight import CategoryStats, Insight, InsightBundle
from dux.models.scan import ScanNode, ScanStats
from dux.services.tree import finalize_sizes
from dux.ui.app import DuxApp, _PagedState
from tests.factories import make_dir, make_file


def _make_app(
    root: ScanNode | None = None,
    stats: ScanStats | None = None,
    bundle: InsightBundle | None = None,
    config: AppConfig | None = None,
    apparent_size: bool = False,
) -> DuxApp:
    if root is None:
        f1 = make_file("/r/a.txt", du=100)
        f2 = make_file("/r/b.txt", du=200)
        sub_f = make_file("/r/sub/c.txt", du=50)
        sub = make_dir("/r/sub", du=50, children=[sub_f])
        root = make_dir("/r", du=350, children=[f1, f2, sub])
        finalize_sizes(root)
    if stats is None:
        stats = ScanStats(files=3, directories=2)
    if bundle is None:
        bundle = InsightBundle(insights=[], by_category={cat: CategoryStats() for cat in InsightCategory})
    if config is None:
        config = AppConfig(
            page_size=50,
            max_insights_per_category=100,
            overview_top_dirs=10,
            scroll_step=5,
        )
    return DuxApp(root=root, stats=stats, bundle=bundle, config=config, apparent_size=apparent_size)


class TestRelativePath:
    def test_strips_root_prefix(self) -> None:
        from dux.services.formatting import relative_path

        assert relative_path("/r/a.txt", "/r/") == "a.txt"

    def test_returns_full_if_no_match(self) -> None:
        from dux.services.formatting import relative_path

        assert relative_path("/other/x.txt", "/r/") == "/other/x.txt"


class TestIndexTree:
    def test_all_nodes_indexed(self) -> None:
        app = _make_app()
        assert "/r" in app.node_by_path
        assert "/r/a.txt" in app.node_by_path
        assert "/r/sub" in app.node_by_path
        assert "/r/sub/c.txt" in app.node_by_path

    def test_parent_by_path(self) -> None:
        app = _make_app()
        assert app.parent_by_path["/r/a.txt"] == "/r"
        assert app.parent_by_path["/r/sub/c.txt"] == "/r/sub"
        assert "/r" not in app.parent_by_path  # root has no parent


class TestOverviewRows:
    def test_contains_totals_and_dirs(self) -> None:
        app = _make_app()
        rows = app._overview_rows()
        names = [r.name for r in rows]
        assert any("Total" in n for n in names)
        assert any("Files" in n for n in names)
        assert any("Directories" in n for n in names)
        assert len(rows) > 7


class TestBrowseRows:
    def test_collapsed_shows_root_only(self) -> None:
        f = make_file("/r/a.txt", du=10)
        sub = make_dir("/r/sub", du=5)
        root = make_dir("/r", du=15, children=[f, sub])
        finalize_sizes(root)
        app = _make_app(root=root)
        rows = app._browse_rows()
        assert len(rows) >= 2

    def test_expanded_shows_children(self) -> None:
        f = make_file("/r/sub/a.txt", du=10)
        sub = make_dir("/r/sub", du=10, children=[f])
        root = make_dir("/r", du=10, children=[sub])
        finalize_sizes(root)
        app = _make_app(root=root)
        app.expanded.add("/r/sub")
        rows = app._browse_rows()
        paths = [r.path for r in rows]
        assert "/r/sub/a.txt" in paths

    def test_directory_markers(self) -> None:
        sub = make_dir("/r/sub", du=5)
        root = make_dir("/r", du=5, children=[sub])
        finalize_sizes(root)
        app = _make_app(root=root)
        rows = app._browse_rows()
        root_row = rows[0]
        sub_row = rows[1]
        assert "▼" in root_row.name  # expanded
        assert "▶" in sub_row.name  # collapsed


class TestInsightRows:
    def test_returns_matching_insights(self) -> None:
        insights = [
            Insight("/r/tmp/a", 100, InsightCategory.TEMP, "tmp", disk_usage=100),
            Insight("/r/.cache/b", 200, InsightCategory.CACHE, "cache", disk_usage=200),
        ]
        bundle = InsightBundle(
            insights=insights,
            by_category={cat: CategoryStats() for cat in InsightCategory},
        )
        app = _make_app(bundle=bundle)
        rows = app._insight_rows(lambda i: i.category is InsightCategory.TEMP)
        assert len(rows) == 1
        assert rows[0].path == "/r/tmp/a"


class TestTopNodesRows:
    def test_returns_top_files(self) -> None:
        app = _make_app()
        rows = app._top_nodes_rows(NodeKind.FILE)
        assert len(rows) > 0
        assert all(app.node_by_path[r.path].kind is NodeKind.FILE for r in rows)

    def test_returns_top_dirs(self) -> None:
        app = _make_app()
        rows = app._top_nodes_rows(NodeKind.DIRECTORY)
        assert len(rows) > 0


class TestFilteredRows:
    def test_no_filter_returns_all(self) -> None:
        app = _make_app()
        rows = app._overview_rows()
        filtered = app._filtered_rows("overview", rows)
        assert len(filtered) == len(rows)

    def test_needle_match(self) -> None:
        app = _make_app()
        app._views["overview"].filter_text = "a.txt"
        rows = app._overview_rows()
        filtered = app._filtered_rows("overview", rows)
        assert all("a.txt" in r.name.lower() or "a.txt" in r.path.lower() for r in filtered)

    def test_cache_hit(self) -> None:
        app = _make_app()
        rows = app._overview_rows()
        _ = app._filtered_rows("overview", rows)
        result = app._filtered_rows("overview", rows)
        assert result is app._views["overview"].filtered_cache.rows  # type: ignore[union-attr]


class TestInvalidateRows:
    def test_clears_caches(self) -> None:
        app = _make_app()
        vs = app._views["overview"]
        vs.rows_cache = [make_file("/r/x")]  # type: ignore[list-item]
        app._invalidate_rows("overview")
        assert vs.rows_cache is None
        assert vs.filtered_cache is None

    def test_resets_paged(self) -> None:
        app = _make_app()
        vs = app._views["temp"]
        assert vs.paged is not None
        vs.paged.page_index = 5
        app._invalidate_rows("temp")
        assert vs.paged is not None
        assert vs.paged.page_index == 0


class TestBuildAllPagedRows:
    def test_temp_view(self) -> None:
        insights = [
            Insight("/r/tmp/a", 100, InsightCategory.TEMP, "tmp", disk_usage=100),
            Insight("/r/.cache/b", 200, InsightCategory.CACHE, "cache", disk_usage=200),
            Insight("/r/nm", 300, InsightCategory.BUILD_ARTIFACT, "nm", disk_usage=300),
        ]
        by_cat = {
            InsightCategory.TEMP: CategoryStats(count=1, size_bytes=100, disk_usage=100, paths={"/r/tmp/a"}),
            InsightCategory.CACHE: CategoryStats(count=1, size_bytes=200, disk_usage=200, paths={"/r/.cache/b"}),
            InsightCategory.BUILD_ARTIFACT: CategoryStats(count=1, size_bytes=300, disk_usage=300, paths={"/r/nm"}),
        }
        bundle = InsightBundle(insights=insights, by_category=by_cat)
        app = _make_app(bundle=bundle)
        rows, total = app._build_all_paged_rows("temp")
        assert len(rows) == 3
        assert total == 3

    def test_large_dir_view(self) -> None:
        app = _make_app()
        rows, total = app._build_all_paged_rows("large_dir")
        assert total == max(0, app.stats.directories - 1)

    def test_large_file_view(self) -> None:
        app = _make_app()
        rows, total = app._build_all_paged_rows("large_file")
        assert total == app.stats.files


class TestTrimmedIndicator:
    def test_non_paged_returns_empty(self) -> None:
        app = _make_app()
        assert app._trimmed_indicator("overview") == ""

    def test_no_rows_returns_empty(self) -> None:
        app = _make_app()
        assert app._trimmed_indicator("temp") == ""

    def test_with_filter(self) -> None:
        app = _make_app()
        vs = app._views["temp"]
        assert vs.paged is not None
        vs.paged.all_rows = [make_file("/r/x")]  # type: ignore[list-item]
        vs.paged.total_items = 5
        vs.filter_text = "x"
        result = app._trimmed_indicator("temp")
        assert "filtered" in result

    def test_trimmed_total(self) -> None:
        app = _make_app()
        vs = app._views["temp"]
        assert vs.paged is not None
        vs.paged.all_rows = [make_file("/r/x")]  # type: ignore[list-item]
        vs.paged.total_items = 100
        result = app._trimmed_indicator("temp")
        assert "of" in result
        assert "100" in result

    def test_showing_all(self) -> None:
        app = _make_app()
        vs = app._views["temp"]
        assert vs.paged is not None
        rows_list = [make_file(f"/r/{i}") for i in range(5)]  # type: ignore[list-item]
        vs.paged.all_rows = rows_list  # type: ignore[assignment]
        vs.paged.total_items = 5
        result = app._trimmed_indicator("temp")
        assert "5" in result
        assert "of" not in result


class TestFilteredPageCount:
    def test_no_rows_returns_one(self) -> None:
        app = _make_app()
        state = _PagedState()
        assert app._filtered_page_count("temp", state) == 1

    def test_page_count(self) -> None:
        app = _make_app()
        state = _PagedState()
        state.all_rows = [make_file(f"/r/{i}") for i in range(250)]  # type: ignore[list-item]
        count = app._filtered_page_count("temp", state)
        assert count == 5


class TestCategorySizeAndDiskUsage:
    def test_category_size_bytes(self) -> None:
        from dux.ui.views import _category_bytes

        by_cat = {
            InsightCategory.TEMP: CategoryStats(size_bytes=100),
            InsightCategory.CACHE: CategoryStats(size_bytes=200),
        }
        sz, _du = _category_bytes(by_cat, InsightCategory.TEMP)
        assert sz == 100

    def test_category_disk_usage(self) -> None:
        from dux.ui.views import _category_bytes

        by_cat = {
            InsightCategory.TEMP: CategoryStats(disk_usage=50),
            InsightCategory.CACHE: CategoryStats(disk_usage=150),
        }
        _sz, du = _category_bytes(by_cat, InsightCategory.CACHE)
        assert du == 150

    def test_missing_category_returns_zero(self) -> None:
        from dux.ui.views import _category_bytes

        by_cat: dict[InsightCategory, CategoryStats] = {}
        sz, du = _category_bytes(by_cat, InsightCategory.TEMP)
        assert sz == 0
        assert du == 0
