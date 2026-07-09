"""
Ties together the auth client, world client, and a discord.py bot to
actually relay chat both directions.
"""

from __future__ import annotations

import asyncio
import logging

import discord

from ..auth.auth_client import AuthClient, FatalAuthError
from ..common.backoff import BackoffPolicy
from ..config.schema import BridgeConfig, ChannelMapping
from ..world import opcodes as wop
from ..world import resolver
from ..world.chat import CHAT_TYPE_NAMES, ChatMessage, GuildMemberInfo, WhoMemberInfo
from ..world.world_client import FatalWorldError, WorldClient
from . import emoji, mentions
from .formatting import format_relay_message, matches_any_filter

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
    "emote": wop.CHAT_MSG_EMOTE,
    # System messages are server-generated (broadcasts, etc.) — WoW's
    # protocol doesn't have a way for a normal client to originate one,
    # so a mapping using this chat_type is realistically wow_to_discord
    # only, even though nothing here enforces that.
    "system": wop.CHAT_MSG_SYSTEM,
}


RACE_NAMES = {
    1: "Human",
    2: "Orc",
    3: "Dwarf",
    4: "Night Elf",
    5: "Undead",
    6: "Tauren",
    7: "Gnome",
    8: "Troll",
    10: "Blood Elf",
    11: "Draenei",
}

CLASS_NAMES = {
    1: "Warrior",
    2: "Paladin",
    3: "Hunter",
    4: "Rogue",
    5: "Priest",
    6: "Death Knight",
    7: "Shaman",
    8: "Mage",
    9: "Warlock",
    11: "Druid",
}

GENDER_NAMES = {
    0: "Male",
    1: "Female",
}


