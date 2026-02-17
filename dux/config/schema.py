from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dux.models.enums import ApplyTo, InsightCategory


@dataclass(slots=True)
class PatternRule:
    name: str
    pattern: str
    category: InsightCategory
    apply_to: ApplyTo = ApplyTo.BOTH
    stop_recursion: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "pattern": self.pattern,
            "category": self.category.value,
            "applyTo": self.apply_to.to_str(),
            "stopRecursion": self.stop_recursion,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PatternRule:
        return cls(
            name=str(payload["name"]),
            pattern=str(payload["pattern"]),
            category=InsightCategory(str(payload["category"])),
            apply_to=ApplyTo.from_str(payload.get("applyTo", "both")),
            stop_recursion=bool(payload.get("stopRecursion", False)),
        )


@dataclass(slots=True)
class AppConfig:
    patterns: list[PatternRule] = field(default_factory=list)
    additional_paths: dict[InsightCategory, list[str]] = field(default_factory=dict)
    max_depth: int | None = None
    scan_workers: int = 4
    top_count: int = 15
    page_size: int = 100
    max_insights_per_category: int = 1000
    overview_top_dirs: int = 100
    scroll_step: int = 10

    def to_dict(self) -> dict[str, Any]:
        additional: dict[str, list[str]] = {cat.value: paths for cat, paths in self.additional_paths.items()}
        return {
            "additionalPaths": additional,
            "maxDepth": self.max_depth,
            "scanWorkers": self.scan_workers,
            "topCount": self.top_count,
            "pageSize": self.page_size,
            "maxInsightsPerCategory": self.max_insights_per_category,
            "overviewTopDirs": self.overview_top_dirs,
            "scrollStep": self.scroll_step,
            "patterns": [rule.to_dict() for rule in self.patterns],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], defaults: AppConfig) -> AppConfig:
        max_depth_raw = data.get("maxDepth", defaults.max_depth)

        # Parse additional paths
        additional_raw = data.get("additionalPaths")
        if additional_raw is not None:
            additional_paths = {InsightCategory(cat): [str(p) for p in paths] for cat, paths in additional_raw.items()}
        else:
            additional_paths = {cat: list(paths) for cat, paths in defaults.additional_paths.items()}

        # Parse patterns
        patterns_raw = data.get("patterns")
        if patterns_raw is not None:
            patterns = [PatternRule.from_dict(x) for x in patterns_raw]
        else:
            patterns = list(defaults.patterns)

        return cls(
            patterns=patterns,
            additional_paths=additional_paths,
            max_depth=int(max_depth_raw) if max_depth_raw is not None else None,
            scan_workers=max(1, int(data.get("scanWorkers", defaults.scan_workers))),
            top_count=max(1, int(data.get("topCount", defaults.top_count))),
            page_size=max(10, int(data.get("pageSize", defaults.page_size))),
            max_insights_per_category=max(
                10,
                int(data.get("maxInsightsPerCategory", defaults.max_insights_per_category)),
            ),
            overview_top_dirs=max(5, int(data.get("overviewTopDirs", defaults.overview_top_dirs))),
            scroll_step=max(1, int(data.get("scrollStep", defaults.scroll_step))),
        )
