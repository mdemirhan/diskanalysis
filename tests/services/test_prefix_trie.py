from __future__ import annotations

import pytest

from dux._prefix_trie import PrefixTrie


def test_empty_trie_returns_empty() -> None:
    pt = PrefixTrie()
    pt.build()
    assert pt.iter("anything") == []


def test_single_prefix_match() -> None:
    pt = PrefixTrie()
    pt.add_prefix("npm", "matched")
    pt.build()
    assert pt.iter("npm-debug.log") == ["matched"]


def test_multiple_prefixes_one_matches() -> None:
    pt = PrefixTrie()
    pt.add_prefix("npm", "npm-val")
    pt.add_prefix("yarn", "yarn-val")
    pt.build()
    assert pt.iter("npm-debug.log") == ["npm-val"]
    assert pt.iter("yarn.lock") == ["yarn-val"]


def test_overlapping_prefixes() -> None:
    """Both "npm" and "npm-debug" fire on "npm-debug.log"."""
    pt = PrefixTrie()
    pt.add_prefix("npm", "short")
    pt.add_prefix("npm-debug", "long")
    pt.build()
    result = pt.iter("npm-debug.log")
    assert result == ["short", "long"]


def test_no_match() -> None:
    pt = PrefixTrie()
    pt.add_prefix("xyz", "val")
    pt.build()
    assert pt.iter("abc") == []


def test_iter_before_build_raises() -> None:
    pt = PrefixTrie()
    pt.add_prefix("x", 1)
    with pytest.raises(RuntimeError, match="call build"):
        pt.iter("x")


def test_add_prefix_after_build_raises() -> None:
    pt = PrefixTrie()
    pt.add_prefix("a", 1)
    pt.build()
    with pytest.raises(RuntimeError, match="cannot add_prefix after build"):
        pt.add_prefix("b", 2)


def test_build_twice_raises() -> None:
    pt = PrefixTrie()
    pt.add_prefix("a", 1)
    pt.build()
    with pytest.raises(RuntimeError, match="trie already built"):
        pt.build()


def test_case_sensitivity() -> None:
    """PrefixTrie is case-sensitive; caller must lowercase."""
    pt = PrefixTrie()
    pt.add_prefix("abc", 1)
    pt.build()
    assert pt.iter("ABC") == []
    assert pt.iter("abc") == [1]
