from __future__ import annotations

from dux.config.defaults import default_config
from dux.config.schema import AppConfig, PatternRule
from dux.models.enums import ApplyTo, InsightCategory
from dux.models.scan import ScanOptions
from dux.scan.python_scanner import PythonScanner
from dux.services.insights import generate_insights
from dux.services.tree import finalize_sizes
from tests.factories import make_dir, make_file
from tests.fs_mock import MemoryFileSystem


class TestFullPipeline:
    def test_scan_then_insights(self) -> None:
        fs = MemoryFileSystem()
        fs.add_dir("/project")
        fs.add_file("/project/src/main.py", size=100, disk_usage=100)
        fs.add_file("/project/tmp/trace.log", size=500, disk_usage=500)
        fs.add_file("/project/.cache/pip/some.whl", size=200, disk_usage=200)

        scanner = PythonScanner(workers=1, fs=fs)
        result = scanner.scan("/project", ScanOptions())
        snapshot = result.unwrap()
        config = default_config()
        bundle = generate_insights(snapshot.root, config)

        categories = {i.category for i in bundle.insights}
        assert InsightCategory.TEMP in categories or InsightCategory.CACHE in categories


class TestMixedCategories:
    def test_temp_cache_build_in_one_tree(self) -> None:
        tmp_file = make_file("/r/tmp/x.log", du=100)
        tmp_dir = make_dir("/r/tmp", du=100, children=[tmp_file])
        cache_file = make_file("/r/.cache/pip/a.whl", du=200)
        pip_dir = make_dir("/r/.cache/pip", du=200, children=[cache_file])
        cache_dir = make_dir("/r/.cache", du=200, children=[pip_dir])
        nm_file = make_file("/r/node_modules/pkg/index.js", du=50)
        pkg = make_dir("/r/node_modules/pkg", du=50, children=[nm_file])
        nm = make_dir("/r/node_modules", du=50, children=[pkg])
        root = make_dir("/r", du=350, children=[tmp_dir, cache_dir, nm])
        finalize_sizes(root)

        config = default_config()
        bundle = generate_insights(root, config)
        categories = {i.category for i in bundle.insights}
        assert InsightCategory.TEMP in categories
        assert InsightCategory.CACHE in categories
        assert InsightCategory.BUILD_ARTIFACT in categories


class TestCaseInsensitive:
    def test_mixed_case_paths_match(self) -> None:
        ds = make_file("/r/DIR/.DS_STORE", du=10)
        d = make_dir("/r/DIR", du=10, children=[ds])
        root = make_dir("/r", du=10, children=[d])
        finalize_sizes(root)
        config = default_config()
        bundle = generate_insights(root, config)
        matched = {i.path for i in bundle.insights}
        assert "/r/DIR/.DS_STORE" in matched


class TestAdditionalPaths:
    def test_additional_cache_path(self) -> None:
        cache_file = make_file("/home/.mycache/data", du=300)
        cache_dir = make_dir("/home/.mycache", du=300, children=[cache_file])
        root = make_dir("/home", du=300, children=[cache_dir])
        finalize_sizes(root)

        config = AppConfig(
            additional_paths={InsightCategory.CACHE: ["/home/.mycache"]},
            max_insights_per_category=100,
        )
        bundle = generate_insights(root, config)
        cache_paths = {i.path for i in bundle.insights if i.category is InsightCategory.CACHE}
        assert "/home/.mycache" in cache_paths


class TestStopRecursion:
    def test_node_modules_stops_descent(self) -> None:
        inner = make_file("/r/node_modules/pkg/a.js", du=10)
        pkg = make_dir("/r/node_modules/pkg", du=10, children=[inner])
        nm = make_dir("/r/node_modules", du=10, children=[pkg])
        root = make_dir("/r", du=10, children=[nm])
        finalize_sizes(root)

        config = default_config()
        bundle = generate_insights(root, config)
        matched = {i.path for i in bundle.insights}
        assert "/r/node_modules" in matched
        assert "/r/node_modules/pkg" not in matched
        assert "/r/node_modules/pkg/a.js" not in matched


class TestConfigRoundTrip:
    def test_default_to_dict_from_dict(self) -> None:
        original = default_config()
        d = original.to_dict()
        restored = AppConfig.from_dict(d, AppConfig())
        assert restored.scan_workers == original.scan_workers
        assert restored.top_count == original.top_count
        assert restored.page_size == original.page_size
        assert restored.max_depth == original.max_depth
        assert len(restored.patterns) == len(original.patterns)


class TestEmptyTree:
    def test_root_with_no_children(self) -> None:
        root = make_dir("/r", du=0)
        config = default_config()
        bundle = generate_insights(root, config)
        assert len(bundle.insights) == 0


class TestHeapEviction:
    def test_only_top_k_kept(self) -> None:
        children = [make_file(f"/r/tmp/f{i}.log", du=i * 10) for i in range(20)]
        tmp = make_dir("/r/tmp", du=sum(i * 10 for i in range(20)), children=children)
        root = make_dir("/r", du=tmp.disk_usage, children=[tmp])
        finalize_sizes(root)

        config = AppConfig(
            patterns=[PatternRule("logs", "**/*.log", InsightCategory.TEMP, apply_to=ApplyTo.FILE)],
            max_insights_per_category=5,
        )
        bundle = generate_insights(root, config)
        temp_insights = [i for i in bundle.insights if i.category is InsightCategory.TEMP]
        assert len(temp_insights) <= 5
        if temp_insights:
            min_kept = min(i.disk_usage for i in temp_insights)
            assert min_kept >= 100
