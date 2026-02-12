from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from diskanalysis.models.enums import InsightCategory, Severity


@dataclass(slots=True)
class Thresholds:
    large_file_mb: int = 512
    large_dir_mb: int = 2048
    old_file_days: int = 365
    min_insight_mb: int = 50

    @property
    def large_file_bytes(self) -> int:
        return self.large_file_mb * 1024 * 1024

    @property
    def large_dir_bytes(self) -> int:
        return self.large_dir_mb * 1024 * 1024

    @property
    def old_file_seconds(self) -> int:
        return self.old_file_days * 24 * 60 * 60

    @property
    def min_insight_bytes(self) -> int:
        return self.min_insight_mb * 1024 * 1024


@dataclass(slots=True)
class PatternRule:
    name: str
    pattern: str
    category: InsightCategory
    safe_to_delete: bool
    recommendation: str
    severity: Severity = Severity.MEDIUM
    apply_to: str = "both"
    stop_recursion: bool = False


@dataclass(slots=True)
class AppConfig:
    thresholds: Thresholds = field(default_factory=Thresholds)
    exclude_paths: list[str] = field(default_factory=list)
    additional_temp_paths: list[str] = field(default_factory=list)
    additional_cache_paths: list[str] = field(default_factory=list)
    temp_patterns: list[PatternRule] = field(default_factory=list)
    cache_patterns: list[PatternRule] = field(default_factory=list)
    build_artifact_patterns: list[PatternRule] = field(default_factory=list)
    custom_patterns: list[PatternRule] = field(default_factory=list)
    follow_symlinks: bool = False
    max_depth: int | None = None
    scan_workers: int = 4
    top_n: int = 15

    def to_dict(self) -> dict[str, Any]:
        return {
            "thresholds": {
                "largeFileMb": self.thresholds.large_file_mb,
                "largeDirMb": self.thresholds.large_dir_mb,
                "oldFileDays": self.thresholds.old_file_days,
                "minInsightMb": self.thresholds.min_insight_mb,
            },
            "excludePaths": self.exclude_paths,
            "additionalTempPaths": self.additional_temp_paths,
            "additionalCachePaths": self.additional_cache_paths,
            "followSymlinks": self.follow_symlinks,
            "maxDepth": self.max_depth,
            "scanWorkers": self.scan_workers,
            "topN": self.top_n,
            "tempPatterns": [_rule_to_dict(rule) for rule in self.temp_patterns],
            "cachePatterns": [_rule_to_dict(rule) for rule in self.cache_patterns],
            "buildArtifactPatterns": [_rule_to_dict(rule) for rule in self.build_artifact_patterns],
            "customPatterns": [_rule_to_dict(rule) for rule in self.custom_patterns],
        }



def _rule_to_dict(rule: PatternRule) -> dict[str, Any]:
    return {
        "name": rule.name,
        "pattern": rule.pattern,
        "category": rule.category.value,
        "safeToDelete": rule.safe_to_delete,
        "recommendation": rule.recommendation,
        "severity": rule.severity.value,
        "applyTo": rule.apply_to,
        "stopRecursion": rule.stop_recursion,
    }


def _rule_from_dict(payload: dict[str, Any]) -> PatternRule:
    return PatternRule(
        name=str(payload["name"]),
        pattern=str(payload["pattern"]),
        category=InsightCategory(str(payload["category"])),
        safe_to_delete=bool(payload.get("safeToDelete", False)),
        recommendation=str(payload.get("recommendation", "Review before deleting.")),
        severity=Severity(str(payload.get("severity", Severity.MEDIUM.value))),
        apply_to=str(payload.get("applyTo", "both")),
        stop_recursion=bool(payload.get("stopRecursion", False)),
    )


def from_dict(data: dict[str, Any], defaults: AppConfig) -> AppConfig:
    thresholds = data.get("thresholds", {})
    threshold_obj = Thresholds(
        large_file_mb=int(thresholds.get("largeFileMb", defaults.thresholds.large_file_mb)),
        large_dir_mb=int(thresholds.get("largeDirMb", defaults.thresholds.large_dir_mb)),
        old_file_days=int(thresholds.get("oldFileDays", defaults.thresholds.old_file_days)),
        min_insight_mb=int(thresholds.get("minInsightMb", defaults.thresholds.min_insight_mb)),
    )

    cfg = AppConfig(
        thresholds=threshold_obj,
        exclude_paths=[str(x) for x in data.get("excludePaths", defaults.exclude_paths)],
        additional_temp_paths=[str(x) for x in data.get("additionalTempPaths", defaults.additional_temp_paths)],
        additional_cache_paths=[str(x) for x in data.get("additionalCachePaths", defaults.additional_cache_paths)],
        follow_symlinks=bool(data.get("followSymlinks", defaults.follow_symlinks)),
        max_depth=data.get("maxDepth", defaults.max_depth),
        scan_workers=max(1, int(data.get("scanWorkers", defaults.scan_workers))),
        top_n=max(1, int(data.get("topN", defaults.top_n))),
        temp_patterns=[_rule_from_dict(x) for x in data.get("tempPatterns", [_rule_to_dict(r) for r in defaults.temp_patterns])],
        cache_patterns=[_rule_from_dict(x) for x in data.get("cachePatterns", [_rule_to_dict(r) for r in defaults.cache_patterns])],
        build_artifact_patterns=[
            _rule_from_dict(x) for x in data.get("buildArtifactPatterns", [_rule_to_dict(r) for r in defaults.build_artifact_patterns])
        ],
        custom_patterns=[_rule_from_dict(x) for x in data.get("customPatterns", [_rule_to_dict(r) for r in defaults.custom_patterns])],
    )
    if cfg.max_depth is not None:
        cfg.max_depth = int(cfg.max_depth)
    return cfg
