from __future__ import annotations

import time
from pathlib import Path

from diskanalysis.config.schema import AppConfig, PatternRule
from diskanalysis.models.enums import InsightCategory, Severity
from diskanalysis.models.insight import Insight, InsightBundle
from diskanalysis.models.scan import ScanNode, norm_sep
from diskanalysis.services.patterns import matches_rule


_SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
}


def _find_rule(rules: list[PatternRule], node: ScanNode) -> PatternRule | None:
    normalized = norm_sep(node.path)
    for rule in rules:
        if matches_rule(rule, normalized, node.name, node.is_dir):
            return rule
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


def _insight_from_rule(node: ScanNode, rule: PatternRule) -> Insight:
    return Insight(
        path=node.path,
        size_bytes=node.size_bytes,
        category=rule.category,
        severity=rule.severity,
        safe_to_delete=rule.safe_to_delete,
        summary=rule.name,
        recommendation=rule.recommendation,
        modified_ts=node.modified_ts,
    )


def generate_insights(root: ScanNode, config: AppConfig) -> InsightBundle:
    insights: dict[str, Insight] = {}
    now = time.time()

    additional_rules: list[tuple[str, PatternRule]] = []
    for category, sources in (
        (InsightCategory.TEMP, config.additional_temp_paths),
        (InsightCategory.CACHE, config.additional_cache_paths),
    ):
        for raw_base in sources:
            base = norm_sep(str(Path(raw_base).expanduser())).rstrip("/")
            additional_rules.append(
                (
                    base,
                    PatternRule(
                        name=f"Additional {category.value} path",
                        pattern=base,
                        category=category,
                        safe_to_delete=category is InsightCategory.TEMP,
                        recommendation="Review configured path and clean safely.",
                        severity=Severity.MEDIUM,
                        apply_to="both",
                        stop_recursion=False,
                    ),
                )
            )

    def _check_additional(
        node_path: str, category: InsightCategory
    ) -> PatternRule | None:
        normalized = norm_sep(node_path).rstrip("/")
        for base, rule in additional_rules:
            if rule.category is not category:
                continue
            if normalized == base or normalized.startswith(f"{base}/"):
                return rule
        return None

    stack: list[tuple[ScanNode, bool]] = [(root, False)]
    while stack:
        node, in_temp_or_cache = stack.pop()

        temp_rule = _find_rule(config.temp_patterns, node) or _check_additional(
            node.path, InsightCategory.TEMP
        )
        cache_rule = _find_rule(config.cache_patterns, node) or _check_additional(
            node.path, InsightCategory.CACHE
        )
        build_rule = _find_rule(config.build_artifact_patterns, node)
        custom_rule = _find_rule(config.custom_patterns, node)

        local_in_temp_cache = (
            in_temp_or_cache or temp_rule is not None or cache_rule is not None
        )

        if node.size_bytes >= config.thresholds.min_insight_bytes:
            for rule in (temp_rule, cache_rule, build_rule, custom_rule):
                if rule is not None:
                    _upsert(insights, _insight_from_rule(node, rule))

        if not local_in_temp_cache:
            if (
                not node.is_dir
                and node.size_bytes >= config.thresholds.large_file_bytes
            ):
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

            if (
                not node.is_dir
                and now - node.modified_ts >= config.thresholds.old_file_seconds
            ):
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
                continue
            for child in reversed(node.children):
                stack.append((child, local_in_temp_cache))

    ordered = sorted(insights.values(), key=lambda x: x.size_bytes, reverse=True)
    reclaimable = sum(item.size_bytes for item in ordered)
    safe_reclaimable = sum(item.size_bytes for item in ordered if item.safe_to_delete)
    return InsightBundle(
        insights=ordered,
        reclaimable_bytes=reclaimable,
        safe_reclaimable_bytes=safe_reclaimable,
    )


def filter_insights(
    bundle: InsightBundle, categories: set[InsightCategory]
) -> list[Insight]:
    return [item for item in bundle.insights if item.category in categories]
