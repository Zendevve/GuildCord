"""
Tests for guild event packet decoding.
Run with: python tests/test_guild_event.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from guildcord.world import chat
from guildcord.world import opcodes


def test_decode_guild_event():
    # 1. Simple Join event: type = 0x03, 1 string ("Alice")
    # body payload format: event_type (1 byte) + num_strings (1 byte) + string0 + null terminator
    body = bytes([0x03, 0x01]) + b"Alice\x00"

    event_type, strings = chat.decode_guild_event(body)
    assert event_type == opcodes.GE_JOINED
    assert strings == ["Alice"]

    # 2. Promotion event: type = 0x00, 3 strings ("Bob", "Charlie", "Officer")
    body = bytes([0x00, 0x03]) + b"Bob\x00" + b"Charlie\x00" + b"Officer\x00"

    event_type, strings = chat.decode_guild_event(body)
    assert event_type == opcodes.GE_PROMOTED
    assert strings == ["Bob", "Charlie", "Officer"]

    print("All guild event decoding tests passed successfully.")


if __name__ == "__main__":
    test_decode_guild_event()
