# Pattern compilation and matching engine.
#
# Two-phase architecture:
#
#   PHASE 1 — COMPILE  (compile_ruleset, called once at startup)
#
#   Each PatternRule has a glob pattern like "**/node_modules/**".
#   Compilation turns these into a fast CompiledRuleSet:
#
#   1. Brace expansion — _expand_braces turns "**/*.{swp,bak}" into
#      two patterns: "**/*.swp" and "**/*.bak".
#
#   2. Classification — _classify assigns a matcher kind to each pattern:
#
#        Kind        Example            Fast operation
#        ----------  -----------------  ----------------------------------
#        EXACT       **/name            dict lookup on basename
#        CONTAINS    **/segment/**      Aho-Corasick on full path
#        ENDSWITH    **/*.ext           Aho-Corasick (end-only) on full path
#        STARTSWITH  **/prefix*         str.startswith on basename
#        GLOB        (anything else)    fnmatch fallback
#
#   3. Bucketing — patterns are split by apply_to (file/dir/both) at
#      compile time so the hot loop never branches on node kind.
#
#   4. Aho-Corasick automaton — CONTAINS and ENDSWITH patterns are merged
#      into a single AhoCorasick automaton per node kind (file/dir).
#      Each pattern becomes a (val, alt, rule) entry fed to _build_ac:
#
#        CONTAINS  "**/tmp/**"   -> val="/tmp/" (match anywhere),
#                                   alt="/tmp"  (end-of-path only).
#                                   The alt handles paths ending with the
#                                   segment itself, e.g. "/a/tmp".
#
#        ENDSWITH  "**/*.log"    -> val=""       (skipped),
#                                   alt=".log"  (end-of-path only).
#                                   Since lpath ends with the basename,
#                                   end_idx == len(lpath)-1 is equivalent
#                                   to basename.endswith(suffix).
#
#      _build_ac skips empty keys, so ENDSWITH entries produce only an
#      end-only key while CONTAINS entries produce both.
#
#   PHASE 2 — MATCH  (match_all, called once per node)
#
#   match_all receives a pre-lowercased path (lpath), basename (lbase),
#   and the CompiledRuleSet.  It checks each tier in order, returning at
#   most one rule per category (first match wins):
#
#     1. EXACT             — O(1) dict lookup on lbase.
#     2. CONTAINS+ENDSWITH — single ac.iter(lpath) call. Hits flagged
#                            end_only=True are accepted only when
#                            end_idx == len(lpath) - 1.
#     3. STARTSWITH        — linear scan of prefix rules against lbase.
#     4. GLOB              — fnmatch fallback.
#     5. Additional paths  — literal path prefix checks for user-configured
#                            directories (e.g. ~/.cache).

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch

from dux._matcher import AhoCorasick

from dux.config.schema import PatternRule
from dux.models.enums import ApplyTo

_FILE = ApplyTo.FILE
_DIR = ApplyTo.DIR

# Matcher kinds — integers for fast dispatch in the hot loop.
_CONTAINS = 0  # "/segment/" in path  (for **/segment/**)
_ENDSWITH = 1  # basename.endswith(v) (for **/*.ext)
_STARTSWITH = 2  # basename.startswith(v) (for **/prefix*)
_EXACT = 3  # basename == v         (for **/name)
_GLOB = 4  # fallback to fnmatch


@dataclass(slots=True, frozen=True)
class _Matcher:
    """Result of classifying one expanded glob pattern.

    For CONTAINS patterns like ``**/tmp/**``, the Aho-Corasick automaton needs
    two keys: ``value="/tmp/"`` matches anywhere in the path, and ``alt="/tmp"``
    matches only at the end (for paths like ``/a/tmp`` that lack a trailing ``/``).
    For ENDSWITH patterns like ``**/*.log``, ``value=""`` (skipped by _build_ac)
    and ``alt=".log"`` (end-of-path only).
    """

    kind: int
    value: str
    alt: str


def _has_glob_chars(s: str) -> bool:
    return "*" in s or "?" in s or "[" in s


