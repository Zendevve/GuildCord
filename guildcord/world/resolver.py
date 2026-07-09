"""
Resolves WoW in-game hyperlinks (items, spells, quests, achievements,
enchants, talents, etc.) into Discord-friendly text, and strips WoW's
raw color-code markup.

Built from Blizzard's publicly documented client hyperlink format (see
e.g. Warcraft Wiki / Wowpedia's "Hyperlinks", "ItemLink", and
"SpellLink" pages) — the text format the client embeds in chat
messages — not from any bridge bot's source. Every hyperlink type
shares one shape:

    |c<AARRGGBB>|H<linktype>:<id>[:<extra colon-separated fields>]|h[<display text>]|h|r

e.g.
    |cff9d9d9d|Hitem:7073:0:0:0:0:0:0:0|h[Broken Fang]|h|r
    |cff71d5ff|Hspell:10060|h[Power Infusion]|h|r

Wowpedia's SpellLink page notes that spell/enchant/quest/talent links
all follow this same shape, differing only in the type prefix and
payload — which is why this module matches every kind with one general
pattern below instead of a separate regex per link type.
"""

from __future__ import annotations

import re
from typing import Optional

# --- color markup -------------------------------------------------------
#
# WoW color codes wrap a span of text as |c<8 hex AARRGGBB>...text...|r.
# Strip these before display since Discord doesn't render them. Handle
# balanced pairs first (keeping the inner text), then clean up any
# stray/unbalanced markers a partial or truncated message might contain.

_COLOR_SPAN_RE = re.compile(r"\|c[0-9A-Fa-f]{8}(.*?)\|r", re.DOTALL)
_STRAY_COLOR_START_RE = re.compile(r"\|c[0-9A-Fa-f]{8}")
_STRAY_COLOR_END_RE = re.compile(r"\|r")


def strip_color_coding(message: str) -> str:
    """Removes WoW color markup, e.g. '|cff00ff00Hello|r' -> 'Hello'."""
    message = _COLOR_SPAN_RE.sub(r"\1", message)
    message = _STRAY_COLOR_START_RE.sub("", message)
    message = _STRAY_COLOR_END_RE.sub("", message)
    return message


# --- hyperlinks -----------------------------------------------------------
#
# One general pattern for every hyperlink kind, per the shared-shape
# note above. `kind` and `id` are captured so the caller can decide how
# (or whether) to turn them into a URL; `text` is always the bracketed
# display name.
#
# The color prefix is matched as a literal 8-hex-digit group (exactly
# what it is on the wire) rather than a generic "anything" wildcard —
# tighter, and avoids accidentally matching unrelated pipe-delimited
# content elsewhere in a message. The payload tail is matched as
# "everything that isn't a pipe" up to |h, since it's always a run of
# colon-separated numbers with no pipe characters in it.

_HYPERLINK_RE = re.compile(
    r"\|c[0-9A-Fa-f]{8}"                 # color prefix, e.g. |cff9d9d9d
    r"\|H(?P<kind>[A-Za-z]+)"            # link type, e.g. item / spell / quest
    r":(?P<id>-?\d+)"                    # first payload field — the actual ID
    r"[^|]*"                             # any remaining :field:field... payload
    r"\|h\[(?P<text>[^\]]+)\]\|h\|r"     # |h[Display Name]|h|r
)

# Maps a link kind (lowercased) to the URL query parameter a typical
# item/spell database site expects for it. Kinds not listed here still
# get their display text shown (as bold), just without a hyperlink.
_KIND_TO_QUERY_PARAM = {
    "item": "item",
    "spell": "spell",
    "enchant": "spell",
    "talent": "spell",
    "glyph": "spell",
    "quest": "quest",
    "achievement": "achievement",
    "trade": "spell",
}


def resolve_links(message: str, link_site: Optional[str] = None) -> str:
    """
    Replaces in-game hyperlinks with Discord-friendly text.

    If `link_site` is configured, links become clickable Markdown
    pointing at f"{link_site}?{param}={id}" — this assumes the site
    supports query-string lookups (?item=<id>, ?spell=<id>, etc.), which
    e.g. wotlkdb.com and wotlk.evowow.com do, but Wowhead does NOT
    (it uses path-style URLs like wowhead.com/wotlk/item=<id>/slug
    instead). Point this at a query-string-style site, or leave it
    unset.

    If it's not configured, links render as plain bold item names with
    no hyperlink — deliberately no hardcoded fallback database. Which
    fan site to send players to isn't something this project should
    decide on a server owner's behalf; it's opt-in via the
    `item_database` config field instead.
    """

    def _replace(match: "re.Match[str]") -> str:
        kind = match.group("kind").lower()
        link_id = match.group("id")
        text = match.group("text")

        if link_site and kind in _KIND_TO_QUERY_PARAM:
            param = _KIND_TO_QUERY_PARAM[kind]
            base = link_site.rstrip("/")
            return f"[{text}]({base}?{param}={link_id})"

        return f"**{text}**"

    return _HYPERLINK_RE.sub(_replace, message)
