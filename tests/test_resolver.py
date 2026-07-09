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


def test_resolve_links_without_configured_site():
    # No link_site configured — links render as bold text, no URL.
    # There's deliberately no hardcoded default database anymore.
    raw = "Check out this: |cff9d9d9d|Hitem:7078:0:0:0:0:0:0:0|h[Artifact Recipe: Lesser Invisibility Elixir]|h|r!"
    expected = "Check out this: **Artifact Recipe: Lesser Invisibility Elixir**!"
    assert resolver.resolve_links(raw) == expected

    raw = "Cast |cff71d5ff|Hspell:2060|h[Greater Heal]|h|r now."
    expected = "Cast **Greater Heal** now."
    assert resolver.resolve_links(raw) == expected

    print("test_resolve_links_without_configured_site passed.")


def test_resolve_links_with_configured_site():
    site = "https://my-custom-db.com"

    # Item link
    raw = "Check out this: |cff9d9d9d|Hitem:7078:0:0:0:0:0:0:0|h[Artifact Recipe: Lesser Invisibility Elixir]|h|r!"
    expected = "Check out this: [Artifact Recipe: Lesser Invisibility Elixir](https://my-custom-db.com?item=7078)!"
    assert resolver.resolve_links(raw, link_site=site) == expected

    # Spell link
    raw = "Cast |cff71d5ff|Hspell:2060|h[Greater Heal]|h|r now."
    expected = "Cast [Greater Heal](https://my-custom-db.com?spell=2060) now."
    assert resolver.resolve_links(raw, link_site=site) == expected

    # Quest link
    raw = "Accept |cffffd000|Hquest:1001:60|h[A New Hope]|h|r."
    expected = "Accept [A New Hope](https://my-custom-db.com?quest=1001)."
    assert resolver.resolve_links(raw, link_site=site) == expected

    # Achievement link
    raw = "Achieved |cffffff00|Hachievement:1180:0000000000000000:0:0:0:0|h[Hero of the Shattered Sun]|h|r!"
    expected = "Achieved [Hero of the Shattered Sun](https://my-custom-db.com?achievement=1180)!"
    assert resolver.resolve_links(raw, link_site=site) == expected

    # Enchant and talent links share the spell shape/param per Wowpedia
    raw = "Socket |cffffffff|Henchant:3789|h[Icy Weapon]|h|r for the slow."
    expected = "Socket [Icy Weapon](https://my-custom-db.com?spell=3789) for the slow."
    assert resolver.resolve_links(raw, link_site=site) == expected

    raw = "Take |cff4e96f7|Htalent:12345:0|h[Improved Fireball]|h|r."
    expected = "Take [Improved Fireball](https://my-custom-db.com?spell=12345)."
    assert resolver.resolve_links(raw, link_site=site) == expected

    # Trailing slash on the configured site shouldn't produce a double slash
    raw2 = "Cast |cff71d5ff|Hspell:2060|h[Greater Heal]|h|r now."
    expected2 = "Cast [Greater Heal](https://my-custom-db.com?spell=2060) now."
    assert resolver.resolve_links(raw2, link_site="https://my-custom-db.com/") == expected2

    print("test_resolve_links_with_configured_site passed.")


def test_resolve_links_unknown_kind_falls_back_to_bold():
    # A hyperlink kind we don't have a query-param mapping for should
    # still have its markup stripped (bold display text), not crash or
    # leave raw pipe-markup behind — even with a site configured.
    raw = "|cffffffff|Hsomethingnew:99|h[Mystery Link]|h|r"
    assert resolver.resolve_links(raw, link_site="https://my-custom-db.com") == "**Mystery Link**"


def test_resolve_links_leaves_plain_text_untouched():
    raw = "just a normal chat message, no links here"
    assert resolver.resolve_links(raw) == raw
    assert resolver.resolve_links(raw, link_site="https://my-custom-db.com") == raw


def test_resolve_links_multiple_in_one_message():
    raw = (
        "Trading |cff9d9d9d|Hitem:7078:0:0:0:0:0:0:0|h[Recipe]|h|r "
        "for |cff71d5ff|Hspell:2060|h[Greater Heal]|h|r lessons"
    )
    expected = "Trading **Recipe** for **Greater Heal** lessons"
    assert resolver.resolve_links(raw) == expected


def test_pipeline_order_resolve_links_then_strip_color():
    """
    Regression test: a hyperlink's markup IS itself shaped like a color
    span (|c........ ... |r), so running strip_color_coding before
    resolve_links would eat the leading |c code resolve_links needs to
    recognize the link at all, silently leaving raw |Hitem:...|h markup
    in the output instead of resolving it. The correct pipeline order
    is resolve_links first, then strip_color_coding to mop up anything
    left over — this test locks that order in.
    """
    raw = "Selling |cff9d9d9d|Hitem:7078:0:0:0:0:0:0:0|h[Recipe]|h|r cheap!"

    # Correct order: resolve_links sees the intact markup and matches.
    correct = resolver.strip_color_coding(resolver.resolve_links(raw))
    assert correct == "Selling **Recipe** cheap!"
    assert "|H" not in correct and "|h" not in correct

    # Wrong order, kept here as a documented negative example: this is
    # exactly the bug that shipped briefly — strip_color_coding first
    # eats the |c prefix, so resolve_links can no longer match and raw
    # markup leaks through.
    wrong = resolver.resolve_links(resolver.strip_color_coding(raw))
    assert "|H" in wrong  # demonstrates the bug this test guards against


def test_should_send_directly():
    from guildcord.config.schema import BridgeConfig, WowConfig, DiscordConfig
    from guildcord.discord_bridge.bot import WowBridge

    # Setup configurations
    wow_cfg = WowConfig(
        auth_host="127.0.0.1", auth_port=3724, world_port=8085,
        account="TEST", password="pwd", realm_name="Realm"
    )

    # 1. Dot commands disabled by default
    discord_cfg = DiscordConfig(bot_token="tok", enable_dot_commands=False)
    bridge = WowBridge(BridgeConfig(wow=wow_cfg, discord=discord_cfg))
    assert bridge.should_send_directly(".s info") is False

    # 2. Dot commands enabled, no whitelist (allows everything starting with .)
    discord_cfg2 = DiscordConfig(bot_token="tok", enable_dot_commands=True)
    bridge2 = WowBridge(BridgeConfig(wow=wow_cfg, discord=discord_cfg2))
    assert bridge2.should_send_directly(".s info") is True
    assert bridge2.should_send_directly("hello") is False

    # 3. Whitelist set
    discord_cfg3 = DiscordConfig(
        bot_token="tok",
        enable_dot_commands=True,
        dot_commands_whitelist=["s", "lookup*"]
    )
    bridge3 = WowBridge(BridgeConfig(wow=wow_cfg, discord=discord_cfg3))
    assert bridge3.should_send_directly(".s info") is True
    assert bridge3.should_send_directly(".lookup item 123") is True
    assert bridge3.should_send_directly(".teleport home") is False

    print("test_should_send_directly passed.")


if __name__ == "__main__":
    test_strip_color_coding()
    test_resolve_links_without_configured_site()
    test_resolve_links_with_configured_site()
    test_resolve_links_unknown_kind_falls_back_to_bold()
    test_resolve_links_leaves_plain_text_untouched()
    test_resolve_links_multiple_in_one_message()
    test_pipeline_order_resolve_links_then_strip_color()
    test_should_send_directly()
    print("All resolver tests passed successfully.")
