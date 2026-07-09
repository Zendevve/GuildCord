# GuildCord

A clientless **World of Warcraft 3.3.5a (WotLK, build 12340) ↔ Discord chat bridge**, written from scratch in Python against publicly documented protocol structures (wowdev.wiki opcode/packet references and general SRP6 cryptographic specs). It is **not derived from any existing bridge bot's source code**.

> **Status:** Feature-complete MVP. All protocol modules have unit-test coverage and have been verified in isolation, but live-server testing requires an actual 3.3.5a realm account.

---

## Table of Contents

- [Features](#features)
- [Why 3.3.5a first](#why-335a-first)
- [High-level architecture](#high-level-architecture)
- [Project structure](#project-structure)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Discord commands](#discord-commands)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)
- [What's not implemented](#whats-not-implemented)
- [Legal note](#legal-note)

---

## Features

- **Two-way chat relay** between WoW and Discord for:
  - `say`, `yell`, `whisper`, `emote`, `channel`
  - `guild`, `officer`, `system`
  - Guild achievements
- **Guild event notifications** to Discord:
  - Member signed on / signed off
  - Member joined / left / was kicked
  - Member promoted / demoted
  - Guild Message of the Day (MOTD)
- **Guild roster & online tracking** with Discord `!online` and `!who` commands.
- **Mention resolution**: `@DiscordUser` or `@"Role Name"` typed in WoW can be resolved to real Discord mentions when relayed.
- **Item/spell/quest/achievement link resolution** from WoW hyperlink markup to clickable Markdown (opt-in via `item_database`).
- **Custom message formatting** per channel mapping with `%time`, `%channel`, `%user`, and `%message` tokens.
- **Regex-based filtering** per mapping to block gold-seller spam, Discord invites, etc.
- **Automatic reconnection** with separate backoff strategies for network blips vs. bad credentials.
- **Status notifications** to a Discord channel when the WoW connection drops or recovers.
- **Direct server commands** (dot commands) from Discord can be optionally enabled and whitelisted.

---

## Why 3.3.5a first

WotLK 3.3.5a is the most heavily documented and most commonly emulated WoW client version (TrinityCore, AzerothCore, etc. all target it), which makes protocol verification easiest. The same building blocks can be adapted to other client builds later.

---

## High-level architecture

```text
                +----------------+
                |  Discord Bot   |  discord.py, gateway connection
                +-------+--------+
                        |
                 message queue / router
                        |
        +---------------+----------------+
        |                                |
+-------v--------+              +--------v-------+
|  Auth client   |   session    |  World client  |
|  (port 3724)   |   key        |  (realm port,  |
|  SRP6 handshake+------------->|  usually 8085) |
+----------------+              +----------------+
                                         |
                                 chat packet codec
                                 (SMSG/CMSG_MESSAGECHAT)
```

### Modules

| Path | Responsibility |
|------|----------------|
| `guildcord/auth/` | SRP6 handshake against the realmd/authserver (`AuthLogonChallenge`, `AuthLogonProof`). |
| `guildcord/world/` | World-server session: `SMSG_AUTH_CHALLENGE` → `CMSG_AUTH_SESSION` → `SMSG_AUTH_RESPONSE`, RC4-based packet header encryption, and chat opcode encode/decode (`SMSG_MESSAGECHAT`, `CMSG_MESSAGECHAT`). |
| `guildcord/discord_bridge/` | Discord gateway bot, channel routing, formatting, mention resolution, emoji cleanup, and link resolution. |
| `guildcord/config/` | YAML config schema + loader. |
| `guildcord/common/` | Generic helpers such as exponential backoff with jitter. |
| `tests/` | Unit tests for SRP6, auth error classification, backoff, formatting, emoji, resolver, guild events, and mentions. |

---

## Quick start

1. **Install dependencies** (Python 3.10+ required):

   ```bash
   pip install -r requirements.txt
   ```

2. **Copy and edit the config**:

   ```bash
   cp config.example.yaml config.yaml
   ```

   Fill in `wow:` (server address, account, password, ports) and `discord:` (bot token) sections. See [SETUP.md](SETUP.md) for a step-by-step walkthrough.

3. **Run the self-tests** to confirm the crypto and protocol helpers are healthy:

   ```bash
   python tests/test_srp6.py
   python tests/test_auth_errors.py
   python tests/test_backoff.py
   python tests/test_formatting.py
   python tests/test_emoji.py
   python tests/test_resolver.py
   python tests/test_guild_event.py
   python tests/test_mentions.py
   ```

   Or, if you have pytest:

   ```bash
   pytest
   ```

4. **Start the bridge**:

   ```bash
   python main.py              # reads ./config.yaml by default
   python main.py other.yaml   # or point it at a specific file
   ```

On a clean startup you should see logs similar to:

```text
Connecting to WoW server...
Auth handshake OK, session key derived
World auth handshake OK
Auto-selected character: YourCharName (guid=...)
Entered world successfully
Connected to WoW server. Running event listener...
Discord bot ready as YourBot#1234
```

---

## Configuration

The config file is YAML. The key sections are:

- `wow:` — server connection and account details.
- `discord:` — bot token, command prefix, optional status channel, item database URL, dot-command settings.
- `channels:` — one entry per WoW-chat-type ↔ Discord-channel pairing.

### Example channel mapping

```yaml
channels:
  - chat_type: "guild"
    discord_channel_id: 222222222222222222
    direction: "both"
    format: "🛡️ **%user**: %message"

  - chat_type: "channel"
    wow_channel: "General"
    discord_channel_id: 333333333333333333
    direction: "both"
    format: "[%time] [%channel] **%user**: %message"

  - chat_type: "system"
    discord_channel_id: 555555555555555555
    direction: "wow_to_discord"  # system messages cannot originate from Discord
    format: "📜 %message"
```

### Direction values

| Value | Meaning |
|-------|---------|
| `both` | Messages flow both ways. |
| `wow_to_discord` | Only relay WoW chat to Discord. |
| `discord_to_wow` | Only relay Discord chat to WoW. |

### Format tokens

| Token | Replaced with |
|-------|---------------|
| `%time` | Local timestamp (strftime format from `discord.time_format`). |
| `%channel` | WoW channel name (for `chat_type: channel`) or chat type label. |
| `%user` | Sender name. |
| `%message` | Message text. |

### Useful optional fields

- `wow.character_guid` — skip auto character enumeration and log straight into a known character.
- `wow.platform` — `"Windows"` (default) or `"Mac"`; affects the auth challenge platform/OS fields.
- `discord.item_database` — query-string-style database URL (e.g. `https://wotlkdb.com`) for clickable item/spell/quest/achievement links.
- `discord.status_channel_id` — Discord channel ID for connection status notifications.
- `discord.enable_dot_commands` / `discord.dot_commands_whitelist` — allow selected server commands (e.g. `.s info`) to be sent directly from Discord.
- `channels[].filters` — list of regexes; messages matching any pattern are silently dropped for that mapping.

See the comments in [`config.example.yaml`](config.example.yaml) for the full option list.

---

## Discord commands

GuildCord responds to messages starting with the configured `command_prefix` (default `!`):

| Command | Description |
|---------|-------------|
| `!online` | Lists guild members currently online. |
| `!who <name>` | Queries the server `/who` list for a player name. If offline but in the guild roster, reports last-seen time. |
| `!gmotd` | Shows the latest guild Message of the Day. |

---

## Tests

The test suite covers the protocol pieces that can be verified without a live realm:

| Test file | What it checks |
|-----------|----------------|
| `tests/test_srp6.py` | Full client/server SRP6 round-trip and session-key derivation. |
| `tests/test_auth_errors.py` | Fatal vs. retryable auth rejection classification. |
| `tests/test_backoff.py` | Exponential backoff with jitter and capping. |
| `tests/test_formatting.py` | Message template substitution and regex filtering. |
| `tests/test_emoji.py` | Discord custom emoji markup → plain text. |
| `tests/test_resolver.py` | WoW color-code stripping and item/spell/quest/achievement link resolution. |
| `tests/test_guild_event.py` | Guild event, roster, name query, achievement, and `/who` packet decoding. |
| `tests/test_mentions.py` | WoW `@name` → Discord mention resolution. |

Run all tests with:

```bash
pytest
```

---

## Troubleshooting

- **`SMSG_CHAR_ENUM` parse error** — this packet's exact byte layout varies slightly across emulator forks. Set `wow.character_guid` in config to skip parsing entirely; get the GUID from your server's character table.
- **Repeated "bad credentials" errors** — double-check `wow.account`, `wow.password`, and `wow.realm_id`. These are treated as fatal and use a separate, slower retry delay (`reconnect_fatal_delay`).
- **Bot connects to WoW but nothing relays to Discord** — usually a `discord_channel_id` mismatch, or the Discord **Message Content Intent** is not enabled.
- **Bot connects to Discord but nothing relays to WoW** — check that the mapping's `direction` includes `discord_to_wow`.
- **Custom emoji appear as raw `<:name:id>` in WoW** — `emoji.py` converts these to `:name:` before relaying; Unicode emoji pass through untouched.
- **Item/spell links show as bold text instead of clickable URLs** — set `discord.item_database` to a query-string-style database site. Wowhead-style path URLs are not supported.

---

## What's not implemented

Movement, object/entity tracking, spells, inventory, and everything else a full client needs — this project only implements enough of the protocol to authenticate, enter the world, and relay chat. `world_client.py`'s main loop intentionally discards every opcode except chat, guild events, roster, name queries, and ping responses.

---

## Legal note

This project is an original, clean-room implementation written by studying public protocol documentation, not by reading or copying any existing bot's source (e.g. GPL/AGPL-licensed bridge bots). It is proprietary software (see [`LICENSE`](LICENSE)), but consider crediting the community protocol documentation you build against, since that's where the actual research burden was done.
