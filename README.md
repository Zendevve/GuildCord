# guildcord

A clientless WoW (3.3.5a / WotLK, build 12340) ↔ Discord chat bridge, built from
scratch against publicly documented protocol structures (wowdev.wiki opcode/packet
references and general SRP6 cryptographic specs) — not derived from any existing
bridge bot's source code.

## Why 3.3.5a first

WotLK 3.3.5a is the most heavily documented and most commonly emulated WoW client
version (TrinityCore, AzerothCore, etc. all target it), which makes protocol
verification easiest.

## High-level architecture

```
                +----------------+
                |  Discord Bot   |  discord.py, gateway connection
                +-------+--------+
                        |
                 message queue / router
                        |
        +---------------+----------------+
        |                                |
+-------v--------+              +--------v-------+
|  Auth client    |   session   |  World client   |
|  (port 3724)    +------key---->  (realm port,   |
|  SRP6 handshake |              |  usually 8085)  |
+-----------------+              +----------------+
                                          |
                                  chat packet codec
                                  (SMSG/CMSG_MESSAGECHAT)
```

### Modules

- `guildcord/auth/` — SRP6 handshake against the realmd/authserver (`AuthLogonChallenge`,
  `AuthLogonProof`), plus realmlist retrieval (`RealmList`).
- `guildcord/world/` — world-server session: `SMSG_AUTH_CHALLENGE` → `CMSG_AUTH_SESSION`
  → `SMSG_AUTH_RESPONSE`, RC4-based packet header encryption, and chat opcode
  encode/decode (`SMSG_MESSAGECHAT`, `CMSG_MESSAGECHAT`).
- `guildcord/discord_bridge/` — Discord gateway bot, channel routing.
- `guildcord/config/` — config schema + loader (YAML).

## Build order / status

1. [x] Project scaffold
2. [x] SRP6 auth handshake (`auth/srp6.py`, `auth/auth_client.py`) — self-test passes
3. [x] World server session + RC4 header crypto (`world/world_client.py`, `world/crypto.py`) — RC4 round-trip verified
4. [x] Chat packet encode/decode (`world/chat.py`) — encode/decode round-trip verified
5. [x] Discord bridge + config-driven routing (`discord_bridge/bot.py`, `config/schema.py`)

**This is an MVP, not a hardened client.** Everything above has been checked in
isolation (SRP6 math, RC4 header crypto, chat packet framing, config parsing)
but has **not yet been run against a live 3.3.5a server**, since that requires
an actual account on a real or private realm. Before relying on it:

- Run `python tests/test_srp6.py` to confirm the crypto self-test still
  passes in your environment.
- Point `main.py` at a real (ideally test/dev) server and watch the logs —
  the handshake either completes or fails loudly with a specific opcode/step,
  which tells you exactly where to look.
- The most likely failure point is `SMSG_CHAR_ENUM` parsing in
  `world_client.py` (see the big comment there) — it's the one packet whose
  exact byte layout varies slightly across TrinityCore/cmangos/vmangos forks.
  If it breaks, set `character_guid` in your config to skip it entirely.
- `CMSG_AUTH_SESSION`'s field list (region id, battlegroup id, dos response,
  etc.) was assembled from cross-referencing wowdev.wiki and the TrinityCore
  `3.3.5` branch opcode header, not from a packet capture — if a specific
  emulator core rejects it, capturing one real login with Wireshark and
  diffing against `_send_auth_session()` is the fastest fix.

## What's NOT implemented (by design, for a chat-only bridge)

Movement, object/entity tracking, spells, inventory, and everything else a
full client needs — this project only implements enough of the protocol to
authenticate, enter the world, and relay chat. `world_client.py`'s main loop
intentionally discards every opcode except `SMSG_MESSAGECHAT`.

## Legal note

This project is an original, clean-room implementation written by studying public
protocol documentation, not by reading or copying any existing bot's source (e.g.
GPL/AGPL-licensed bridge bots). It is proprietary software (see `LICENSE`), but consider
crediting the community protocol documentation you build against, since that's where the
actual research burden was done.
