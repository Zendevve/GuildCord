"""
Ties together the auth client, world client, and a discord.py bot to
actually relay chat both directions.
"""

from __future__ import annotations

import asyncio
import logging

import discord

from ..auth.auth_client import AuthClient
from ..config.schema import BridgeConfig, ChannelMapping
from ..world import opcodes as wop
from ..world import resolver
from ..world.chat import CHAT_TYPE_NAMES, ChatMessage
from ..world.world_client import WorldClient

log = logging.getLogger("guildcord")

CHAT_TYPE_BY_NAME = {
    "say": wop.CHAT_MSG_SAY,
    "party": wop.CHAT_MSG_PARTY,
    "raid": wop.CHAT_MSG_RAID,
    "guild": wop.CHAT_MSG_GUILD,
    "officer": wop.CHAT_MSG_OFFICER,
    "yell": wop.CHAT_MSG_YELL,
    "whisper": wop.CHAT_MSG_WHISPER,
    "channel": wop.CHAT_MSG_CHANNEL,
}


class WowBridge:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.world: WorldClient | None = None

        intents = discord.Intents.default()
        intents.message_content = True
        self.discord_client = discord.Client(intents=intents)
        self.discord_client.event(self.on_discord_message)
        self.discord_client.event(self.on_discord_ready)

    # -----------------------------------------------------------
    # WoW -> Discord
    # -----------------------------------------------------------

    def _find_mapping_for_wow_message(self, msg: ChatMessage) -> list[ChannelMapping]:
        matches = []
        for mapping in self.config.channels:
            if mapping.direction not in ("wow_to_discord", "both"):
                continue
            expected_type = CHAT_TYPE_BY_NAME.get(mapping.chat_type)
            if expected_type != msg.msg_type:
                continue
            if msg.msg_type == wop.CHAT_MSG_CHANNEL:
                if (mapping.wow_channel or "").lower() != (
                    msg.channel_name or ""
                ).lower():
                    continue
            matches.append(mapping)
        return matches

    async def on_wow_chat(self, msg: ChatMessage) -> None:
        type_name = CHAT_TYPE_NAMES.get(msg.msg_type, str(msg.msg_type))
        log.info("[WoW %s] guid=%s: %s", type_name, msg.sender_guid, msg.message)

        clean_message = resolver.strip_color_coding(msg.message)
        clean_message = resolver.resolve_links(
            clean_message,
            client_build=self.config.wow.client_build,
            link_site=self.config.discord.item_database,
        )

        mappings = self._find_mapping_for_wow_message(msg)
        for mapping in mappings:
            channel = self.discord_client.get_channel(mapping.discord_channel_id)
            if channel is None:
                log.warning(
                    "Discord channel %s not found/cached", mapping.discord_channel_id
                )
                continue
            sender = msg.sender_name or f"guid:{msg.sender_guid}"
            text = mapping.format.replace("%user", sender).replace(
                "%message", clean_message
            )
            await channel.send(text)

    # -----------------------------------------------------------
    # Discord -> WoW
    # -----------------------------------------------------------

    async def on_discord_ready(self) -> None:
        log.info("Discord bot ready as %s", self.discord_client.user)

    async def on_discord_message(self, message: "discord.Message") -> None:
        if message.author.bot:
            return
        if self.world is None:
            return

        for mapping in self.config.channels:
            if mapping.direction not in ("discord_to_wow", "both"):
                continue
            if message.channel.id != mapping.discord_channel_id:
                continue

            chat_type = CHAT_TYPE_BY_NAME.get(mapping.chat_type)
            if chat_type is None:
                continue

            content = f"[Discord] {message.author.display_name}: {message.content}"
            try:
                await self.world.send_chat(
                    chat_type, content, channel_name=mapping.wow_channel
                )
            except Exception:
                log.exception("failed to relay Discord message to WoW")

    # -----------------------------------------------------------
    # lifecycle
    # -----------------------------------------------------------

    async def connect_wow(self) -> None:
        cfg = self.config.wow
        auth = AuthClient(cfg.auth_host, cfg.auth_port, platform=cfg.platform)
        await auth.connect()
        login_result = await auth.login(cfg.account, cfg.password)
        await auth.close()
        log.info("Auth handshake OK, session key derived")

        world = WorldClient(
            host=cfg.auth_host,  # many private servers run world on same host
            port=cfg.world_port,
            username=cfg.account,
            session_key=login_result.session_key,
            client_build=cfg.client_build,
            realm_id=cfg.realm_id,
        )
        await world.connect()
        await world.handshake()
        log.info("World auth handshake OK")

        character_guid = cfg.character_guid
        if character_guid is None:
            chars = await world.request_characters()
            if not chars:
                raise RuntimeError(
                    "no characters found on this account — create one, or "
                    "set wow.character_guid in config"
                )
            character_guid = chars[0].guid
            log.info("Auto-selected character: %s (guid=%s)", chars[0].name, chars[0].guid)

        await world.enter_world(character_guid)
        log.info("Entered world successfully")

        for mapping in self.config.channels:
            if mapping.chat_type == "channel" and mapping.wow_channel:
                try:
                    await world.join_channel(mapping.wow_channel)
                except Exception:
                    log.exception("failed to join WoW channel %s", mapping.wow_channel)

        self.world = world

    async def run(self) -> None:
        logging.basicConfig(level=logging.INFO)
        await self.connect_wow()
        assert self.world is not None

        world_task = asyncio.create_task(self.world.run(self.on_wow_chat))
        try:
            await self.discord_client.start(self.config.discord.bot_token)
        finally:
            await self.world.close()
            world_task.cancel()
