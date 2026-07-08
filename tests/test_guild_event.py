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


def test_decode_guild_roster():
    # Constructing a sample WotLK SMSG_GUILD_ROSTER packet body:
    # num_members (uint32) = 2
    # motd (cstring) = "Welcome to the guild!"
    # info (cstring) = "Info info"
    # num_ranks (uint32) = 1
    # rank rights/flags (num_ranks * uint32) = 1 * [0x00000001]
    # Member 1:
    #   guid (uint64) = 12345
    #   is_online (uint8) = 1
    #   name (cstring) = "Bob"
    #   rank (uint32) = 0
    #   level (uint8) = 80
    #   char_class (uint8) = 1 (Warrior)
    #   zone_id (uint32) = 1519 (Stormwind City)
    #   last_logoff (not present since online)
    #   public note (cstring) = "Main Tank"
    #   officer note (cstring) = "Officer Note"
    # Member 2:
    #   guid (uint64) = 67890
    #   is_online (uint8) = 0
    #   name (cstring) = "Alice"
    #   rank (uint32) = 1
    #   level (uint8) = 70
    #   char_class (uint8) = 4 (Rogue)
    #   zone_id (uint32) = 1657 (Darnassus)
    #   last_logoff (float32) = 1.5 (days)
    #   public note (cstring) = "Alt"
    #   officer note (cstring) = "Alt Note"
    
    import struct
    
    body = struct.pack("<I", 2)
    body += b"Welcome to the guild!\x00"
    body += b"Info info\x00"
    body += struct.pack("<II", 1, 0x00000001)
    
    # Member 1
    body += struct.pack("<QB", 12345, 1)
    body += b"Bob\x00"
    body += struct.pack("<IBBI", 0, 80, 1, 1519)
    body += b"Main Tank\x00"
    body += b"Officer Note\x00"
    
    # Member 2
    body += struct.pack("<QB", 67890, 0)
    body += b"Alice\x00"
    body += struct.pack("<IBBIf", 1, 70, 4, 1657, 1.5)
    body += b"Alt\x00"
    body += b"Alt Note\x00"
    
    motd, members = chat.decode_guild_roster(body)
    assert motd == "Welcome to the guild!"
    assert len(members) == 2
    
    assert members[0].guid == 12345
    assert members[0].is_online is True
    assert members[0].name == "Bob"
    assert members[0].level == 80
    assert members[0].char_class == 1
    assert members[0].zone_id == 1519
    assert members[0].last_logoff == 0.0
    
    assert members[1].guid == 67890
    assert members[1].is_online is False
    assert members[1].name == "Alice"
    assert members[1].level == 70
    assert members[1].char_class == 4
    assert members[1].zone_id == 1657
    assert members[1].last_logoff == 1.5
    
    print("test_decode_guild_roster passed.")


def test_decode_name_query_response():
    # Constructing a sample WotLK SMSG_NAME_QUERY packet body:
    # Packed GUID: mask=0x01, val=123 (equivalent to 123)
    # name_known (uint8) = 0
    # name (cstring) = "Bob"
    # realm_name (cstring) = ""
    # race (uint8) = 1
    # gender (uint8) = 0
    # char_class (uint8) = 1
    import struct
    body = struct.pack("<BB", 0x01, 123)  # packed guid: mask 1, val 123
    body += struct.pack("<B", 0)           # name known = 0 (yes)
    body += b"Bob\x00"                     # name
    body += b"\x00"                        # realm name (empty)
    body += struct.pack("<BBB", 1, 0, 1)   # race, gender, class
    
    guid, name = chat.decode_name_query_response(body)
    assert guid == 123
    assert name == "Bob"
    print("test_decode_name_query_response passed.")


def test_decode_messagechat_achievement():
    # Constructing a sample WotLK SMSG_MESSAGECHAT packet for CHAT_MSG_GUILD_ACHIEVEMENT:
    # msg_type = 0x31 (CHAT_MSG_GUILD_ACHIEVEMENT)
    # language = -1 (LANG_UNIVERSAL or similar)
    # sender_guid = 11111
    # unk = 0
    # target_guid = 0
    # message = "earned achievement link..."
    # chat_tag = 0
    # achievement_id = 1180
    import struct
    msg_bytes = b"earned achievement link\x00"
    body = struct.pack("<BiQIQ", 0x31, -1, 11111, 0, 0)
    body += struct.pack("<I", len(msg_bytes))
    body += msg_bytes
    body += struct.pack("<BI", 0, 1180) # chat_tag, achievement_id
    
    msg = chat.decode_messagechat(body)
    assert msg.msg_type == 0x31
    assert msg.sender_guid == 11111
    assert msg.message == "earned achievement link"
    assert msg.achievement_id == 1180
    print("test_decode_messagechat_achievement passed.")


def test_decode_who_response():
    # Constructing a sample WotLK SMSG_WHO packet body:
    # display_count (uint32) = 1
    # match_count (uint32) = 1
    # Player 1:
    #   name (cstring) = "Bob"
    #   guild (cstring) = "Knights of Stormwind"
    #   level (uint32) = 80
    #   char_class (uint32) = 1 (Warrior)
    #   race (uint32) = 1 (Human)
    #   gender (uint8) = 0 (Male)
    #   zone_id (uint32) = 1519 (Stormwind City)
    import struct
    body = struct.pack("<II", 1, 1)
    body += b"Bob\x00"
    body += b"Knights of Stormwind\x00"
    body += struct.pack("<IIIBI", 80, 1, 1, 0, 1519)

    results = chat.decode_who_response(body)
    assert len(results) == 1
    assert results[0].name == "Bob"
    assert results[0].guild_name == "Knights of Stormwind"
    assert results[0].level == 80
    assert results[0].char_class == 1
    assert results[0].race == 1
    assert results[0].gender == 0
    assert results[0].zone_id == 1519
    print("test_decode_who_response passed.")


if __name__ == "__main__":
    test_decode_guild_event()
    test_decode_guild_roster()
    test_decode_name_query_response()
    test_decode_messagechat_achievement()
    test_decode_who_response()
