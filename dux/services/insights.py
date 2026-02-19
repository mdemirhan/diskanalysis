from __future__ import annotations

import heapq
from pathlib import Path

from dux.config.schema import AppConfig, PatternRule
from dux.models.enums import ApplyTo, InsightCategory
from dux.models.insight import CategoryStats, Insight, InsightBundle
from dux.models.scan import ScanNode
from dux.services.patterns import CompiledRuleSet, compile_ruleset, match_all

# Heap entry: (disk_usage, path, Insight).  Using disk usage as the key so the
# smallest item sits at the top of the min-heap for efficient eviction.
type _HeapEntry = tuple[int, str, Insight]


def _heap_push(
    heap: list[_HeapEntry],
    seen: dict[str, int],
    insight: Insight,
    max_size: int,
) -> None:
    """Push *insight* into a bounded min-heap, deduplicating by path.

    The ``seen`` dict tracks the highest disk_usage per path.  Stale entries
    (lower usage for the same path) may remain in the heap; they are filtered
    out during the final extraction phase in ``generate_insights``.
    """
    prev_usage = seen.get(insight.path)
    if prev_usage is not None:
        if insight.disk_usage <= prev_usage:
            return
    seen[insight.path] = insight.disk_usage
    entry: _HeapEntry = (insight.disk_usage, insight.path, insight)
    if len(heap) < max_size:
        heapq.heappush(heap, entry)
    elif insight.disk_usage > heap[0][0]:
        heapq.heapreplace(heap, entry)


def generate_insights(root: ScanNode, config: AppConfig) -> InsightBundle:
    """Walk the scan tree and produce an InsightBundle.

    Pipeline:
      1. Wrap ``additional_paths`` as synthetic PatternRule objects so they
         go through the same matching pipeline as glob patterns.
      2. Compile all rules into a CompiledRuleSet (fast hash/AC dispatch).
      3. DFS traversal: match each node, record insights into per-category
         bounded min-heaps (top-K by disk_usage) and unbounded aggregate
         counters (for overview totals in the TUI).
      4. Extract and deduplicate the heaps into a flat sorted list.
    """
    # --- build additional path rules ---
    # Bases are lowercased for case-insensitive matching, consistent with
    # the main glob/AC pipeline which compares against lpath.
    additional_paths: list[tuple[str, PatternRule]] = []
    for category, sources in config.additional_paths.items():
        for raw_base in sources:
            base = str(Path(raw_base).expanduser()).rstrip("/").lower()
            additional_paths.append(
                (
                    base,
                    PatternRule(
                        name=f"Additional {category.value} path",
                        pattern=base,
                        category=category,
                        apply_to=ApplyTo.BOTH,
                        stop_recursion=False,
                    ),
                )
            )

    # --- compile all rules into a single dispatch structure ---
    ruleset: CompiledRuleSet = compile_ruleset(
        config.patterns,
        additional_paths=additional_paths or None,
    )

    # --- per-category min-heaps (bounded: top-K for paginated TUI lists) ---
    heaps: dict[InsightCategory, list[_HeapEntry]] = {cat: [] for cat in InsightCategory}
    seen: dict[InsightCategory, dict[str, int]] = {cat: {} for cat in InsightCategory}

    # --- aggregate counters (unbounded: totals for overview/status bar) ---
    by_category: dict[InsightCategory, CategoryStats] = {cat: CategoryStats() for cat in InsightCategory}

    def _record(insight: Insight) -> None:
        # Update both: by_category sees every match (for accurate totals),
        # while the heap only keeps the top-K largest (for display).
        cs = by_category[insight.category]
        cs.count += 1
        cs.size_bytes += insight.size_bytes
        cs.disk_usage += insight.disk_usage
        cs.paths.add(insight.path)
        _heap_push(heaps[insight.category], seen[insight.category], insight, config.max_insights_per_category)

    # --- main traversal ---
    _TEMP = InsightCategory.TEMP
    _CACHE = InsightCategory.CACHE
    # Using .value strings because rule.category.value is compared below
    # (avoids repeated attribute access in the hot loop).
    _temp_cache = {_TEMP.value, _CACHE.value}

    # The traversal uses two pruning mechanisms:
    #   1. in_temp_or_cache — skips children of dirs already matched as TEMP
    #      or CACHE, because the parent's aggregate size already covers them.
    #   2. stop_recursion (via build_rule) — skips children of dirs like
    #      node_modules to avoid wasting time on uninteresting subtrees.
    stack: list[tuple[ScanNode, bool]] = [(root, False)]
    while stack:
        node, in_temp_or_cache = stack.pop()

        if in_temp_or_cache:
            continue

        path = node.path
        basename = node.name
        is_dir = node.is_dir

        # Lowercase once per entry for case-insensitive pattern matching.
        lpath = path.lower()
        lbase = basename.lower()

        # Single-pass match across all categories
        matched_rules = match_all(ruleset, lpath, lbase, is_dir)

        local_in_temp_cache = False
        build_rule: PatternRule | None = None
        for rule in matched_rules:
            _record(_insight_from_rule(node, rule))
            if rule.category.value in _temp_cache:
                local_in_temp_cache = True
            if rule.stop_recursion:
                build_rule = rule

        if is_dir:
            if build_rule is not None:
                continue
            # Reverse before pushing onto the LIFO stack so children are
            # visited in their original order (largest disk_usage first).
            for child in reversed(node.children):
                stack.append((child, local_in_temp_cache))

    # --- merge heaps into a single sorted list ---
    # Phase 2 of the lazy dedup strategy (see _heap_push): stale entries
    # (superseded by a higher-usage entry for the same path) may still be
    # in the heap.  Sort descending and skip paths already seen to keep
    # only the freshest.  Cross-category duplicates are kept intentionally
    # so that filter_insights (per-category view) stays consistent.
    all_insights: list[Insight] = []
    for cat in InsightCategory:
        cat_seen: set[str] = set()
        entries = sorted(heaps[cat], key=lambda e: e[0], reverse=True)
        for _, path, insight in entries:
            if path not in cat_seen:
                cat_seen.add(path)
                all_insights.append(insight)

    all_insights.sort(key=lambda x: x.disk_usage, reverse=True)

    return InsightBundle(
        insights=all_insights,
        by_category=by_category,
    )


def _insight_from_rule(node: ScanNode, rule: PatternRule) -> Insight:
    return Insight(
        path=node.path,
        size_bytes=node.size_bytes,
        category=rule.category,
        summary=rule.name,
        kind=node.kind,
        disk_usage=node.disk_usage,
    )


def filter_insights(bundle: InsightBundle, categories: set[InsightCategory]) -> list[Insight]:
    return [item for item in bundle.insights if item.category in categories]
