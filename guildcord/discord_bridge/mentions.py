"""
Resolves mentions in chat messages relayed between Discord and WoW.
"""

from __future__ import annotations

import re
import discord

# Matches "@name" or "@"name with spaces""
# e.g., @Bob or @"Bob Smith"
MENTION_RE = re.compile(r'@(?:"([^"]+)"|([a-zA-Z0-9_\-\.]+))')


def resolve_wow_mentions(message: str, channel: discord.abc.GuildChannel | discord.abc.PrivateChannel) -> str:
    """
    Finds @username or @"role or user name" tags in WoW chat and resolves them
    to Discord mention tags (<@id> or <@&id>) if a match is found in the channel.
    """
    guild = getattr(channel, "guild", None)
    if not guild:
        return message

    bot_id = guild.me.id if guild.me else None

    # Gather potential roles and members
    candidates: list[tuple[str, str]] = []

    # Add roles (excluding @everyone)
    for role in guild.roles:
        if role.name != "@everyone":
            candidates.append((role.name.lower(), f"<@&{role.id}>"))

    # Add members in this channel
    for member in channel.members:
        if bot_id and member.id == bot_id:
            continue
        names = {member.name.lower(), member.display_name.lower()}
        if member.nick:
            names.add(member.nick.lower())
        for name in names:
            if name:
                candidates.append((name, f"<@{member.id}>"))

    def replace_match(match: re.Match) -> str:
        # Extract tag name from either group 1 (quoted) or group 2 (unquoted)
        tag_name = (match.group(1) or match.group(2) or "").lower().strip()
        if not tag_name:
            return match.group(0)

        # Look for exact match first
        matched_mentions = []
        for cand_name, mention_str in candidates:
            if cand_name == tag_name:
                matched_mentions.append(mention_str)

        # If no exact match, try matching as a word in candidate name
        if not matched_mentions:
            for cand_name, mention_str in candidates:
                words = re.split(r"\W+", cand_name)
                if tag_name in words:
                    matched_mentions.append(mention_str)

        # Deduplicate
        unique_matches = list(set(matched_mentions))
        if len(unique_matches) == 1:
            return unique_matches[0]

        return match.group(0)

    return MENTION_RE.sub(replace_match, message)