def _classify(pattern: str) -> _Matcher:
    """Turn one expanded pattern into a fast string matcher.

    All matcher values are lowercased at compile time so that callers can pass
    pre-lowercased paths for case-insensitive matching with ~4% overhead.
    """
    if not pattern.startswith("**/"):
        return _Matcher(_GLOB, pattern.lower(), "")

    rest = pattern[3:]

    # **/segment/** or **/path/to/thing/**  →  contains check on path
    if rest.endswith("/**"):
        middle = rest[:-3]
        if not _has_glob_chars(middle):
            mid = middle.lower()
            return _Matcher(_CONTAINS, f"/{mid}/", f"/{mid}")
        return _Matcher(_GLOB, pattern.lower(), "")

    # **/*.ext  →  endswith check on basename
    if rest.startswith("*") and not _has_glob_chars(rest[1:]):
        return _Matcher(_ENDSWITH, rest[1:].lower(), "")

    # **/prefix*  →  startswith check on basename
    if rest.endswith("*") and not _has_glob_chars(rest[:-1]):
        return _Matcher(_STARTSWITH, rest[:-1].lower(), "")

    # **/exact  →  exact basename match
    if not _has_glob_chars(rest):
        return _Matcher(_EXACT, rest.lower(), "")

    return _Matcher(_GLOB, pattern.lower(), "")


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


def _match_pattern_slow(pattern: str, normalized_path: str, basename: str) -> bool:
    """Fallback for patterns that can't be classified into simple string ops."""
    if pattern.endswith("/**"):
        # A pattern like "foo/bar/**" should match "foo/bar" itself (the
        # directory), not just its descendants.  Try without the trailing "/**".
        base_pattern = pattern[: -len("/**")]
        if fnmatch(normalized_path, base_pattern):
            return True
    if fnmatch(normalized_path, pattern):
        return True
    return fnmatch(basename, pattern)


# ---------------------------------------------------------------------------
# CompiledRuleSet — single-pass, hash-based dispatch for all categories
# ---------------------------------------------------------------------------


def _build_ac(
    entries: list[tuple[str, str, PatternRule]],
) -> AhoCorasick | None:
    """Build an Aho-Corasick automaton from CONTAINS and ENDSWITH entries.

    Each entry is (val, alt, rule).  *val* is an any-position substring
    (empty for ENDSWITH-only entries); *alt* is an end-of-string-only suffix.
    The automaton value for each key is ``list[tuple[PatternRule, bool]]``
    where the bool means *end_only*.
    """
    if not entries:
        return None
    patterns: dict[str, list[tuple[PatternRule, bool]]] = {}
    for val, alt, rule in entries:
        if val:
            patterns.setdefault(val, []).append((rule, False))
        if alt:
            patterns.setdefault(alt, []).append((rule, True))
    ac = AhoCorasick()
    for key, value in patterns.items():
        ac.add_word(key, value)
    ac.make_automaton()
    return ac


@dataclass(slots=True)
class _ByKind:
    """All pattern rules for one node kind (file or dir), indexed by matcher kind."""

    exact: dict[str, list[PatternRule]] = field(default_factory=dict)
    ac: AhoCorasick | None = None
    startswith: list[tuple[str, PatternRule]] = field(default_factory=list)
    glob: list[tuple[str, PatternRule]] = field(default_factory=list)
    additional: list[tuple[str, PatternRule]] = field(default_factory=list)


@dataclass(slots=True)
class _ByKindBuilder:
    """Accumulates pattern entries for one node kind during compilation."""

    exact: dict[str, list[PatternRule]] = field(default_factory=dict)
    ac_entries: list[tuple[str, str, PatternRule]] = field(default_factory=list)
    startswith: list[tuple[str, PatternRule]] = field(default_factory=list)
    glob: list[tuple[str, PatternRule]] = field(default_factory=list)
    additional: list[tuple[str, PatternRule]] = field(default_factory=list)

    def add(self, m: _Matcher, rule: PatternRule) -> None:
        if m.kind == _EXACT:
            self.exact.setdefault(m.value, []).append(rule)
        elif m.kind == _CONTAINS:
            self.ac_entries.append((m.value, m.alt, rule))
        elif m.kind == _ENDSWITH:
            # Empty val tells _build_ac to skip the any-position key;
            # only the end-only alt key (the suffix) is registered.
            self.ac_entries.append(("", m.value, rule))
        elif m.kind == _STARTSWITH:
            self.startswith.append((m.value, rule))
        else:
            self.glob.append((m.value, rule))

    def build(self) -> _ByKind:
        return _ByKind(
            exact=self.exact,
            ac=_build_ac(self.ac_entries),
            startswith=self.startswith,
            glob=self.glob,
            additional=self.additional,
        )


