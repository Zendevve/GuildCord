"""
Tests for WoW-to-Discord mentions resolution.
Run with: python tests/test_mentions.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from guildcord.discord_bridge import mentions


class MockRole:
    def __init__(self, id, name):
        self.id = id
        self.name = name


class MockMember:
    def __init__(self, id, name, display_name=None, nick=None):
        self.id = id
        self.name = name
        self.display_name = display_name or name
        self.nick = nick


class MockGuild:
    def __init__(self, roles, me_id=999):
        self.roles = roles
        self.me = MockMember(me_id, "BridgeBot")


class MockTextChannel:
    def __init__(self, guild, members):
        self.guild = guild
        self.members = members


def test_resolve_wow_mentions():
    role_officer = MockRole(555, "Officer")
    role_mod = MockRole(666, "Moderator")
    roles = [role_officer, role_mod]

    guild = MockGuild(roles)

    member_alice = MockMember(101, "alice", display_name="Alice In Wonderland")
    member_bob = MockMember(102, "bob", nick="Bobby")
    members = [member_alice, member_bob]

    channel = MockTextChannel(guild, members)

    # 1. Test exact match role
    msg = "Pinging @Officer and @everyone"
    # @everyone is ignored, @Officer is resolved
    expected = "Pinging <@&555> and @everyone"
    assert mentions.resolve_wow_mentions(msg, channel) == expected

    # 2. Test exact match user name / nickname
    msg = "Hello @alice and @Bobby!"
    expected = "Hello <@101> and <@102>!"
    assert mentions.resolve_wow_mentions(msg, channel) == expected

    # 3. Test multi-word quoted name
    msg = 'Hey @"Alice In Wonderland"!'
    expected = "Hey <@101>!"
    assert mentions.resolve_wow_mentions(msg, channel) == expected

    # 4. Test partial word match (tag is a word in display name)
    msg = "Ping @Wonderland"
    expected = "Ping <@101>"
    assert mentions.resolve_wow_mentions(msg, channel) == expected

    # 5. Test no match / ambiguous match
    msg = "Ping @Unknown"
    assert mentions.resolve_wow_mentions(msg, channel) == msg

    print("All mentions tests passed successfully.")


if __name__ == "__main__":
    test_resolve_wow_mentions()
