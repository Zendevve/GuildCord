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
