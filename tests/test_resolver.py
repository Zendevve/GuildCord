"""
Tests for WoW color code stripping and item/spell link resolution.
Run with: python tests/test_resolver.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from guildcord.world import resolver


def test_strip_color_coding():
    # Basic color block
    raw = "|cff00ff00Green text|r"
    assert resolver.strip_color_coding(raw) == "Green text"

    # Multi color block
    raw = "Hello |cff00ff00Green|r and |cffff0000Red|r!"
    assert resolver.strip_color_coding(raw) == "Hello Green and Red!"

    # Unbalanced tags
    raw = "|cff00ff00Stray color start"
    assert resolver.strip_color_coding(raw) == "Stray color start"

    raw = "Stray color end|r"
    assert resolver.strip_color_coding(raw) == "Stray color end"

    print("test_strip_color_coding passed.")


def test_resolve_links():
    # Item link
    raw = "Check out this: |cff9d9d9d|Hitem:7078:0:0:0:0:0:0:0|h[Artifact Recipe: Lesser Invisibility Elixir]|h|r!"
    expected = "Check out this: [Artifact Recipe: Lesser Invisibility Elixir](https://wotlk-twinhead.twinstar.cz?item=7078)!"
    assert resolver.resolve_links(raw) == expected

    # Spell link
    raw = "Cast |cff71d5ff|Hspell:2060|h[Greater Heal]|h|r now."
    expected = "Cast [Greater Heal](https://wotlk-twinhead.twinstar.cz?spell=2060) now."
    assert resolver.resolve_links(raw) == expected

    # Quest link
    raw = "Accept |cffffd000|Hquest:1001:60|h[A New Hope]|h|r."
    expected = "Accept [A New Hope](https://wotlk-twinhead.twinstar.cz?quest=1001)."
    assert resolver.resolve_links(raw) == expected

    # Achievement link
    raw = "Achieved |cffffff00|Hachievement:1180:0000000000000000:0:0:0:0|h[Hero of the Shattered Sun]|h|r!"
    expected = "Achieved [Hero of the Shattered Sun](https://wotlk-twinhead.twinstar.cz?achievement=1180)!"
    assert resolver.resolve_links(raw) == expected

    # Custom database site
    expected_custom = "Cast [Greater Heal](https://my-custom-db.com?spell=2060) now."
    assert resolver.resolve_links(message="Cast |cff71d5ff|Hspell:2060|h[Greater Heal]|h|r now.", link_site="https://my-custom-db.com/") == expected_custom

    print("test_resolve_links passed.")


if __name__ == "__main__":
    test_strip_color_coding()
    test_resolve_links()
    print("All resolver tests passed successfully.")
