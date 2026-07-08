"""
Auth-server (realmd) opcode constants for 3.3.5a (build 12340).
Values match the publicly documented WoW auth protocol.
"""

CMD_AUTH_LOGON_CHALLENGE = 0x00
CMD_AUTH_LOGON_PROOF = 0x01
CMD_AUTH_RECONNECT_CHALLENGE = 0x02
CMD_AUTH_RECONNECT_PROOF = 0x03
CMD_REALM_LIST = 0x10

# AuthLogonChallenge error/result codes
WOW_SUCCESS = 0x00
WOW_FAIL_UNKNOWN_ACCOUNT = 0x04
WOW_FAIL_INCORRECT_PASSWORD = 0x05
WOW_FAIL_VERSION_INVALID = 0x09

# Client build number for 3.3.5a
CLIENT_BUILD = 12340
CLIENT_LOCALE = "enUS"
CLIENT_OS = "Win"
CLIENT_PLATFORM = "x86"
