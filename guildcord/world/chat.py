"""
Chat packet encode/decode for 3.3.5a.

SMSG_MESSAGECHAT (server -> client) body layout, per the widely
cross-verified structure used across TrinityCore/mangos-family servers
for this build:

    uint8   msg_type          (CHAT_MSG_* constant)
    int32   language
    uint64  sender_guid
    uint32  unk (flags, usually 0)
    -- then, depending on msg_type --
    if msg_type == CHAT_MSG_CHANNEL:
        cstring channel_name
    uint64  target_guid
    uint32  message_len       (includes null terminator)
    cstring message
    uint8   chat_tag

CMSG_MESSAGECHAT (client -> server) body layout:

    uint32  msg_type
    uint32  language
    -- then depending on type --
    if type == CHAT_MSG_WHISPER: cstring target_name
    if type == CHAT_MSG_CHANNEL: cstring channel_name
    cstring message
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import opcodes


@dataclass
class ChatMessage:
    msg_type: int
    language: int
    sender_guid: int
    message: str
    channel_name: str | None = None
    sender_name: str | None = None  # filled in later via CMSG_NAME_QUERY if desired


def _read_cstring(buf: bytes, offset: int) -> tuple[str, int]:
    end = buf.index(b"\x00", offset)
    return buf[offset:end].decode("utf-8", errors="replace"), end + 1


def decode_messagechat(body: bytes) -> ChatMessage:
    offset = 0
    msg_type = body[offset]
    offset += 1
    (language,) = struct.unpack_from("<i", body, offset)
    offset += 4
    (sender_guid,) = struct.unpack_from("<Q", body, offset)
    offset += 8
    # unk/flags field (uint32) — present for most message types on this build
    offset += 4

    channel_name = None
    if msg_type == opcodes.CHAT_MSG_CHANNEL:
        channel_name, offset = _read_cstring(body, offset)

    # target_guid (uint64) — receiver guid, not needed for a relay bot
    offset += 8

    (msg_len,) = struct.unpack_from("<I", body, offset)
    offset += 4
    message = body[offset : offset + msg_len - 1].decode("utf-8", errors="replace")
    offset += msg_len
    # trailing chat_tag (uint8) ignored

    return ChatMessage(
        msg_type=msg_type,
        language=language,
        sender_guid=sender_guid,
        message=message,
        channel_name=channel_name,
    )


def encode_messagechat(
    msg_type: int,
    message: str,
    language: int = opcodes.LANG_UNIVERSAL,
    target_name: str | None = None,
    channel_name: str | None = None,
) -> bytes:
    """Builds a CMSG_MESSAGECHAT body (header added separately by the caller)."""
    body = struct.pack("<II", msg_type, language)

    if msg_type == opcodes.CHAT_MSG_WHISPER:
        if not target_name:
            raise ValueError("whisper requires target_name")
        body += target_name.encode("utf-8") + b"\x00"
    elif msg_type == opcodes.CHAT_MSG_CHANNEL:
        if not channel_name:
            raise ValueError("channel message requires channel_name")
        body += channel_name.encode("utf-8") + b"\x00"

    body += message.encode("utf-8") + b"\x00"
    return body


CHAT_TYPE_NAMES = {
    opcodes.CHAT_MSG_SAY: "Say",
    opcodes.CHAT_MSG_PARTY: "Party",
    opcodes.CHAT_MSG_RAID: "Raid",
    opcodes.CHAT_MSG_GUILD: "Guild",
    opcodes.CHAT_MSG_OFFICER: "Officer",
    opcodes.CHAT_MSG_YELL: "Yell",
    opcodes.CHAT_MSG_WHISPER: "Whisper",
    opcodes.CHAT_MSG_EMOTE: "Emote",
    opcodes.CHAT_MSG_CHANNEL: "Channel",
    opcodes.CHAT_MSG_SYSTEM: "System",
}


def decode_guild_event(body: bytes) -> tuple[int, list[str]]:
    """
    Decodes SMSG_GUILD_EVENT body:
    uint8 event_type
    uint8 num_strings
    followed by num_strings null-terminated strings.
    """
    if len(body) < 2:
        raise ValueError("guild event packet too short")
    offset = 0
    event_type = body[offset]
    offset += 1
    num_strings = body[offset]
    offset += 1
    strings = []
    for _ in range(num_strings):
        if offset >= len(body):
            break
        end = body.index(b"\x00", offset)
        strings.append(body[offset:end].decode("utf-8", errors="replace"))
        offset = end + 1
    return event_type, strings


@dataclass
class GuildMemberInfo:
    guid: int
    is_online: bool
    name: str
    level: int
    char_class: int
    zone_id: int
    last_logoff: float


def decode_guild_roster(body: bytes) -> tuple[str, list[GuildMemberInfo]]:
    """
    Decodes SMSG_GUILD_ROSTER body for WotLK.
    Returns (motd, members_list).
    """
    if len(body) < 8:
        raise ValueError("guild roster packet too short")
    offset = 0
    (num_members,) = struct.unpack_from("<I", body, offset)
    offset += 4

    # Read motd string
    motd_end = body.index(b"\x00", offset)
    motd = body[offset:motd_end].decode("utf-8", errors="replace")
    offset = motd_end + 1

    # Read guild info string
    info_end = body.index(b"\x00", offset)
    _info = body[offset:info_end].decode("utf-8", errors="replace")
    offset = info_end + 1

    # Read ranks count and skip rank details (4 bytes each)
    (num_ranks,) = struct.unpack_from("<I", body, offset)
    offset += 4
    offset += num_ranks * 4  # skip rank rights/flags

    members = []
    for _ in range(num_members):
        if offset >= len(body):
            break
        (guid, is_online) = struct.unpack_from("<QB", body, offset)
        offset += 9

        name_end = body.index(b"\x00", offset)
        name = body[offset:name_end].decode("utf-8", errors="replace")
        offset = name_end + 1

        offset += 4  # skip rank ID (uint32)

        (level, char_class) = struct.unpack_from("<BB", body, offset)
        offset += 2

        (zone_id,) = struct.unpack_from("<I", body, offset)
        offset += 4

        last_logoff = 0.0
        if not is_online:
            (last_logoff,) = struct.unpack_from("<f", body, offset)
            offset += 4

        # Skip public note string
        note_end = body.index(b"\x00", offset)
        offset = note_end + 1

        # Skip officer note string
        off_end = body.index(b"\x00", offset)
        offset = off_end + 1

        members.append(
            GuildMemberInfo(
                guid=guid,
                is_online=bool(is_online),
                name=name,
                level=level,
                char_class=char_class,
                zone_id=zone_id,
                last_logoff=last_logoff,
            )
        )
    return motd, members
