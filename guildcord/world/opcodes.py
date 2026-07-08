"""
World-server opcode constants for 3.3.5a (build 12340).

Values verified directly against the `3.3.5` branch of TrinityCore's
Opcodes.h (github.com/TrinityCore/TrinityCore/blob/3.3.5/.../Opcodes.h),
which targets exactly this client build. Only the subset needed for a
chat bridge is included here.
"""

# --- auth handshake (unencrypted headers) ---
SMSG_AUTH_CHALLENGE = 0x1EC
CMSG_AUTH_SESSION = 0x1ED
SMSG_AUTH_RESPONSE = 0x1EE

# --- character screen ---
CMSG_CHAR_ENUM = 0x037
SMSG_CHAR_ENUM = 0x03B
CMSG_PLAYER_LOGIN = 0x03D
SMSG_LOGIN_VERIFY_WORLD = 0x236
SMSG_CHARACTER_LOGIN_FAILED = 0x041
CMSG_NAME_QUERY = 0x050
SMSG_NAME_QUERY = 0x051

# --- guild roster ---
CMSG_GUILD_ROSTER = 0x089
SMSG_GUILD_ROSTER = 0x08A

# --- chat ---
CMSG_MESSAGECHAT = 0x095
SMSG_MESSAGECHAT = 0x096
CMSG_JOIN_CHANNEL = 0x097
CMSG_LEAVE_CHANNEL = 0x098
SMSG_CHANNEL_NOTIFY = 0x099
SMSG_GUILD_EVENT = 0x092

# --- guild events ---
GE_PROMOTED = 0x00
GE_DEMOTED = 0x01
GE_MOTD = 0x02
GE_JOINED = 0x03
GE_LEFT = 0x04
GE_REMOVED = 0x05
GE_SIGNED_ON = 0x0C
GE_SIGNED_OFF = 0x0D

# --- keepalive ---
CMSG_PING = 0x1DC
SMSG_PONG = 0x1DD

# --- who query ---
CMSG_WHO = 0x062
SMSG_WHO = 0x063

# AuthResponse result codes (subset)
AUTH_OK = 0x0C
AUTH_UNKNOWN_ACCOUNT = 0x15

# Chat message types (subset relevant to a bridge bot)
CHAT_MSG_SAY = 0x00
CHAT_MSG_PARTY = 0x01
CHAT_MSG_RAID = 0x02
CHAT_MSG_GUILD = 0x03
CHAT_MSG_OFFICER = 0x04
CHAT_MSG_YELL = 0x05
CHAT_MSG_WHISPER = 0x06
CHAT_MSG_EMOTE = 0x0A
CHAT_MSG_CHANNEL = 0x11
CHAT_MSG_SYSTEM = 0x0F
CHAT_MSG_GUILD_ACHIEVEMENT = 0x31

# Language IDs (0 = universal, used for bridge-sent messages to avoid
# skill-based language filtering)
LANG_UNIVERSAL = 0
