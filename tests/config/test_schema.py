from __future__ import annotations

from dux.config.schema import AppConfig, PatternRule
from dux.models.enums import ApplyTo, InsightCategory


class TestToDict:
    def test_keys_present(self) -> None:
        cfg = AppConfig()
        d = cfg.to_dict()
        expected_keys = {
            "additionalPaths",
            "maxDepth",
            "scanWorkers",
            "topCount",
            "pageSize",
            "maxInsightsPerCategory",
            "overviewTopDirs",
            "scrollStep",
            "patterns",
        }
        assert set(d.keys()) == expected_keys

    def test_max_depth_none(self) -> None:
        cfg = AppConfig(max_depth=None)
        assert cfg.to_dict()["maxDepth"] is None

    def test_max_depth_int(self) -> None:
        cfg = AppConfig(max_depth=5)
        assert cfg.to_dict()["maxDepth"] == 5


class TestRuleToDict:
    def test_dict_structure(self) -> None:
        rule = PatternRule(
            name="test",
            pattern="**/*.log",
            category=InsightCategory.TEMP,
            apply_to=ApplyTo.FILE,
            stop_recursion=True,
        )
        d = rule.to_dict()
        assert d["name"] == "test"
        assert d["pattern"] == "**/*.log"
        assert d["category"] == "temp"
        assert d["applyTo"] == "file"
        assert d["stopRecursion"] is True

    def test_apply_to_both(self) -> None:
        rule = PatternRule("r", "p", InsightCategory.CACHE, apply_to=ApplyTo.BOTH)
        assert rule.to_dict()["applyTo"] == "both"

    def test_apply_to_dir(self) -> None:
        rule = PatternRule("r", "p", InsightCategory.CACHE, apply_to=ApplyTo.DIR)
        assert rule.to_dict()["applyTo"] == "dir"


class TestApplyToFromStr:
    def test_file(self) -> None:
        assert ApplyTo.from_str("file") == ApplyTo.FILE

    def test_dir(self) -> None:
        assert ApplyTo.from_str("dir") == ApplyTo.DIR

    def test_both(self) -> None:
        assert ApplyTo.from_str("both") == ApplyTo.BOTH

    def test_unknown_fallback(self) -> None:
        assert ApplyTo.from_str("unknown") == ApplyTo.BOTH

    def test_non_string_fallback(self) -> None:
        assert ApplyTo.from_str(42) == ApplyTo.BOTH


class TestRuleFromDict:
    def test_full_payload(self) -> None:
        payload = {
            "name": "test",
            "pattern": "**/*.log",
            "category": "temp",
            "applyTo": "file",
            "stopRecursion": True,
        }
        rule = PatternRule.from_dict(payload)
        assert rule.name == "test"
        assert rule.pattern == "**/*.log"
        assert rule.category is InsightCategory.TEMP
        assert rule.apply_to == ApplyTo.FILE
        assert rule.stop_recursion is True

    def test_without_optional_keys(self) -> None:
        payload = {"name": "test", "pattern": "**/*.log", "category": "cache"}
        rule = PatternRule.from_dict(payload)
        assert rule.apply_to == ApplyTo.BOTH
        assert rule.stop_recursion is False


class TestFromDict:
    def test_max_depth_none(self) -> None:
        defaults = AppConfig()
        result = AppConfig.from_dict({"maxDepth": None}, defaults)
        assert result.max_depth is None

    def test_max_depth_present(self) -> None:
        defaults = AppConfig()
        result = AppConfig.from_dict({"maxDepth": 3}, defaults)
        assert result.max_depth == 3

    def test_numeric_clamping_scan_workers(self) -> None:
        defaults = AppConfig()
        result = AppConfig.from_dict({"scanWorkers": 0}, defaults)
        assert result.scan_workers == 1

    def test_numeric_clamping_page_size(self) -> None:
        defaults = AppConfig()
        result = AppConfig.from_dict({"pageSize": 1}, defaults)
        assert result.page_size == 10

    def test_numeric_clamping_max_insights(self) -> None:
        defaults = AppConfig()
        result = AppConfig.from_dict({"maxInsightsPerCategory": 1}, defaults)
        assert result.max_insights_per_category == 10

    def test_numeric_clamping_overview_top_dirs(self) -> None:
        defaults = AppConfig()
        result = AppConfig.from_dict({"overviewTopDirs": 1}, defaults)
        assert result.overview_top_dirs == 5

    def test_numeric_clamping_scroll_step(self) -> None:
        defaults = AppConfig()
        result = AppConfig.from_dict({"scrollStep": 0}, defaults)
        assert result.scroll_step == 1

    def test_patterns_present(self) -> None:
        payload = {
            "patterns": [{"name": "t", "pattern": "**/t", "category": "temp"}],
        }
        result = AppConfig.from_dict(payload, AppConfig())
        assert len(result.patterns) == 1
        assert result.patterns[0].name == "t"

    def test_patterns_absent_uses_defaults(self) -> None:
        defaults = AppConfig(
            patterns=[PatternRule("d", "**/*.d", InsightCategory.TEMP)],
        )
        result = AppConfig.from_dict({}, defaults)
        assert len(result.patterns) == 1
        assert result.patterns[0].name == "d"
