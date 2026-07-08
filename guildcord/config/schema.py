"""
Config schema + YAML loader for guildcord.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import yaml


@dataclass
class ChannelMapping:
    wow_channel: Optional[str]  # e.g. "General", or None for say/guild/etc via chat_type
    chat_type: str  # "say" | "guild" | "yell" | "channel" | "officer"
    discord_channel_id: int
    direction: str = "both"  # "wow_to_discord" | "discord_to_wow" | "both"
    format: str = "**%user**: %message"


@dataclass
class WowConfig:
    auth_host: str
    auth_port: int
    world_port: int
    account: str
    password: str
    realm_name: str
    realm_id: int = 1
    character_guid: Optional[int] = None  # bypasses SMSG_CHAR_ENUM parsing if set
    client_build: int = 12340
    platform: str = "Windows"             # "Windows" or "Mac"


@dataclass
class DiscordConfig:
    bot_token: str
    command_prefix: str = "!"
    item_database: Optional[str] = None
    enable_dot_commands: bool = False
    dot_commands_whitelist: list[str] = field(default_factory=list)


@dataclass
class BridgeConfig:
    wow: WowConfig
    discord: DiscordConfig
    channels: list[ChannelMapping] = field(default_factory=list)


def load_config(path: str) -> BridgeConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    wow_raw = raw["wow"]
    wow = WowConfig(
        auth_host=wow_raw["auth_host"],
        auth_port=wow_raw.get("auth_port", 3724),
        world_port=wow_raw["world_port"],
        account=wow_raw["account"],
        password=wow_raw["password"],
        realm_name=wow_raw["realm_name"],
        realm_id=wow_raw.get("realm_id", 1),
        character_guid=wow_raw.get("character_guid"),
        client_build=wow_raw.get("client_build", 12340),
        platform=wow_raw.get("platform", "Windows"),
    )

    discord_raw = raw["discord"]
    discord = DiscordConfig(
        bot_token=discord_raw["bot_token"],
        command_prefix=discord_raw.get("command_prefix", "!"),
        item_database=discord_raw.get("item_database"),
        enable_dot_commands=discord_raw.get("enable_dot_commands", False),
        dot_commands_whitelist=discord_raw.get("dot_commands_whitelist", []),
    )

    channels = []
    for c in raw.get("channels", []):
        channels.append(
            ChannelMapping(
                wow_channel=c.get("wow_channel"),
                chat_type=c["chat_type"],
                discord_channel_id=int(c["discord_channel_id"]),
                direction=c.get("direction", "both"),
                format=c.get("format", "**%user**: %message"),
            )
        )

    return BridgeConfig(wow=wow, discord=discord, channels=channels)
