from __future__ import annotations

import threading

import pytest
from result import Err

from dux.config.schema import AppConfig, PatternRule
from dux.models.enums import ApplyTo, InsightCategory, NodeKind
from dux.models.insight import CategoryStats, Insight, InsightBundle
from dux.models.scan import ScanOptions, ScanStats
from dux.scan import Scanner
from dux.scan.python_scanner import PythonScanner
from dux.services.insights import generate_insights
from dux.services.tree import finalize_sizes
from dux.ui.app import DuxApp
from tests.factories import make_dir, make_file
from tests.fs_mock import MemoryFileSystem


class _BlockingScanner:
    def __init__(self, scanner: Scanner) -> None:
        self._scanner = scanner
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def scan(self, path, options, progress_callback=None, cancel_check=None):
        self.calls += 1
        self.entered.set()
        self.release.wait(timeout=2)
        return self._scanner.scan(path, options, progress_callback, cancel_check)


def _make_app(apparent_size: bool = False) -> DuxApp:
    f1 = make_file("/r/a.txt", du=100)
    f2 = make_file("/r/b.txt", du=200)
    sub_f = make_file("/r/sub/c.txt", du=50)
    sub = make_dir("/r/sub", du=50, children=[sub_f])
    root = make_dir("/r", du=350, children=[f1, f2, sub])
    finalize_sizes(root)
    stats = ScanStats(files=3, directories=2)
    insights = [
        Insight("/r/a.txt", 100, InsightCategory.TEMP, "tmp file", disk_usage=100),
        Insight("/r/sub", 50, InsightCategory.BUILD_ARTIFACT, "build", kind=NodeKind.DIRECTORY, disk_usage=50),
    ]
    by_cat = {
        InsightCategory.TEMP: CategoryStats(count=1, size_bytes=100, disk_usage=100, paths={"/r/a.txt"}),
        InsightCategory.CACHE: CategoryStats(),
        InsightCategory.BUILD_ARTIFACT: CategoryStats(count=1, size_bytes=50, disk_usage=50, paths={"/r/sub"}),
    }
    bundle = InsightBundle(insights=insights, by_category=by_cat)
    config = AppConfig(page_size=50, max_insights_per_category=100, overview_top_dirs=10, scroll_step=5)
    return DuxApp(root=root, stats=stats, bundle=bundle, config=config, apparent_size=apparent_size)


@pytest.mark.asyncio
async def test_app_mounts_and_renders() -> None:
    app = _make_app()
    async with app.run_test(size=(120, 40)):
        assert app.current_view == "overview"
        assert len(app.rows) > 0


@pytest.mark.asyncio
async def test_tab_switches_view() -> None:
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("tab")
        assert app.current_view == "browse"
        await pilot.press("tab")
        assert app.current_view == "large_dir"


@pytest.mark.asyncio
async def test_view_hotkeys() -> None:
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("b")
        assert app.current_view == "browse"
        await pilot.press("t")
        assert app.current_view == "temp"
        await pilot.press("d")
        assert app.current_view == "large_dir"
        await pilot.press("f")
        assert app.current_view == "large_file"
        await pilot.press("o")
        assert app.current_view == "overview"


@pytest.mark.asyncio
async def test_navigation_j_k() -> None:
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("j")
        assert app.selected_index == 1
        await pilot.press("k")
        assert app.selected_index == 0


@pytest.mark.asyncio
async def test_browse_expand_collapse() -> None:
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("b")
        assert app.current_view == "browse"
        # First row is root (expanded), navigate to sub dir
        sub_idx = None
        for i, row in enumerate(app.rows):
            if row.path == "/r/sub":
                sub_idx = i
                break
        assert sub_idx is not None
        for _ in range(sub_idx):
            await pilot.press("j")
        # Toggle expand
        await pilot.press("space")
        expanded = "/r/sub" in app.expanded
        # Toggle again
        await pilot.press("space")
        assert ("/r/sub" in app.expanded) != expanded


@pytest.mark.asyncio
async def test_help_overlay() -> None:
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("question_mark")
        # Help overlay should be visible
        assert app.screen.__class__.__name__ == "HelpOverlay"
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_apparent_size_mode() -> None:
    app = _make_app(apparent_size=True)
    async with app.run_test(size=(120, 40)):
        assert app._apparent_size is True
        assert len(app.rows) > 0


