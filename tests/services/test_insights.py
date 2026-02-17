from __future__ import annotations

from dux.config.defaults import default_config
from dux.models.enums import InsightCategory
from dux.models.scan import ScanNode
from dux.services.insights import generate_insights
from tests.factories import make_dir, make_file


def _tree_with(*children: ScanNode) -> ScanNode:
    return make_dir("/root", du=0, children=list(children))


def test_temp_analyzer_path_matching_and_threshold_logic() -> None:
    config = default_config()
    node = make_file("/root/tmp/trace.log", du=2 * 1024 * 1024)
    bundle = generate_insights(_tree_with(node), config)

    assert any(item.category is InsightCategory.TEMP for item in bundle.insights)


def test_cache_analyzer_path_matching_and_threshold_logic() -> None:
    config = default_config()
    node = make_dir("/root/.cache/pip", du=3 * 1024 * 1024)
    bundle = generate_insights(_tree_with(node), config)

    assert any(item.category is InsightCategory.CACHE for item in bundle.insights)


def test_build_artifact_detection() -> None:
    config = default_config()
    node = make_dir(
        "/root/project/node_modules",
        du=2 * 1024 * 1024,
        children=[make_file("/root/project/node_modules/a.js", du=100)],
    )
    bundle = generate_insights(_tree_with(node), config)

    assert any(item.category is InsightCategory.BUILD_ARTIFACT for item in bundle.insights)


def test_dedup_by_path() -> None:
    config = default_config()
    node = make_dir("/root/__pycache__", du=100)
    bundle = generate_insights(_tree_with(node), config)

    matched = [item for item in bundle.insights if item.path == "/root/__pycache__"]
    assert len(matched) == 1


def test_temp_and_cache_insights_generated() -> None:
    config = default_config()
    temp = make_dir("/root/tmp/cache", du=100)
    cache = make_dir("/root/.cache/pip", du=200)
    bundle = generate_insights(_tree_with(temp, cache), config)

    categories = {item.category for item in bundle.insights}
    assert InsightCategory.TEMP in categories
    assert InsightCategory.CACHE in categories


def test_case_insensitive_matching() -> None:
    config = default_config()
    node = make_file("/root/project/.DS_STORE", du=4096)
    bundle = generate_insights(_tree_with(node), config)

    assert any(item.category is InsightCategory.TEMP for item in bundle.insights)


def test_case_insensitive_extension_matching() -> None:
    config = default_config()
    node = make_file("/root/app/debug.LOG", du=1024)
    bundle = generate_insights(_tree_with(node), config)

    assert any(item.category is InsightCategory.TEMP for item in bundle.insights)


def test_case_insensitive_directory_matching() -> None:
    config = default_config()
    node = make_dir(
        "/root/project/Node_Modules",
        du=2 * 1024 * 1024,
        children=[make_file("/root/project/Node_Modules/a.js", du=100)],
    )
    bundle = generate_insights(_tree_with(node), config)

    assert any(item.category is InsightCategory.BUILD_ARTIFACT for item in bundle.insights)
