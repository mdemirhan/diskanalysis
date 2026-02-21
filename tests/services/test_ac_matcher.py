from __future__ import annotations

import pytest

from dux._ac_matcher import AhoCorasick


def test_empty_automaton_returns_empty_list() -> None:
    ac = AhoCorasick()
    ac.make_automaton()
    assert ac.iter("hello world") == []


def test_iter_before_make_automaton_raises() -> None:
    ac = AhoCorasick()
    ac.add_word("x", 1)
    with pytest.raises(RuntimeError, match="call make_automaton"):
        ac.iter("x")


def test_add_word_after_make_automaton_raises() -> None:
    ac = AhoCorasick()
    ac.add_word("a", 1)
    ac.make_automaton()
    with pytest.raises(RuntimeError, match="cannot add_word after make_automaton"):
        ac.add_word("b", 2)


def test_make_automaton_twice_raises() -> None:
    ac = AhoCorasick()
    ac.add_word("a", 1)
    ac.make_automaton()
    with pytest.raises(RuntimeError, match="automaton already built"):
        ac.make_automaton()


def test_single_pattern_match() -> None:
    ac = AhoCorasick()
    ac.add_word("he", 42)
    ac.make_automaton()
    result = ac.iter("she")
    assert result == [(2, 42)]


def test_end_index_is_last_byte() -> None:
    """end_index is the 0-based index of the last byte of the match."""
    ac = AhoCorasick()
    ac.add_word("abc", "found")
    ac.make_automaton()
    # text: x a b c y
    # idx:  0 1 2 3 4
    result = ac.iter("xabcy")
    assert result == [(3, "found")]


def test_multiple_overlapping_patterns() -> None:
    ac = AhoCorasick()
    ac.add_word("he", 1)
    ac.add_word("she", 2)
    ac.add_word("his", 3)
    ac.add_word("hers", 4)
    ac.make_automaton()
    result = ac.iter("shers")
    # "she" ends at index 2, "he" ends at 2 (via dict_suffix), "hers" ends at 4
    end_indices = {(idx, val) for idx, val in result}
    assert (2, 2) in end_indices  # "she"
    assert (2, 1) in end_indices  # "he"
    assert (4, 4) in end_indices  # "hers"


def test_no_match_returns_empty() -> None:
    ac = AhoCorasick()
    ac.add_word("xyz", 1)
    ac.make_automaton()
    assert ac.iter("abc") == []


def test_pattern_at_start() -> None:
    ac = AhoCorasick()
    ac.add_word("abc", 1)
    ac.make_automaton()
    result = ac.iter("abcdef")
    assert result == [(2, 1)]


def test_pattern_at_end() -> None:
    ac = AhoCorasick()
    ac.add_word("def", 1)
    ac.make_automaton()
    result = ac.iter("abcdef")
    assert result == [(5, 1)]


def test_pattern_in_middle() -> None:
    ac = AhoCorasick()
    ac.add_word("cd", 1)
    ac.make_automaton()
    result = ac.iter("abcdef")
    assert result == [(3, 1)]


def test_duplicate_key_overwrites_value() -> None:
    ac = AhoCorasick()
    ac.add_word("ab", "first")
    ac.add_word("ab", "second")
    ac.make_automaton()
    result = ac.iter("ab")
    # C code sets nodes[cur].output = vid each time, so last write wins
    assert result == [(1, "second")]


def test_arbitrary_value_list() -> None:
    ac = AhoCorasick()
    val = [1, 2, 3]
    ac.add_word("key", val)
    ac.make_automaton()
    result = ac.iter("key")
    assert result == [(2, [1, 2, 3])]


def test_arbitrary_value_dict() -> None:
    ac = AhoCorasick()
    val = {"cat": "temp"}
    ac.add_word("key", val)
    ac.make_automaton()
    result = ac.iter("key")
    assert result[0][1] == {"cat": "temp"}


def test_case_sensitivity() -> None:
    """AhoCorasick is case-sensitive; caller must lowercase."""
    ac = AhoCorasick()
    ac.add_word("abc", 1)
    ac.make_automaton()
    assert ac.iter("ABC") == []
    assert ac.iter("abc") == [(2, 1)]


def test_empty_key_never_matches() -> None:
    """Empty string as key: root gets output but iter loop skips root."""
    ac = AhoCorasick()
    ac.add_word("", 99)
    ac.make_automaton()
    # The iter loop uses `while (tmp > 0)` so root output is never collected
    assert ac.iter("anything") == []
    assert ac.iter("") == []


def test_single_char_patterns() -> None:
    ac = AhoCorasick()
    ac.add_word("a", 1)
    ac.add_word("b", 2)
    ac.make_automaton()
    result = ac.iter("cab")
    assert result == [(1, 1), (2, 2)]


def test_long_text_multiple_positions() -> None:
    ac = AhoCorasick()
    ac.add_word("needle", 1)
    ac.make_automaton()
    text = "x" * 1000 + "needle" + "y" * 1000 + "needle" + "z" * 500
    result = ac.iter(text)
    assert len(result) == 2
    assert result[0] == (1005, 1)  # first "needle" ends at 1005
    assert result[1] == (2011, 1)  # second "needle" ends at 2011


def test_multiple_matches_same_position() -> None:
    """Patterns 'a' and 'ba' both end at the same index."""
    ac = AhoCorasick()
    ac.add_word("a", 1)
    ac.add_word("ba", 2)
    ac.make_automaton()
    result = ac.iter("ba")
    end_indices = {(idx, val) for idx, val in result}
    assert (1, 1) in end_indices  # "a" ends at 1
    assert (1, 2) in end_indices  # "ba" ends at 1


def test_repeated_pattern_in_text() -> None:
    ac = AhoCorasick()
    ac.add_word("aa", 1)
    ac.make_automaton()
    result = ac.iter("aaa")
    # "aa" at positions 0-1 (end=1) and 1-2 (end=2)
    assert result == [(1, 1), (2, 1)]
