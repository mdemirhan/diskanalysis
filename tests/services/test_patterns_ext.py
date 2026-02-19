from __future__ import annotations

from dux.config.schema import PatternRule
from dux.models.enums import ApplyTo, InsightCategory
from dux.services.patterns import _classify, _match_pattern_slow, compile_ruleset, match_all

_GLOB = 4


def _rule(name: str = "r", pattern: str = "**/*", cat: InsightCategory = InsightCategory.TEMP) -> PatternRule:
    return PatternRule(name=name, pattern=pattern, category=cat)


class TestClassifyGlobFallback:
    def test_no_double_star_prefix(self) -> None:
        m = _classify("foo/*.log")
        assert m.kind == _GLOB

    def test_double_star_dir_with_glob_chars(self) -> None:
        m = _classify("**/?foo/**")
        assert m.kind == _GLOB

    def test_rest_has_glob_chars(self) -> None:
        m = _classify("**/[abc]file")
        assert m.kind == _GLOB


class TestMatchPatternSlow:
    def test_dir_pattern_matches_normalized(self) -> None:
        assert _match_pattern_slow("**/tmp/**", "/root/tmp/foo", "foo") is True

    def test_full_path_match(self) -> None:
        assert _match_pattern_slow("**/*.log", "/root/app.log", "app.log") is True

    def test_basename_match(self) -> None:
        assert _match_pattern_slow("*.txt", "/root/notes.txt", "notes.txt") is True

    def test_no_match(self) -> None:
        assert _match_pattern_slow("*.py", "/root/notes.txt", "notes.txt") is False


class TestCompileRulesetGlob:
    def test_non_double_star_goes_to_glob(self) -> None:
        rule = PatternRule("test", "foo/*.log", InsightCategory.TEMP)
        rs = compile_ruleset([rule])
        assert len(rs.for_file.glob) > 0

    def test_glob_match_via_match_all(self) -> None:
        rule = PatternRule("test", "foo/*.log", InsightCategory.TEMP)
        rs = compile_ruleset([rule])
        hits = match_all(rs, "foo/app.log", "app.log", False)
        assert len(hits) == 1
        assert hits[0].name == "test"


class TestApplyToDirMatching:
    def test_dir_only_rule_matches_dir(self) -> None:
        rule = PatternRule("egg", "**/*.egg-info", InsightCategory.BUILD_ARTIFACT, apply_to=ApplyTo.DIR)
        rs = compile_ruleset([rule])
        hits = match_all(rs, "/r/pkg.egg-info", "pkg.egg-info", True)
        assert len(hits) == 1

    def test_dir_only_rule_skips_file(self) -> None:
        rule = PatternRule("egg", "**/*.egg-info", InsightCategory.BUILD_ARTIFACT, apply_to=ApplyTo.DIR)
        rs = compile_ruleset([rule])
        hits = match_all(rs, "/r/pkg.egg-info", "pkg.egg-info", False)
        assert len(hits) == 0

    def test_file_only_rule_skips_dir(self) -> None:
        rule = PatternRule("log", "**/*.log", InsightCategory.TEMP, apply_to=ApplyTo.FILE)
        rs = compile_ruleset([rule])
        hits = match_all(rs, "/r/app.log", "app.log", True)
        assert len(hits) == 0
