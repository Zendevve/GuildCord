"""
Helper functions to strip WoW in-game color codes and resolve links
(items, spells, quests, achievements) into clickable web database URLs.
"""

from __future__ import annotations

import re

# Regex to match hex color codes like |cff00ff00 and their corresponding reset |r
# Format: |c(AARRGGBB)text|r
COLOR_CODE_RE = re.compile(r"\|c[0-9a-fA-F]{8}(.*?)\|r")
RAW_COLOR_START_RE = re.compile(r"\|c[0-9a-fA-F]{8}")
RAW_COLOR_END_RE = re.compile(r"\|r")

# WotLK-specific link regexes
# Item link format: |cff9d9d9d|Hitem:7078:0:0:0:0:0:0:0|h[Artifact Recipe: Lesser Invisibility Elixir]|h|r
ITEM_RE = re.compile(r"\|.+?\|Hitem:(\d+):.+?\|h\[(.+?)\]\|h\|r")
# Spell / Enchant / Talent link format: |cff71d5ff|Hspell:2060|h[Greater Heal]|h|r
SPELL_RE = re.compile(r"\|.+?\|(?:Hspell|Henchant|Htalent)?:(\d+).*?\|h\[(.+?)\]\|h\|r")
# Quest link format: |cffffd000|Hquest:1001:60|h[A New Hope]|h|r
QUEST_RE = re.compile(r"\|.+?\|Hquest:(\d+):.+?\|h\[(.+?)\]\|h\|r")
# Achievement link format: |cffffff00|Hachievement:1180:0000000000000000:0:0:0:0|h[Hero of the Shattered Sun]|h|r
ACHIEVEMENT_RE = re.compile(r"\|.+?\|Hachievement:(\d+):.+?\|h\[(.+?)\]\|h\|r")
# Trade link format: |Htrade:51300:280:280:80000:7E17E3D3|h[Tailoring]|h
TRADE_RE = re.compile(r"\|Htrade:(\d+):.+?\|h\[(.+?)\]\|h")


def strip_color_coding(message: str) -> str:
    """
    Removes WoW-specific color coding markup.
    e.g. "|cff00ff00Hello|r" -> "Hello"
    """
    # Replace balanced color blocks with their text
    res = COLOR_CODE_RE.sub(r"\1", message)
    # Strip any stray or unbalanced color codes
    res = RAW_COLOR_START_RE.sub("", res)
    res = RAW_COLOR_END_RE.sub("", res)
    return res


def resolve_links(message: str, client_build: int = 12340, link_site: str | None = None) -> str:
    """
    Finds in-game WoW item, spell, quest, achievement, and trade links,
    and replaces them with Discord-compatible markdown links pointing to a database site.
    """
    if not link_site:
        # Default database website based on build
        # 12340 is 3.3.5a (WotLK)
        if client_build < 8606:      # Vanilla (< 2.0.1)
            link_site = "https://classicdb.ch"
        elif client_build < 12340:   # TBC (< 3.0.2)
            link_site = "https://tbc-twinhead.twinstar.cz"
        else:                        # WotLK / default
            link_site = "https://wotlk-twinhead.twinstar.cz"

    # Ensure link_site doesn't end with a slash for clean query parameters
    link_site = link_site.rstrip("/")

    # Resolve items
    message = ITEM_RE.sub(rf"[\2]({link_site}?item=\1)", message)

    # Resolve spells / enchants
    message = SPELL_RE.sub(rf"[\2]({link_site}?spell=\1)", message)

    # Resolve quests
    message = QUEST_RE.sub(rf"[\2]({link_site}?quest=\1)", message)

    # Resolve achievements
    message = ACHIEVEMENT_RE.sub(rf"[\2]({link_site}?achievement=\1)", message)

    # Resolve trades
    message = TRADE_RE.sub(rf"[\2]({link_site}?spell=\1)", message)

    return message
