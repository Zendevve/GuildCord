"""
Pure text-formatting helpers for the WoW <-> Discord relay: message
template substitution and per-channel regex filtering. Kept separate
from bot.py (which owns the actual Discord/WoW I/O) so this logic is
unit-testable without spinning up a bot, a socket, or a mock Discord
channel.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, Optional


def format_relay_message(
    template: str,
    *,
    user: str,
    message: str,
    channel: str = "",
    time_format: str = "%H:%M:%S",
    now: Optional[datetime] = None,
) -> str:
    """
    Substitutes %time / %channel / %user / %message tokens in a message
    format template.

    `now` is injectable so tests can assert exact output instead of
    matching against "whatever time it happens to be right now"; it
    defaults to the current local time in real use.
    """
    timestamp = (now or datetime.now()).strftime(time_format)
    return (
        template.replace("%time", timestamp)
        .replace("%channel", channel)
        .replace("%user", user)
        .replace("%message", message)
    )


def matches_any_filter(patterns: Iterable[str], text: str) -> bool:
    """
    Returns True if `text` matches any of the given regex patterns
    (case-insensitive) — i.e. the message should be blocked from
    relaying. An invalid regex in the list is treated as a non-match
    rather than raised, so one bad pattern in someone's config doesn't
    take down the whole relay; callers should log.warning about
    invalid patterns separately (e.g. at config-load time) if they
    want that surfaced.
    """
    for pattern in patterns:
        try:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        except re.error:
            continue
    return False
