"""
Tests for Discord custom-emoji-markup resolution before relaying into
WoW chat.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from guildcord.discord_bridge.emoji import resolve_discord_emoji


def test_static_custom_emoji():
    assert resolve_discord_emoji("<:pepehands:123456789012345678>") == ":pepehands:"


def test_animated_custom_emoji():
    assert resolve_discord_emoji("<a:dancing:987654321098765432>") == ":dancing:"


def test_emoji_within_a_sentence():
    raw = "gg <:pepehands:123456789012345678> that was close"
    assert resolve_discord_emoji(raw) == "gg :pepehands: that was close"


def test_multiple_emoji_in_one_message():
    raw = "<:kekw:111111111111111111><a:pog:222222222222222222>"
    assert resolve_discord_emoji(raw) == ":kekw::pog:"


def test_plain_unicode_emoji_passes_through_untouched():
    raw = "nice one 😀"
    assert resolve_discord_emoji(raw) == raw


def test_no_emoji_passes_through_untouched():
    raw = "just a normal message"
    assert resolve_discord_emoji(raw) == raw


def test_does_not_touch_wow_style_colons():
    # Make sure this doesn't overreach into unrelated colon-delimited
    # text that isn't actually Discord emoji markup (no surrounding
    # angle brackets / numeric id, so it shouldn't match).
    raw = "time is 10:30, see you then"
    assert resolve_discord_emoji(raw) == raw


if __name__ == "__main__":
    test_static_custom_emoji()
    test_animated_custom_emoji()
    test_emoji_within_a_sentence()
    test_multiple_emoji_in_one_message()
    test_plain_unicode_emoji_passes_through_untouched()
    test_no_emoji_passes_through_untouched()
    test_does_not_touch_wow_style_colons()
    print("All emoji resolution tests passed.")