@dataclass(slots=True)
class CompiledRuleSet:
    """All pattern rules from all categories, split by file/dir at compile time."""

    for_file: _ByKind = field(default_factory=_ByKind)
    for_dir: _ByKind = field(default_factory=_ByKind)


def compile_ruleset(
    rules: list[PatternRule],
    additional_paths: list[tuple[str, PatternRule]] | None = None,
) -> CompiledRuleSet:
    """Build a single CompiledRuleSet from all rules.

    Each rule already carries its own category. Rules with ``apply_to=BOTH``
    are merged into both file and dir collections at compile time so the hot
    loop never branches on apply_to.

    *additional_paths* are pre-normalized (base_path, rule) pairs.
    """
    builders = {_FILE: _ByKindBuilder(), _DIR: _ByKindBuilder()}

    for rule in rules:
        at = rule.apply_to
        for expanded_pat in _expand_braces(rule.pattern):
            m = _classify(expanded_pat)
            # IntFlag bitwise test: BOTH (= FILE | DIR) distributes
            # the rule into both builders in a single loop iteration.
            for flag, b in builders.items():
                if at & flag:
                    b.add(m, rule)

    if additional_paths:
        for base, rule in additional_paths:
            for flag, b in builders.items():
                if rule.apply_to & flag:
                    b.additional.append((base, rule))

    return CompiledRuleSet(
        for_file=builders[_FILE].build(),
        for_dir=builders[_DIR].build(),
    )


def match_all(
    rs: CompiledRuleSet,
    lpath: str,
    lbase: str,
    is_dir: bool,
    raw_path: str,
) -> list[PatternRule]:
    """Return all matching rules for a node, one pass across all categories.

    *lpath* and *lbase* must be pre-lowercased.
    *raw_path* is the original-case path for additional path matching.

    Returns at most one rule per category (first match wins).

    Perf: this function is called once per node during the insight traversal
    (millions of times on large trees).  All matching is done via inline
    ``for`` loops instead of list comprehensions to avoid allocating ~10
    temporary lists per call.  Do not refactor back to comprehensions.
    """
    bk = rs.for_dir if is_dir else rs.for_file
    matched: list[PatternRule] = []
    seen: set[str] = set()

    # First-match-per-category gatekeeper: once a category has a hit,
    # later matches for the same category are ignored.  Called from
    # every tier below (EXACT, AC, STARTSWITH, GLOB, additional).
    def _try(rule: PatternRule) -> None:
        cat = rule.category.value
        if cat not in seen:
            seen.add(cat)
            matched.append(rule)

    # --- EXACT: O(1) dict lookup ---
    hits = bk.exact.get(lbase)
    if hits:
        for rule in hits:
            _try(rule)

    # --- CONTAINS + ENDSWITH: Aho-Corasick automaton ---
    # A single ac.iter() call finds all CONTAINS and ENDSWITH matches.
    # end_only=True (set at compile time in _build_ac) restricts ENDSWITH
    # and CONTAINS-alt hits to fire only when the match ends at the last
    # character of the path — this is the runtime enforcement of the
    # "match at end of path" semantic.
    if bk.ac is not None:
        _lpath_end = len(lpath) - 1
        for end_idx, entries in bk.ac.iter(lpath):
            for rule, end_only in entries:
                if end_only and end_idx != _lpath_end:
                    continue
                _try(rule)

    # --- STARTSWITH ---
    for prefix, rule in bk.startswith:
        if lbase.startswith(prefix):
            _try(rule)

    # --- GLOB fallback ---
    for pat, rule in bk.glob:
        if _match_pattern_slow(pat, lpath, lbase):
            _try(rule)

    # --- Additional paths (pre-normalized) ---
    if bk.additional:
        for base, rule in bk.additional:
            if raw_path == base or raw_path.startswith(base + "/"):
                _try(rule)

    return matched