@pytest.mark.asyncio
async def test_temp_view_paging() -> None:
    """Test that paged views render correctly."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("t")
        assert app.current_view == "temp"
        assert len(app.rows) > 0


@pytest.mark.asyncio
async def test_shift_tab() -> None:
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        # Shift+tab should go to the previous view (last tab from overview)
        await pilot.press("shift+tab")
        assert app.current_view == "temp"


@pytest.mark.asyncio
async def test_g_g_goes_to_top() -> None:
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        # Move down first
        await pilot.press("j")
        await pilot.press("j")
        assert app.selected_index >= 1
        # gg goes to top
        await pilot.press("g")
        await pilot.press("g")
        assert app.selected_index == 0


@pytest.mark.asyncio
async def test_G_goes_to_bottom() -> None:
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("G")
        assert app.selected_index == len(app.rows) - 1


@pytest.mark.asyncio
async def test_browse_drill_in_out() -> None:
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("b")
        # Navigate to sub dir
        for i, row in enumerate(app.rows):
            if row.path == "/r/sub":
                for _ in range(i):
                    await pilot.press("j")
                break
        # Drill in with enter (expand first, then drill)
        await pilot.press("enter")
        await pilot.press("enter")
        assert app.browse_root_path == "/r/sub"
        # Drill out with backspace
        await pilot.press("backspace")
        assert app.browse_root_path == "/r"


@pytest.mark.asyncio
async def test_escape_clears_filter() -> None:
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        app._views["overview"].filter_text = "something"
        await pilot.press("escape")
        assert app._views["overview"].filter_text == ""


@pytest.mark.asyncio
async def test_large_dir_view() -> None:
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("d")
        assert app.current_view == "large_dir"
        assert len(app.rows) > 0


@pytest.mark.asyncio
async def test_large_file_view() -> None:
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("f")
        assert app.current_view == "large_file"
        assert len(app.rows) > 0


@pytest.mark.asyncio
async def test_browse_collapse_or_parent() -> None:
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("b")
        # Navigate to a file (should go to parent on h)
        for i, row in enumerate(app.rows):
            if row.path == "/r/a.txt":
                for _ in range(i):
                    await pilot.press("j")
                break
        old_idx = app.selected_index
        await pilot.press("h")
        # Should have navigated to parent
        assert app.selected_index <= old_idx


@pytest.mark.asyncio
async def test_resize_triggers_refresh() -> None:
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        # Just verifying it doesn't crash
        await pilot.resize_terminal(80, 30)
        assert len(app.rows) > 0


@pytest.mark.asyncio
async def test_browse_r_refreshes_subtree_and_all_derived_views() -> None:
    fs = (
        MemoryFileSystem()
        .add_dir("/r")
        .add_dir("/r/sub")
        .add_file("/r/sub/old.txt", size=10)
        .add_file("/r/sibling.txt", size=20)
    )
    scanner = PythonScanner(workers=1, fs=fs)
    scan_options = ScanOptions()
    scan_result = scanner.scan("/r", scan_options)
    assert not isinstance(scan_result, Err)
    snapshot = scan_result.unwrap()
    config = AppConfig(
        patterns=[
            PatternRule(
                name="temp extension",
                pattern="**/*.tmp",
                category=InsightCategory.TEMP,
                apply_to=ApplyTo.FILE,
            )
        ],
        page_size=50,
        max_insights_per_category=100,
        overview_top_dirs=10,
        scroll_step=5,
    )
    app = DuxApp(
        root=snapshot.root,
        stats=snapshot.stats,
        bundle=generate_insights(snapshot.root, config),
        config=config,
        scanner=scanner,
        scan_options=scan_options,
    )
    fs.remove("/r/sub/old.txt").add_file("/r/sub/new.tmp", size=40)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("b")
        sub_index = next(index for index, row in enumerate(app.rows) if row.path == "/r/sub")
        for _ in range(sub_index):
            await pilot.press("j")
        await pilot.press("space")
        await pilot.press("r")
        for _ in range(200):
            if not app._refreshing:
                break
            await pilot.pause(0.01)

        assert app._refreshing is False
        assert "/r/sub/old.txt" not in app.node_by_path
        assert app.node_by_path["/r/sub/new.tmp"].disk_usage == 40
        assert app.root.disk_usage == 60
        assert app.stats.files == 2
        assert any(item.path == "/r/sub/new.tmp" for item in app.bundle.insights)
        assert app.rows[app.selected_index].path == "/r/sub"
        assert any(row.path == "/r/sub/new.tmp" for row in app.rows)

        await pilot.press("t")
        assert any(row.path == "/r/sub/new.tmp" for row in app.rows)


@pytest.mark.asyncio
async def test_browse_ignores_duplicate_refresh_while_one_is_running() -> None:
    fs = MemoryFileSystem().add_dir("/r").add_dir("/r/sub").add_file("/r/sub/a.txt", size=10)
    scanner = PythonScanner(workers=1, fs=fs)
    scan_result = scanner.scan("/r", ScanOptions())
    assert not isinstance(scan_result, Err)
    snapshot = scan_result.unwrap()
    blocking_scanner = _BlockingScanner(scanner)
    config = AppConfig(page_size=50, max_insights_per_category=100, overview_top_dirs=10, scroll_step=5)
    app = DuxApp(
        root=snapshot.root,
        stats=snapshot.stats,
        bundle=generate_insights(snapshot.root, config),
        config=config,
        scanner=blocking_scanner,
    )

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("b")
        await pilot.press("r")
        for _ in range(100):
            if blocking_scanner.entered.is_set():
                break
            await pilot.pause(0.01)
        assert app._refresh_status == 'Refreshing "r".'
        app._advance_refresh_animation()
        assert app._refresh_status == 'Refreshing "r"..'
        app._advance_refresh_animation()
        assert app._refresh_status == 'Refreshing "r"...'
        app._advance_refresh_animation()
        assert app._refresh_status == 'Refreshing "r".'
        await pilot.press("r")
        assert blocking_scanner.calls == 1
        blocking_scanner.release.set()
        for _ in range(200):
            if not app._refreshing:
                break
            await pilot.pause(0.01)
        assert app._refreshing is False
