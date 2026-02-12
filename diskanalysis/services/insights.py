from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from diskanalysis.config.schema import AppConfig, PatternRule
from diskanalysis.models.enums import InsightCategory, Severity
from diskanalysis.models.insight import Insight, InsightBundle
from diskanalysis.models.scan import ScanNode, ScanSuccess
from diskanalysis.services.patterns import matches_rule


@dataclass(slots=True)
class _MatchState:
    in_temp_or_cache: bool


_SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
}


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def _find_rule(rules: list[PatternRule], node: ScanNode) -> PatternRule | None:
    normalized = _norm(node.path)
    for rule in rules:
        if matches_rule(rule, normalized, node.name, node.is_dir):
            return rule
    return None


def _is_under(path: str, base: str) -> bool:
    normalized_path = _norm(path).rstrip("/")
    normalized_base = _norm(base).rstrip("/")
    if normalized_path == normalized_base:
        return True
    return normalized_path.startswith(f"{normalized_base}/")


def _additional_path_rule(config: AppConfig, node: ScanNode, category: InsightCategory) -> PatternRule | None:
    sources = config.additional_temp_paths if category is InsightCategory.TEMP else config.additional_cache_paths
    for raw_base in sources:
        base = str(Path(raw_base).expanduser())
        if _is_under(node.path, base):
            return PatternRule(
                name=f"Additional {category.value} path",
                pattern=base,
                category=category,
                safe_to_delete=category is InsightCategory.TEMP,
                recommendation="Review configured path and clean safely.",
                severity=Severity.MEDIUM,
                apply_to="both",
                stop_recursion=False,
            )
    return None


def _upsert(target: dict[str, Insight], insight: Insight) -> None:
    existing = target.get(insight.path)
    if existing is None:
        target[insight.path] = insight
        return

    if insight.size_bytes > existing.size_bytes:
        target[insight.path] = insight
        return

    if _SEVERITY_RANK[insight.severity] > _SEVERITY_RANK[existing.severity]:
        target[insight.path] = insight


def generate_insights(scan: ScanSuccess, config: AppConfig) -> InsightBundle:
    insights: dict[str, Insight] = {}
    now = time.time()

    def walk(node: ScanNode, state: _MatchState) -> None:
        temp_rule = _find_rule(config.temp_patterns, node) or _additional_path_rule(config, node, InsightCategory.TEMP)
        cache_rule = _find_rule(config.cache_patterns, node) or _additional_path_rule(config, node, InsightCategory.CACHE)
        build_rule = _find_rule(config.build_artifact_patterns, node)
        custom_rule = _find_rule(config.custom_patterns, node)

        local_in_temp_cache = state.in_temp_or_cache or temp_rule is not None or cache_rule is not None

        if temp_rule is not None and node.size_bytes >= config.thresholds.min_insight_bytes:
            _upsert(
                insights,
                Insight(
                    path=node.path,
                    size_bytes=node.size_bytes,
                    category=temp_rule.category,
                    severity=temp_rule.severity,
                    safe_to_delete=temp_rule.safe_to_delete,
                    summary=temp_rule.name,
                    recommendation=temp_rule.recommendation,
                    modified_ts=node.modified_ts,
                ),
            )

        if cache_rule is not None and node.size_bytes >= config.thresholds.min_insight_bytes:
            _upsert(
                insights,
                Insight(
                    path=node.path,
                    size_bytes=node.size_bytes,
                    category=cache_rule.category,
                    severity=cache_rule.severity,
                    safe_to_delete=cache_rule.safe_to_delete,
                    summary=cache_rule.name,
                    recommendation=cache_rule.recommendation,
                    modified_ts=node.modified_ts,
                ),
            )

        if build_rule is not None and node.size_bytes >= config.thresholds.min_insight_bytes:
            _upsert(
                insights,
                Insight(
                    path=node.path,
                    size_bytes=node.size_bytes,
                    category=build_rule.category,
                    severity=build_rule.severity,
                    safe_to_delete=build_rule.safe_to_delete,
                    summary=build_rule.name,
                    recommendation=build_rule.recommendation,
                    modified_ts=node.modified_ts,
                ),
            )

        if custom_rule is not None and node.size_bytes >= config.thresholds.min_insight_bytes:
            _upsert(
                insights,
                Insight(
                    path=node.path,
                    size_bytes=node.size_bytes,
                    category=InsightCategory.CUSTOM,
                    severity=custom_rule.severity,
                    safe_to_delete=custom_rule.safe_to_delete,
                    summary=custom_rule.name,
                    recommendation=custom_rule.recommendation,
                    modified_ts=node.modified_ts,
                ),
            )

        if not local_in_temp_cache:
            if not node.is_dir and node.size_bytes >= config.thresholds.large_file_bytes:
                _upsert(
                    insights,
                    Insight(
                        path=node.path,
                        size_bytes=node.size_bytes,
                        category=InsightCategory.LARGE_FILE,
                        severity=Severity.MEDIUM,
                        safe_to_delete=False,
                        summary="Large file",
                        recommendation="Review whether this file is still needed.",
                        modified_ts=node.modified_ts,
                    ),
                )

            if node.is_dir and node.size_bytes >= config.thresholds.large_dir_bytes:
                _upsert(
                    insights,
                    Insight(
                        path=node.path,
                        size_bytes=node.size_bytes,
                        category=InsightCategory.LARGE_DIRECTORY,
                        severity=Severity.MEDIUM,
                        safe_to_delete=False,
                        summary="Large directory",
                        recommendation="Inspect directory contents for cleanup opportunities.",
                        modified_ts=node.modified_ts,
                    ),
                )

            if not node.is_dir and now - node.modified_ts >= config.thresholds.old_file_seconds:
                _upsert(
                    insights,
                    Insight(
                        path=node.path,
                        size_bytes=node.size_bytes,
                        category=InsightCategory.OLD_FILE,
                        severity=Severity.LOW,
                        safe_to_delete=False,
                        summary="Old file",
                        recommendation="Archive or remove if no longer needed.",
                        modified_ts=node.modified_ts,
                    ),
                )

        if node.is_dir:
            if build_rule is not None and build_rule.stop_recursion:
                return
            for child in node.children:
                walk(child, _MatchState(in_temp_or_cache=local_in_temp_cache))

    walk(scan.root, _MatchState(in_temp_or_cache=False))

    ordered = sorted(insights.values(), key=lambda x: x.size_bytes, reverse=True)
    reclaimable = sum(item.size_bytes for item in ordered)
    safe_reclaimable = sum(item.size_bytes for item in ordered if item.safe_to_delete)
    return InsightBundle(insights=ordered, reclaimable_bytes=reclaimable, safe_reclaimable_bytes=safe_reclaimable)


def filter_insights(bundle: InsightBundle, categories: set[InsightCategory]) -> list[Insight]:
    return [item for item in bundle.insights if item.category in categories]
