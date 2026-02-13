from __future__ import annotations

from fnmatch import fnmatch
from functools import lru_cache

from diskanalysis.config.schema import PatternRule


@lru_cache(maxsize=256)
def _expand_braces(pattern: str) -> tuple[str, ...]:
    start = pattern.find("{")
    end = pattern.find("}", start + 1)
    if start == -1 or end == -1:
        return (pattern,)
    choices = pattern[start + 1 : end].split(",")
    prefix = pattern[:start]
    suffix = pattern[end + 1 :]
    expanded: list[str] = []
    for choice in choices:
        expanded.extend(_expand_braces(f"{prefix}{choice}{suffix}"))
    return tuple(expanded)


def _match_pattern(pattern: str, normalized_path: str, basename: str) -> bool:
    if pattern.endswith("/**"):
        # Treat `.../**` as matching the directory itself and descendants.
        base_pattern = pattern[: -len("/**")]
        if fnmatch(normalized_path, base_pattern):
            return True
    if fnmatch(normalized_path, pattern):
        return True
    return fnmatch(basename, pattern)


def matches_rule(
    rule: PatternRule, normalized_path: str, basename: str, is_dir: bool
) -> bool:
    if rule.apply_to == "file" and is_dir:
        return False
    if rule.apply_to == "dir" and not is_dir:
        return False

    for pattern in _expand_braces(rule.pattern):
        if _match_pattern(pattern, normalized_path, basename):
            return True
    return False


def matches_glob(pattern: str, normalized_path: str, basename: str) -> bool:
    for item in _expand_braces(pattern):
        if _match_pattern(item, normalized_path, basename):
            return True
    return False
