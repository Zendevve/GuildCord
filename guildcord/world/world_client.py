"""
World-server session for 3.3.5a: completes the post-auth handshake
(SMSG_AUTH_CHALLENGE -> CMSG_AUTH_SESSION -> SMSG_AUTH_RESPONSE), enters
the world with a chosen character, and then runs a read loop that
dispatches decoded chat messages to a callback while keeping the
connection alive with CMSG_PING.

NOTE on SMSG_CHAR_ENUM parsing: this build's character-list packet has a
long, mostly-fixed-size per-character record (stats + 19 equipment
slots) documented at wowdev.wiki. That layout is the single most
failure-prone part of this client, since off-by-one field mistakes are
easy and can only really be caught against a live server capture. To
keep the bridge usable even if that parser needs adjustment, you can set
`character_guid` directly in the config to skip SMSG_CHAR_ENUM parsing
entirely and log straight into a known character.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import struct
import zlib
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from . import opcodes
from .chat import ChatMessage, decode_messagechat, encode_messagechat, decode_guild_event, decode_guild_roster, GuildMemberInfo, decode_name_query_response, decode_who_response, WhoMemberInfo
from .crypto import WorldCrypto

ChatCallback = Callable[[ChatMessage], Awaitable[None]]


class WorldError(Exception):
    """Raised for world-server protocol errors."""

    pass


class FatalWorldError(WorldError):
    """
    Raised when the world server explicitly rejects the auth session
    (bad account) rather than a transient issue. See FatalAuthError in
    auth_client.py for the same reasoning — no point retrying at normal
    cadence against a rejection that won't change on its own.
    """

    pass


class ConnectionStale(WorldError):
    """
    Raised when no packet arrives from the server for longer than
    `stale_timeout` seconds. WoW's world server doesn't always cleanly
    close a dead TCP connection (e.g. the process hung, or a NAT/firewall
    silently dropped it), so relying solely on read errors to detect a
    disconnect can leave the bridge stuck waiting indefinitely. This is
    a generic "the other end has gone quiet" timeout, not WoW-specific.
    """

    pass


@dataclass
class CharacterInfo:
    guid: int
    name: str
    level: int


class WorldClient:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        session_key: bytes,
        client_build: int = 12340,
        realm_id: int = 1,
        stale_timeout: float = 90.0,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.session_key = session_key
        self.client_build = client_build
        self.realm_id = realm_id
        # No packet at all (not even a ping reply) for this long means
        # the connection is dead even if the socket hasn't errored yet.
        # 90s = 3x the 30s ping interval, so we tolerate a couple of
        # missed beats before giving up.
        self.stale_timeout = stale_timeout

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._crypto: Optional[WorldCrypto] = None
        self._encrypted = False  # flips true right after CMSG_AUTH_SESSION is sent

        self.characters: list[CharacterInfo] = []
        self._chat_callback: Optional[ChatCallback] = None
        self._running = False

    # ---------------------------------------------------------------
    # low-level connection helpers
    # ---------------------------------------------------------------

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(
            self.host, self.port
        )

    async def close(self) -> None:
        self._running = False
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass

    async def _read_exact(self, n: int) -> bytes:
        assert self._reader is not None
        try:
            return await asyncio.wait_for(
                self._reader.readexactly(n), timeout=self.stale_timeout
            )
        except asyncio.TimeoutError as exc:
            raise ConnectionStale(
                f"no data from world server for {self.stale_timeout}s, "
                f"treating connection as dead"
            ) from exc

    async def _read_server_packet(self) -> tuple[int, bytes]:
        """
        Reads one SMSG packet, transparently decrypting the header if
        encryption is active. Returns (opcode, body).
        """
        header = await self._read_exact(4)
        if self._encrypted:
            assert self._crypto is not None
            header = self._crypto.decrypt_header(header)
        size, op = struct.unpack(">HH", header)
        # size includes the 2-byte opcode field but not the size field
        # itself; body length is therefore size - 2.
        body = await self._read_exact(size - 2)
        return op, body

    async def _send_client_packet(self, op: int, body: bytes) -> None:
        assert self._writer is not None
        # CMSG header is 6 bytes on this build: 2 (size, big-endian) +
        # 4 (opcode, little-endian). size covers the opcode field too.
        size = len(body) + 4
        header = struct.pack(">H", size) + struct.pack("<I", op)
        if self._encrypted:
            assert self._crypto is not None
            header = self._crypto.encrypt_header(header)
        self._writer.write(header + body)
        await self._writer.drain()

    # ---------------------------------------------------------------
    # handshake
    # ---------------------------------------------------------------

    async def _read_auth_challenge(self) -> int:
        """Reads the plaintext SMSG_AUTH_CHALLENGE, returns the server seed."""
        header = await self._read_exact(4)
        size, op = struct.unpack(">HH", header)
        if op != opcodes.SMSG_AUTH_CHALLENGE:
            raise WorldError(f"expected SMSG_AUTH_CHALLENGE, got opcode {op:#x}")
        body = await self._read_exact(size - 2)
        # body: uint32 unk(=1), uint32 server_seed, uint8[16] unk2, uint8[16] unk3
        _unk, server_seed = struct.unpack_from("<II", body, 0)
        return server_seed

    def _compute_session_proof(self, client_seed: int, server_seed: int) -> bytes:
        """
        digest = SHA1( ACCOUNT + 0x00000000 + clientSeed + serverSeed + K )
        This mirrors the server-side check in WorldSession::HandleAuthSession
        across the mangos/TrinityCore family for this build.
        """
        h = hashlib.sha1()
        h.update(self.username.upper().encode("ascii"))
        h.update(b"\x00\x00\x00\x00")
        h.update(struct.pack("<I", client_seed))
        h.update(struct.pack("<I", server_seed))
        h.update(self.session_key)
        return h.digest()

    async def _send_auth_session(self, client_seed: int, server_seed: int) -> None:
        assert self._writer is not None
        digest = self._compute_session_proof(client_seed, server_seed)
        account_bytes = self.username.upper().encode("ascii") + b"\x00"

        # No addon data: send a zlib-compressed empty addon block, which
        # is what a client with no addons effectively produces.
        addon_info = zlib.compress(b"\x00" * 4)

        body = struct.pack("<I", self.client_build)
        body += struct.pack("<I", 0)  # login server id / unk
        body += account_bytes
        body += struct.pack("<I", 0)  # login server type
        body += struct.pack("<I", client_seed)
        body += struct.pack("<I", 0)  # region id
        body += struct.pack("<I", 0)  # battlegroup id
        body += struct.pack("<I", self.realm_id)
        body += struct.pack("<Q", 0)  # dos response (unchecked by most emu cores)
        body += digest
        body += struct.pack("<I", len(addon_info))
        body += addon_info

        # CMSG_AUTH_SESSION is sent with a PLAINTEXT header (one of the
        # two exceptions), even though everything after it is encrypted.
        size = len(body) + 4  # opcode is 4 bytes on the wire for CMSG
        header = struct.pack(">H", size) + struct.pack("<I", opcodes.CMSG_AUTH_SESSION)
        self._writer.write(header + body)
        await self._writer.drain()

        # From this point on, ALL packet headers (both directions) are
        # RC4-encrypted using the session key.
        self._crypto = WorldCrypto(self.session_key)
        self._encrypted = True

    async def _read_auth_response(self) -> None:
        op, body = await self._read_server_packet()
        if op != opcodes.SMSG_AUTH_RESPONSE:
            raise WorldError(f"expected SMSG_AUTH_RESPONSE, got opcode {op:#x}")
        result = body[0]
        if result != opcodes.AUTH_OK:
            if result == opcodes.AUTH_UNKNOWN_ACCOUNT:
                raise FatalWorldError(
                    f"world server rejected auth session — unknown account, "
                    f"code={result:#x}"
                )
            raise WorldError(f"world server rejected auth session, code={result:#x}")

    async def handshake(self) -> None:
        """Runs SMSG_AUTH_CHALLENGE -> CMSG_AUTH_SESSION -> SMSG_AUTH_RESPONSE."""
        server_seed = await self._read_auth_challenge()
        client_seed = int.from_bytes(os.urandom(4), "little")
        await self._send_auth_session(client_seed, server_seed)
        await self._read_auth_response()

    # ---------------------------------------------------------------
    # character enum + login
    # ---------------------------------------------------------------

    async def request_characters(self) -> list[CharacterInfo]:
        await self._send_client_packet(opcodes.CMSG_CHAR_ENUM, b"")
        op, body = await self._read_server_packet()
        if op != opcodes.SMSG_CHAR_ENUM:
            raise WorldError(f"expected SMSG_CHAR_ENUM, got opcode {op:#x}")

        chars: list[CharacterInfo] = []
        try:
            count = body[0]
            offset = 1
            for _ in range(count):
                (guid,) = struct.unpack_from("<Q", body, offset)
                offset += 8
                name_end = body.index(b"\x00", offset)
                name = body[offset:name_end].decode("utf-8", errors="replace")
                offset = name_end + 1
                # race, class, gender, skin, face, hairStyle, hairColor,
                # facialHair, level = 9 single bytes
                fields = struct.unpack_from("<9B", body, offset)
                level = fields[8]
                offset += 9
                chars.append(CharacterInfo(guid=guid, name=name, level=level))
                # Remaining per-character fields (zone, map, position,
                # guild, flags, pet info, 19 equipment slots) are fixed
                # size but version/branch-sensitive; rather than risk
                # silently misparsing subsequent characters we stop
                # after the first successfully parsed one, which is
                # enough for a bridge bot that logs in as one character.
                break
        except (struct.error, IndexError, ValueError) as exc:
            raise WorldError(
                "failed to parse SMSG_CHAR_ENUM — this packet's layout is "
                "the most version-sensitive part of the protocol; set "
                "character_guid in config to bypass parsing entirely"
            ) from exc

        self.characters = chars
        return chars

    async def enter_world(self, character_guid: int) -> None:
        await self._send_client_packet(
            opcodes.CMSG_PLAYER_LOGIN, struct.pack("<Q", character_guid)
        )
        # Drain packets until we see SMSG_LOGIN_VERIFY_WORLD (or a
        # failure), ignoring everything else the server sends during
        # world-enter (tutorial flags, initial spells, object updates,
        # etc. — none of which a chat-only bridge needs to understand).
        for _ in range(200):
            op, body = await self._read_server_packet()
            if op == opcodes.SMSG_LOGIN_VERIFY_WORLD:
                return
            if op == opcodes.SMSG_CHARACTER_LOGIN_FAILED:
                reason = body[0] if body else -1
                raise WorldError(f"character login failed, reason={reason}")
        raise WorldError("timed out waiting for SMSG_LOGIN_VERIFY_WORLD")

    # ---------------------------------------------------------------
    # chat send/receive + main loop
    # ---------------------------------------------------------------

    async def send_chat(
        self,
        msg_type: int,
        message: str,
        channel_name: Optional[str] = None,
        target_name: Optional[str] = None,
    ) -> None:
        body = encode_messagechat(
            msg_type, message, channel_name=channel_name, target_name=target_name
        )
        await self._send_client_packet(opcodes.CMSG_MESSAGECHAT, body)

    async def join_channel(self, channel_name: str, password: str = "") -> None:
        body = struct.pack("<I", 0)  # channel id, 0 = resolve by name
        body += b"\x00\x00"  # unk flags (byte) + unk (byte), commonly zero
        body += channel_name.encode("utf-8") + b"\x00"
        body += password.encode("utf-8") + b"\x00"
        await self._send_client_packet(opcodes.CMSG_JOIN_CHANNEL, body)

    async def request_guild_roster(self) -> None:
        await self._send_client_packet(opcodes.CMSG_GUILD_ROSTER, b"")

    async def request_name_query(self, guid: int) -> None:
        body = struct.pack("<Q", guid)
        await self._send_client_packet(opcodes.CMSG_NAME_QUERY, body)

    async def request_who(self, query: str) -> None:
        # Build who message
        # WotLK format:
        # uint32 level_min (0)
        # uint32 level_max (100)
        # cstring player_name (query)
        # cstring guild_name ("")
        # uint32 race_mask (0xFFFFFFFF)
        # uint32 class_mask (0xFFFFFFFF)
        # uint32 zones_count (0)
        # uint32 strings_count (0)
        body = struct.pack("<II", 0, 100)
        body += query.encode("utf-8") + b"\x00"
        body += b"\x00"  # guild name (empty)
        body += struct.pack("<IIII", 0xFFFFFFFF, 0xFFFFFFFF, 0, 0)
        await self._send_client_packet(opcodes.CMSG_WHO, body)

    async def _send_ping(self, sequence: int) -> None:
        body = struct.pack("<II", sequence, 50)  # sequence, latency(ms) placeholder
        await self._send_client_packet(opcodes.CMSG_PING, body)

    async def run(
        self,
        on_chat: ChatCallback,
        on_guild_event: Callable[[int, list[str]], Awaitable[None]] | None = None,
        on_guild_roster: Callable[[str, list[GuildMemberInfo]], Awaitable[None]] | None = None,
        on_name_query_response: Callable[[int, str], Awaitable[None]] | None = None,
        on_who_response: Callable[[list[WhoMemberInfo]], Awaitable[None]] | None = None,
    ) -> None:
        """
        Main receive loop. Dispatches SMSG_MESSAGECHAT, SMSG_GUILD_EVENT,
        SMSG_GUILD_ROSTER, SMSG_NAME_QUERY, and SMSG_WHO to their respective callbacks.
        """
        self._chat_callback = on_chat
        self._running = True
        ping_seq = 0

        async def ping_loop():
            nonlocal ping_seq
            while self._running:
                await asyncio.sleep(30)
                ping_seq += 1
                try:
                    await self._send_ping(ping_seq)
                except Exception:
                    break

        ping_task = asyncio.create_task(ping_loop())
        try:
            while self._running:
                op, body = await self._read_server_packet()
                if op == opcodes.SMSG_MESSAGECHAT:
                    try:
                        msg = decode_messagechat(body)
                    except (struct.error, IndexError, ValueError):
                        continue
                    await on_chat(msg)
                elif op == opcodes.SMSG_GUILD_EVENT:
                    if on_guild_event:
                        try:
                            event_type, strings = decode_guild_event(body)
                        except (struct.error, IndexError, ValueError):
                            continue
                        await on_guild_event(event_type, strings)
                elif op == opcodes.SMSG_GUILD_ROSTER:
                    if on_guild_roster:
                        try:
                            motd, members = decode_guild_roster(body)
                        except (struct.error, IndexError, ValueError):
                            continue
                        await on_guild_roster(motd, members)
                elif op == opcodes.SMSG_NAME_QUERY:
                    if on_name_query_response:
                        try:
                            guid, name = decode_name_query_response(body)
                        except (struct.error, IndexError, ValueError):
                            continue
                        await on_name_query_response(guid, name)
                elif op == opcodes.SMSG_WHO:
                    if on_who_response:
                        try:
                            results = decode_who_response(body)
                        except (struct.error, IndexError, ValueError):
                            continue
                        await on_who_response(results)
        finally:
            ping_task.cancel()
            self._running = False
