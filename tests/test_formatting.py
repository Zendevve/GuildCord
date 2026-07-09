"""
Tests for the pure formatting/filter helpers used by the relay.
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from guildcord.discord_bridge.formatting import format_relay_message, matches_any_filter


def test_all_four_tokens_substituted():
    fixed_time = datetime(2026, 7, 9, 14, 30, 5)
    result = format_relay_message(
        "[%time] (%channel) %user: %message",
        user="Alice",
        message="hello there",
        channel="General",
        time_format="%H:%M:%S",
        now=fixed_time,
    )
    assert result == "[14:30:05] (General) Alice: hello there"


def test_missing_tokens_are_left_alone():
    # A template that doesn't use every token should still work fine —
    # replace() on a token that isn't present is a harmless no-op.
    result = format_relay_message(
        "%user says: %message",
        user="Bob",
        message="hi",
        channel="Guild",
        now=datetime(2026, 1, 1),
    )
    assert result == "Bob says: hi"


def test_custom_time_format():
    fixed_time = datetime(2026, 7, 9, 14, 30, 5)
    result = format_relay_message(
        "%time %user",
        user="Carol",
        message="",
        time_format="%I:%M %p",
        now=fixed_time,
    )
    assert result == "02:30 PM Carol"


def test_default_now_does_not_crash():
    # No `now` passed — should use the real current time without error.
    result = format_relay_message("%time %user: %message", user="Dave", message="x")
    assert "Dave: x" in result


def test_matches_any_filter_basic():
    assert matches_any_filter([r"gold\s*seller"], "cheap gold seller here") is True
    assert matches_any_filter([r"gold\s*seller"], "just saying hi") is False


def test_matches_any_filter_is_case_insensitive():
    assert matches_any_filter([r"spam"], "totally not SPAM") is True


def test_matches_any_filter_multiple_patterns():
    patterns = [r"^\.", r"discord\.gg"]
    assert matches_any_filter(patterns, ".teleport") is True
    assert matches_any_filter(patterns, "join my discord.gg/abc") is True
    assert matches_any_filter(patterns, "hello world") is False


def test_matches_any_filter_empty_list_never_matches():
    assert matches_any_filter([], "anything at all") is False


def test_matches_any_filter_invalid_regex_does_not_raise():
    # A malformed pattern (unbalanced group) should be skipped, not
    # crash the whole filter check — other valid patterns still apply.
    patterns = [r"(unclosed", r"valid"]
    assert matches_any_filter(patterns, "this is valid text") is True
    assert matches_any_filter(patterns, "nothing matches here") is False


if __name__ == "__main__":
    test_all_four_tokens_substituted()
    test_missing_tokens_are_left_alone()
    test_custom_time_format()
    test_default_now_does_not_crash()
    test_matches_any_filter_basic()
    test_matches_any_filter_is_case_insensitive()
    test_matches_any_filter_multiple_patterns()
    test_matches_any_filter_empty_list_never_matches()
    test_matches_any_filter_invalid_regex_does_not_raise()
    print("All formatting/filter tests passed.")
