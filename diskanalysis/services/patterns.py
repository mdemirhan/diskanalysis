from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from functools import lru_cache
from typing import Literal

from diskanalysis.config.schema import PatternRule

# Matcher kinds — integers for fast dispatch in the hot loop.
_CONTAINS = 0  # "/segment/" in path  (for **/segment/**)
_ENDSWITH = 1  # basename.endswith(v) (for **/*.ext)
_STARTSWITH = 2  # basename.startswith(v) (for **/prefix*)
_EXACT = 3  # basename == v         (for **/name)
_GLOB = 4  # fallback to fnmatch


@dataclass(slots=True, frozen=True)
class _Matcher:
    kind: int
    value: str
    alt: str  # _CONTAINS only: endswith variant without trailing /


def _has_glob_chars(s: str) -> bool:
    return "*" in s or "?" in s or "[" in s


def _classify(pattern: str) -> _Matcher:
    """Turn one expanded pattern into a fast string matcher."""
    if not pattern.startswith("**/"):
        return _Matcher(_GLOB, pattern, "")

    rest = pattern[3:]

    # **/segment/** or **/path/to/thing/**  →  contains check on path
    if rest.endswith("/**"):
        middle = rest[:-3]
        if not _has_glob_chars(middle):
            return _Matcher(_CONTAINS, f"/{middle}/", f"/{middle}")
        return _Matcher(_GLOB, pattern, "")

    # **/*.ext  →  endswith check on basename
    if rest.startswith("*") and not _has_glob_chars(rest[1:]):
        return _Matcher(_ENDSWITH, rest[1:], "")

    # **/prefix*  →  startswith check on basename
    if rest.endswith("*") and not _has_glob_chars(rest[:-1]):
        return _Matcher(_STARTSWITH, rest[:-1], "")

    # **/exact  →  exact basename match
    if not _has_glob_chars(rest):
        return _Matcher(_EXACT, rest, "")

    return _Matcher(_GLOB, pattern, "")


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


@dataclass(slots=True, frozen=True)
class CompiledRule:
    rule: PatternRule
    matchers: tuple[_Matcher, ...]
    apply_to: Literal["file", "dir", "both"]


def compile_rule(rule: PatternRule) -> CompiledRule:
    expanded = _expand_braces(rule.pattern)
    matchers = tuple(_classify(p) for p in expanded)
    return CompiledRule(rule=rule, matchers=matchers, apply_to=rule.apply_to)


def compile_rules(rules: list[PatternRule]) -> list[CompiledRule]:
    return [compile_rule(r) for r in rules]


def compiled_matches(cr: CompiledRule, path: str, basename: str, is_dir: bool) -> bool:
    if cr.apply_to == "file" and is_dir:
        return False
    if cr.apply_to == "dir" and not is_dir:
        return False

    for m in cr.matchers:
        kind = m.kind
        if kind == _CONTAINS:
            if m.value in path or path.endswith(m.alt):
                return True
        elif kind == _ENDSWITH:
            if basename.endswith(m.value):
                return True
        elif kind == _STARTSWITH:
            if basename.startswith(m.value):
                return True
        elif kind == _EXACT:
            if basename == m.value:
                return True
        else:  # _GLOB fallback
            if _match_pattern_slow(m.value, path, basename):
                return True
    return False


def _match_pattern_slow(pattern: str, normalized_path: str, basename: str) -> bool:
    """Fallback for patterns that can't be classified into simple string ops."""
    if pattern.endswith("/**"):
        base_pattern = pattern[: -len("/**")]
        if fnmatch(normalized_path, base_pattern):
            return True
    if fnmatch(normalized_path, pattern):
        return True
    return fnmatch(basename, pattern)
