from __future__ import annotations

import pytest

from dux.config.schema import AppConfig
from dux.models.enums import InsightCategory, NodeKind
from dux.models.insight import CategoryStats, Insight, InsightBundle
from dux.models.scan import ScanNode, ScanStats
from dux.services.tree import LEAF_CHILDREN, finalize_sizes
from dux.ui.app import DuxApp


def _dir(path: str, name: str, children: list[ScanNode] | None = None, du: int = 0) -> ScanNode:
    return ScanNode(
        path=path, name=name, kind=NodeKind.DIRECTORY, size_bytes=du, disk_usage=du, children=children or []
    )


def _file(path: str, name: str, du: int = 0) -> ScanNode:
    return ScanNode(path=path, name=name, kind=NodeKind.FILE, size_bytes=du, disk_usage=du, children=LEAF_CHILDREN)


def _make_app(apparent_size: bool = False) -> DuxApp:
    f1 = _file("/r/a.txt", "a.txt", du=100)
    f2 = _file("/r/b.txt", "b.txt", du=200)
    sub_f = _file("/r/sub/c.txt", "c.txt", du=50)
    sub = _dir("/r/sub", "sub", [sub_f], du=50)
    root = _dir("/r", "root", [f1, f2, sub], du=350)
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
