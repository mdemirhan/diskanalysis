from __future__ import annotations

import time

from diskanalysis.config.defaults import default_config
from diskanalysis.config.schema import PatternRule, Thresholds
from diskanalysis.models.enums import InsightCategory, NodeKind, Severity
from diskanalysis.models.scan import ScanNode
from diskanalysis.services.insights import generate_insights


def _tree_with(*children: ScanNode) -> ScanNode:
    total = sum(child.size_bytes for child in children)
    return ScanNode(
        path="/root",
        name="root",
        kind=NodeKind.DIRECTORY,
        size_bytes=total,
        modified_ts=time.time(),
        children=list(children),
    )


def _file(path: str, size: int, modified: float | None = None) -> ScanNode:
    return ScanNode(
        path=path,
        name=path.rsplit("/", 1)[-1],
        kind=NodeKind.FILE,
        size_bytes=size,
        modified_ts=modified or time.time(),
        children=[],
    )


def _dir(path: str, size: int, *children: ScanNode) -> ScanNode:
    return ScanNode(
        path=path,
        name=path.rsplit("/", 1)[-1],
        kind=NodeKind.DIRECTORY,
        size_bytes=size,
        modified_ts=time.time(),
        children=list(children),
    )


def test_temp_analyzer_path_matching_and_threshold_logic() -> None:
    config = default_config()
    config.thresholds = Thresholds(min_insight_mb=1)
    node = _file("/root/tmp/trace.log", size=2 * 1024 * 1024)
    bundle = generate_insights(_tree_with(node), config)

    assert any(item.category is InsightCategory.TEMP for item in bundle.insights)


def test_cache_analyzer_path_matching_and_threshold_logic() -> None:
    config = default_config()
    config.thresholds = Thresholds(min_insight_mb=1)
    node = _dir("/root/.cache/pip", size=3 * 1024 * 1024)
    bundle = generate_insights(_tree_with(node), config)

    assert any(item.category is InsightCategory.CACHE for item in bundle.insights)


def test_large_file_detection() -> None:
    config = default_config()
    config.thresholds = Thresholds(large_file_mb=1, large_dir_mb=2048, old_file_days=365, min_insight_mb=0)
    node = _file("/root/huge.dump", size=2 * 1024 * 1024)
    bundle = generate_insights(_tree_with(node), config)

    assert any(item.category is InsightCategory.LARGE_FILE for item in bundle.insights)


def test_build_artifact_detection() -> None:
    config = default_config()
    config.thresholds = Thresholds(min_insight_mb=1)
    node = _dir("/root/project/node_modules", 2 * 1024 * 1024, _file("/root/project/node_modules/a.js", 100))
    bundle = generate_insights(_tree_with(node), config)

    assert any(item.category is InsightCategory.BUILD_ARTIFACT for item in bundle.insights)


def test_dedup_by_path() -> None:
    config = default_config()
    config.thresholds = Thresholds(min_insight_mb=0)
    node = _dir("/root/__pycache__", size=100)
    bundle = generate_insights(_tree_with(node), config)

    matched = [item for item in bundle.insights if item.path == "/root/__pycache__"]
    assert len(matched) == 1


def test_reclaimable_space_calculation() -> None:
    config = default_config()
    config.thresholds = Thresholds(min_insight_mb=0)
    temp = _dir("/root/tmp/cache", size=100)
    cache = _dir("/root/.cache/pip", size=200)
    bundle = generate_insights(_tree_with(temp, cache), config)

    assert bundle.reclaimable_bytes >= 300
    assert bundle.safe_reclaimable_bytes > 0


def test_old_file_detection() -> None:
    config = default_config()
    config.thresholds = Thresholds(large_file_mb=1024, large_dir_mb=2048, old_file_days=10, min_insight_mb=0)
    old_ts = time.time() - (20 * 24 * 60 * 60)
    node = _file("/root/old.txt", size=100, modified=old_ts)
    bundle = generate_insights(_tree_with(node), config)

    assert any(item.category is InsightCategory.OLD_FILE for item in bundle.insights)


def test_custom_pattern_detection() -> None:
    config = default_config()
    config.thresholds = Thresholds(min_insight_mb=0)
    config.custom_patterns = [
        PatternRule(
            name="ISO",
            pattern="**/*.iso",
            category=InsightCategory.CUSTOM,
            safe_to_delete=False,
            recommendation="Review archives",
            severity=Severity.LOW,
            apply_to="file",
            stop_recursion=False,
        )
    ]
    node = _file("/root/images/archive.iso", size=1024)
    bundle = generate_insights(_tree_with(node), config)

    assert any(item.category is InsightCategory.CUSTOM for item in bundle.insights)