class WowBridge:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.world: WorldClient | None = None

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        self.discord_client = discord.Client(intents=intents)
        self.discord_client.event(self.on_discord_message)
        self.discord_client.event(self.on_discord_ready)

        self.guild_motd: str = ""
        self.guild_members: list[GuildMemberInfo] = []
        self.wow_character_name: str | None = None
        self.name_cache: dict[int, str] = {}
        self.pending_chat_queues: dict[int, list[ChatMessage]] = {}
        self.last_who_channel_id: int | None = None
        self.last_who_query: str | None = None

    # -----------------------------------------------------------
    # WoW -> Discord
    # -----------------------------------------------------------

    def _find_mapping_for_wow_message(self, msg: ChatMessage) -> list[ChannelMapping]:
        matches = []
        for mapping in self.config.channels:
            if mapping.direction not in ("wow_to_discord", "both"):
                continue
            expected_type = CHAT_TYPE_BY_NAME.get(mapping.chat_type)
            if msg.msg_type == wop.CHAT_MSG_GUILD_ACHIEVEMENT:
                if expected_type != wop.CHAT_MSG_GUILD:
                    continue
            else:
                if expected_type != msg.msg_type:
                    continue
            if msg.msg_type == wop.CHAT_MSG_CHANNEL:
                if (mapping.wow_channel or "").lower() != (
                     msg.channel_name or ""
                ).lower():
                    continue
            matches.append(mapping)
        return matches

    async def _send_wow_chat_to_discord(self, msg: ChatMessage) -> None:
        # Order matters here: resolve_links needs the hyperlink's own
        # |c........|H...|h|r markup intact to recognize it, and that
        # markup is itself shaped like a color span — if
        # strip_color_coding ran first it would eat the leading |c code
        # a hyperlink depends on, and resolve_links would never match.
        # strip_color_coding runs second to mop up any color codes that
        # aren't part of a link; it's safe to run after since resolved
        # link text never itself contains |c/|r sequences.
        clean_message = resolver.resolve_links(
            msg.message,
            link_site=self.config.discord.item_database,
        )
        clean_message = resolver.strip_color_coding(clean_message)

        mappings = self._find_mapping_for_wow_message(msg)
        for mapping in mappings:
            if matches_any_filter(mapping.filters, clean_message):
                continue

            channel = self.discord_client.get_channel(mapping.discord_channel_id)
            if channel is None:
                log.warning(
                    "Discord channel %s not found/cached", mapping.discord_channel_id
                )
                continue

            # Resolve WoW mentions (@User) to Discord tags
            resolved_message = mentions.resolve_wow_mentions(clean_message, channel)

            sender = msg.sender_name or f"guid:{msg.sender_guid}"
            channel_label = msg.channel_name or CHAT_TYPE_NAMES.get(msg.msg_type, "")
            if msg.msg_type == wop.CHAT_MSG_GUILD_ACHIEVEMENT:
                text = f"🏆 **{sender}** has earned the achievement {resolved_message}!"
            else:
                text = format_relay_message(
                    mapping.format,
                    user=sender,
                    message=resolved_message,
                    channel=channel_label,
                    time_format=self.config.discord.time_format,
                )
            try:
                await channel.send(text)
            except Exception:
                log.exception("failed to send message to Discord channel %s", mapping.discord_channel_id)

    async def on_wow_chat(self, msg: ChatMessage) -> None:
        type_name = CHAT_TYPE_NAMES.get(msg.msg_type, str(msg.msg_type))
        log.info("[WoW %s] guid=%s: %s", type_name, msg.sender_guid, msg.message)

        if msg.sender_guid == 0:
            await self._send_wow_chat_to_discord(msg)
            return

        if msg.sender_guid in self.name_cache:
            msg.sender_name = self.name_cache[msg.sender_guid]
            await self._send_wow_chat_to_discord(msg)
            return

        # Request name from server and queue the message
        if msg.sender_guid not in self.pending_chat_queues:
            self.pending_chat_queues[msg.sender_guid] = []
            try:
                if self.world:
                    await self.world.request_name_query(msg.sender_guid)
            except Exception:
                log.exception("failed to request name query for guid %s", msg.sender_guid)

        self.pending_chat_queues[msg.sender_guid].append(msg)

    async def on_wow_name_query_response(self, guid: int, name: str) -> None:
        log.info("Resolved name for guid %s -> %s", guid, name)
        self.name_cache[guid] = name

        if guid in self.pending_chat_queues:
            for msg in self.pending_chat_queues[guid]:
                msg.sender_name = name
                await self._send_wow_chat_to_discord(msg)
            del self.pending_chat_queues[guid]

    def should_send_directly(self, message: str) -> bool:
        if not message.startswith("."):
            return False
        cfg = self.config.discord
        if not cfg.enable_dot_commands:
            return False

        whitelist = cfg.dot_commands_whitelist
        if not whitelist:
            return True

        trimmed = message[1:].lower().strip()
        words = trimmed.split()
        if not words:
            return False
        first_word = words[0]

        if first_word in whitelist:
            return True

        # Check wildcard matching (e.g. "s*")
        for item in whitelist:
            if item.endswith("*"):
                prefix = item[:-1].lower()
                if trimmed.startswith(prefix):
                    return True

        return False

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

        # Handle local commands
        prefix = self.config.discord.command_prefix
        if message.content.startswith(prefix):
            parts = message.content[len(prefix):].strip().split()
            if parts:
                cmd = parts[0].lower()
                if cmd == "online" or (cmd == "who" and len(parts) == 1):
                    online_list = [m.name for m in self.guild_members if m.is_online]
                    if not online_list:
                        await message.channel.send("Currently no guild members online.")
                    else:
                        members_str = ", ".join(online_list)
                        await message.channel.send(
                            f"Currently {len(online_list)} member(s) online: {members_str}"
                        )
                    return
                elif cmd == "who" and len(parts) > 1:
                    query = " ".join(parts[1:])
                    self.last_who_channel_id = message.channel.id
                    self.last_who_query = query
                    try:
                        await self.world.request_who(query)
                    except Exception:
                        log.exception("failed to request world who query")
                    return
                elif cmd == "gmotd":
                    if self.guild_motd:
                        await message.channel.send(f"📢 **Guild MotD:** {self.guild_motd}")
                    else:
                        await message.channel.send("No Guild MotD has been fetched yet.")
                    return
                # If command prefix matched but command unrecognized, fall through (or ignore/return)
                # To prevent spamming raw unrecognized commands into WoW, we return here
                return

        # Discord's <:name:id> / <a:name:id> custom emoji markup can't
        # render in WoW — turn it into plain ":name:" text once, before
        # any per-mapping processing below.
        clean_content = emoji.resolve_discord_emoji(message.clean_content)

        for mapping in self.config.channels:
            if mapping.direction not in ("discord_to_wow", "both"):
                continue
            if message.channel.id != mapping.discord_channel_id:
                continue

            chat_type = CHAT_TYPE_BY_NAME.get(mapping.chat_type)
            if chat_type is None:
                continue

            if matches_any_filter(mapping.filters, clean_content):
                continue

            # If dot command option is enabled and matched, send directly. Otherwise send formatted.
            if self.should_send_directly(clean_content):
                content = clean_content
            else:
                content = f"[Discord] {message.author.display_name}: {clean_content}"
                if content.startswith("."):
                    content = " " + content

            try:
                await self.world.send_chat(
                    chat_type, content, channel_name=mapping.wow_channel
                )
            except Exception:
                log.exception("failed to relay Discord message to WoW")

    async def on_wow_guild_event(self, event_type: int, strings: list[str]) -> None:
        if not strings or not strings[0].strip():
            return

        actor = strings[0]
        # Skip events triggered by the bot's own character
        if event_type != wop.GE_MOTD and self.wow_character_name and actor.lower() == self.wow_character_name.lower():
            return

        # Find the Discord channel mapped to the WoW guild chat
        guild_channel_id = None
        for mapping in self.config.channels:
            if mapping.chat_type == "guild":
                guild_channel_id = mapping.discord_channel_id
                break

        if not guild_channel_id:
            return

        channel = self.discord_client.get_channel(guild_channel_id)
        if not channel:
            return

        # Format events into human-readable messages with rich emojis
        if event_type == wop.GE_SIGNED_ON:
            message = f"🟢 **{actor}** has logged on."
        elif event_type == wop.GE_SIGNED_OFF:
            message = f"🔴 **{actor}** has logged off."
        elif event_type == wop.GE_JOINED:
            message = f"🤝 **{actor}** has joined the guild."
        elif event_type == wop.GE_LEFT:
            message = f"🚶 **{actor}** has left the guild."
        elif event_type == wop.GE_MOTD:
            message = f"📢 **Guild Message of the Day:** {actor}"
        elif event_type == wop.GE_REMOVED:
            target = actor
            kicker = strings[1] if len(strings) > 1 else "someone"
            message = f"🥾 **{target}** was kicked by **{kicker}**."
        elif event_type == wop.GE_PROMOTED:
            promoter = actor
            target = strings[1] if len(strings) > 1 else "someone"
            rank = strings[2] if len(strings) > 2 else "new rank"
            message = f"🔼 **{target}** was promoted by **{promoter}** to **{rank}**."
        elif event_type == wop.GE_DEMOTED:
            demoter = actor
            target = strings[1] if len(strings) > 1 else "someone"
            rank = strings[2] if len(strings) > 2 else "lower rank"
            message = f"🔽 **{target}** was demoted by **{demoter}** to **{rank}**."
        else:
            return

        await channel.send(message)

    async def on_wow_guild_roster(self, motd: str, members: list[GuildMemberInfo]) -> None:
        self.guild_motd = motd
        self.guild_members = members

    async def on_wow_who_response(self, results: list[WhoMemberInfo]) -> None:
        if self.last_who_channel_id is None:
            return

        channel = self.discord_client.get_channel(self.last_who_channel_id)
        if channel is None:
            return

        query = self.last_who_query or ""

        if not results:
            # Check if there is an offline guild roster member matching the name
            offline_match = None
            for m in self.guild_members:
                if m.name.lower() == query.lower():
                    offline_match = m
                    break

            if offline_match:
                cls_name = CLASS_NAMES.get(offline_match.char_class, "Unknown Class")
                # Format last seen details
                days = int(offline_match.last_logoff)
                hours = int((offline_match.last_logoff * 24) % 24)
                minutes = int((offline_match.last_logoff * 24 * 60) % 60)

                minutes_str = f" {minutes} minute{'s' if minutes != 1 else ''}"
                hours_str = f" {hours} hour{'s' if hours != 1 else ''}," if hours > 0 else ""
                days_str = f" {days} day{'s' if days != 1 else ''}," if days > 0 else ""

                await channel.send(
                    f"**{offline_match.name}** is a level {offline_match.level} {cls_name} currently offline. "
                    f"Last seen{days_str}{hours_str}{minutes_str} ago."
                )
            else:
                await channel.send(f"No player matching '{query}' found online.")
        else:
            # Send at most 3 results
            for r in results[:3]:
                gender_str = GENDER_NAMES.get(r.gender, "")
                race_str = RACE_NAMES.get(r.race, "Unknown Race")
                class_str = CLASS_NAMES.get(r.char_class, "Unknown Class")
                guild_str = f" <{r.guild_name}>" if r.guild_name else ""
                gender_prefix = f" {gender_str}" if gender_str else ""

                await channel.send(
                    f"**{r.name}**{guild_str} is a level {r.level}{gender_prefix} {race_str} {class_str} currently in Zone {r.zone_id}."
                )

        self.last_who_channel_id = None
        self.last_who_query = None

    # -----------------------------------------------------------
    # lifecycle
    # -----------------------------------------------------------

    async def connect_wow(self) -> None:
        cfg = self.config.wow
        auth = AuthClient(cfg.auth_host, cfg.auth_port, platform=cfg.platform)
        try:
            await auth.connect()
            login_result = await auth.login(cfg.account, cfg.password)
        finally:
            # Always release the auth-server socket, whether login
            # succeeded or raised (including FatalAuthError).
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
        try:
            await world.connect()
            await world.handshake()
            log.info("World auth handshake OK")

            chars = await world.request_characters()
            character_name = None
            character_guid = cfg.character_guid
            if character_guid is None:
                if not chars:
                    raise RuntimeError(
                        "no characters found on this account — create one, or "
                        "set wow.character_guid in config"
                    )
                character_guid = chars[0].guid
                character_name = chars[0].name
                log.info("Auto-selected character: %s (guid=%s)", chars[0].name, chars[0].guid)
            else:
                for c in chars:
                    if c.guid == character_guid:
                        character_name = c.name
                        break

            self.wow_character_name = character_name

            await world.enter_world(character_guid)
            log.info("Entered world successfully")

            for mapping in self.config.channels:
                if mapping.chat_type == "channel" and mapping.wow_channel:
                    try:
                        await world.join_channel(mapping.wow_channel)
                    except Exception:
                        log.exception("failed to join WoW channel %s", mapping.wow_channel)
        except Exception:
            # Don't leak a half-open world-server socket across retries
            # — every failure path above lands here before we've
            # assigned `world` to self.world, so this is the only
            # place that would otherwise forget to close it.
            await world.close()
            raise

        self.world = world
        try:
            await world.request_guild_roster()
        except Exception:
            log.exception("failed to request initial guild roster")

    async def _notify_status(self, text: str) -> None:
        """Posts a connection-status update to the configured status
        channel, if any. Silently does nothing if unconfigured or if
        the channel isn't resolvable yet (e.g. Discord not ready)."""
        channel_id = self.config.discord.status_channel_id
        if not channel_id:
            return
        channel = self.discord_client.get_channel(channel_id)
        if channel is None:
            return
        try:
            await channel.send(text)
        except Exception:
            log.exception("failed to send status notification")

    async def run(self) -> None:
        logging.basicConfig(level=logging.INFO)

        # Start the Discord bot in the background
        discord_task = asyncio.create_task(
            self.discord_client.start(self.config.discord.bot_token)
        )

        cfg = self.config.wow
        backoff = BackoffPolicy(
            base_delay=cfg.reconnect_base_delay,
            max_delay=cfg.reconnect_max_delay,
        )
        ever_connected = False
        down_notified = False
        fatal_notified = False

        try:
            # Reconnection loop for WoW
            while not self.discord_client.is_closed():
                log.info("Connecting to WoW server...")
                try:
                    # Bound the whole connect sequence — a server that
                    # accepts the TCP connection but never responds
                    # would otherwise hang here indefinitely instead of
                    # hitting the backoff/retry logic below.
                    await asyncio.wait_for(self.connect_wow(), timeout=60.0)
                except (FatalAuthError, FatalWorldError) as exc:
                    # The server explicitly rejected our credentials —
                    # retrying at normal cadence just hammers it with
                    # the same bad login over and over. Back off hard
                    # and say so once, instead of spamming logs/Discord.
                    log.error("WoW login rejected (check credentials/config): %s", exc)
                    if not fatal_notified:
                        await self._notify_status(
                            f"⚠️ Can't log into the WoW account — the server "
                            f"rejected it (`{exc}`). Check `account`/`password` "
                            f"in config. I'll keep retrying every "
                            f"{int(cfg.reconnect_fatal_delay)}s, but this won't "
                            f"fix itself without a config change."
                        )
                        fatal_notified = True
                    await asyncio.sleep(cfg.reconnect_fatal_delay)
                    continue
                except Exception as exc:
                    log.error("Failed to connect to WoW server: %s", exc)
                    if ever_connected and not down_notified:
                        await self._notify_status(
                            "🔴 Lost connection to the WoW server. Reconnecting..."
                        )
                        down_notified = True
                    delay = backoff.next_delay()
                    log.info(
                        "Retrying in %.1fs (attempt %d)", delay, backoff.attempt
                    )
                    await asyncio.sleep(delay)
                    continue

                # Connected successfully — reset backoff and clear any
                # outage notifications from a prior failure streak.
                if down_notified or fatal_notified:
                    await self._notify_status("🟢 Reconnected to the WoW server.")
                backoff.reset()
                ever_connected = True
                down_notified = False
                fatal_notified = False

                log.info("Connected to WoW server. Running event listener...")

                # Start the periodic roster updater
                async def roster_updater():
                    while True:
                        await asyncio.sleep(60)
                        try:
                            if self.world:
                                await self.world.request_guild_roster()
                        except Exception:
                            pass

                roster_task = asyncio.create_task(roster_updater())

                try:
                    # Run the world client receive loop
                    await self.world.run(
                        self.on_wow_chat,
                        self.on_wow_guild_event,
                        self.on_wow_guild_roster,
                        self.on_wow_name_query_response,
                        self.on_wow_who_response,
                    )
                except Exception as exc:
                    log.error("WoW client run loop encountered error: %s", exc)
                finally:
                    roster_task.cancel()
                    if self.world:
                        await self.world.close()
                        self.world = None

                if self.discord_client.is_closed():
                    break

                log.info("Disconnected from WoW server.")
                if not down_notified:
                    await self._notify_status(
                        "🔴 Lost connection to the WoW server. Reconnecting..."
                    )
                    down_notified = True
                delay = backoff.next_delay()
                log.info("Retrying in %.1fs (attempt %d)", delay, backoff.attempt)
                await asyncio.sleep(delay)

        finally:
            await self.discord_client.close()
            await discord_task
