"""
Converts Discord custom-emoji markup into plain text before relaying a
Discord message into WoW chat. Discord stores a typed custom emoji as
<:name:id> (or <a:name:id> for animated ones) in message content — WoW
obviously can't render that, so it needs to become readable text
instead.

Note this only concerns Discord's *custom* guild emoji markup. Plain
Unicode emoji (typed directly, e.g. "😀") pass through untouched; the
3.3.5a client's font rendering for arbitrary Unicode is a separate,
much fuzzier concern than the well-defined "raw <:name:id> markup
would appear literally in chat" problem this module fixes.
"""

from __future__ import annotations

import re

_DISCORD_EMOJI_RE = re.compile(r"<a?:(\w+):\d+>")


def resolve_discord_emoji(content: str) -> str:
    """'<:pepehands:123456789012345678>' -> ':pepehands:'"""
    return _DISCORD_EMOJI_RE.sub(r":\1:", content)
