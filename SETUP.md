# Setting up Guildcord

This walks through getting Guildcord actually running: a WoW account for
the bot to log in as, a Discord bot application, and the config file that
ties them together.

## 1. Prerequisites

- Python 3.10+
- Access to a WoW 3.3.5a (WotLK) server — your own private server, or one
  where an admin has agreed to let you run a bridge bot. You'll need admin
  cooperation either way to get the connection details in step 3.
- A Discord server where you can add bots (need "Manage Server" there).

## 2. Create the Discord bot

1. Go to https://discord.com/developers/applications → **New Application**.
2. **Bot** tab → **Reset Token** (or it's shown once on creation) → copy it.
   This is `bot_token` in config. Treat it like a password — anyone with
   it can control the bot.
3. Still on the **Bot** tab, under **Privileged Gateway Intents**, enable
   both:
   - **Message Content Intent** — required, the bot needs to read message
     text to relay it.
   - **Server Members Intent** — required for the guild roster / who-online
     features.
   Guildcord will fail to start (or silently not see message content) if
   these aren't on.
4. **OAuth2 → URL Generator**: scope `bot`; permissions **Send Messages**,
   **Read Message History**, **View Channels**. Open the generated URL to
   invite the bot to your server.
5. In Discord: **User Settings → Advanced → Developer Mode** (on), then
   right-click each channel you want to bridge → **Copy Channel ID**.
   You'll need one ID per channel mapping.

## 3. Get a WoW account for the bot

Create a **dedicated account** for the bot — not your main login. The bot
logs in as a real character and stays in the world the whole time it's
running; that character is who "speaks" in WoW chat when relaying from
Discord, and who shows up online in `/who`.

You'll need, from the server (ask an admin if you don't have these):

| Config field | Where it comes from |
|---|---|
| `auth_host` | The realmlist address, e.g. from the client's `realmlist.wtf` (`set realmlist host.name`) |
| `auth_port` | Almost always `3724` (the default) |
| `world_port` | The realm's world-server port — Guildcord doesn't auto-fetch the realm list, so this has to come from the client's realm selection screen or the server admin. Commonly `8085` but varies per server. |
| `realm_id` | Usually `1` for a single-realm server; ask the admin if there are multiple realms |
| `account` / `password` | The bot's dedicated account |
| `realm_name` | Required by the config loader but not actually used for anything — any label works |

Also: log into that account once with a real client first and create one
character. Guildcord logs into whichever character it finds (or a specific
one if you set `character_guid`), it doesn't create one for you.

## 4. Configure

Copy `config.example.yaml` to `config.yaml` and fill in the `wow:` and
`discord:` sections from steps 2–3.

Then set up `channels:` — one entry per WoW-chat-type ↔ Discord-channel
pairing. See the comments in `config.example.yaml` for the full option
list (format tokens, filters, direction, per-type notes), but the shape is:

```yaml
channels:
  - chat_type: "guild"
    discord_channel_id: 222222222222222222   # from step 2.5
    direction: "both"                         # or wow_to_discord / discord_to_wow
    format: "🛡️ **%user**: %message"
```

`direction: both` means messages flow both ways through that mapping;
`wow_to_discord` or `discord_to_wow` restrict it to one direction — useful
for e.g. `system` messages, which can only ever originate in WoW.

## 5. Install and run

```bash
pip install -r requirements.txt --break-system-packages   # or use a venv
python main.py                    # reads ./config.yaml by default
python main.py other-config.yaml  # or point it at a specific file
```

## 6. What you should see

On a clean startup, the logs go roughly:
```
Connecting to WoW server...
Auth handshake OK, session key derived
World auth handshake OK
Auto-selected character: YourCharName (guid=...)
Entered world successfully
Connected to WoW server. Running event listener...
Discord bot ready as YourBot#1234
```

Once both sides show ready, test with a message in a mapped channel —
should show up on the other side within a second or two.

## Troubleshooting

- **`SMSG_CHAR_ENUM` parse error** — this is the one genuinely
  version-fragile packet (see the comment in `world_client.py`). Set
  `character_guid` in config to skip parsing entirely and log straight
  into a known character; get the GUID from the server's character table.
- **Repeated "bad credentials" errors that don't stop** — double-check
  `account`/`password`/`realm_id`. This is a fatal-error class specifically
  because retrying won't fix it — see `reconnect_fatal_delay` in config.
- **Bot connects to WoW but nothing relays to Discord** — usually a
  `discord_channel_id` mismatch, or the Message Content Intent wasn't
  enabled (step 2.3).
- **Bot connects to Discord but nothing relays to WoW** — check
  `direction` on the mapping actually includes `discord_to_wow`.
- Set `status_channel_id` once things are working, so you get a Discord
  ping if the WoW-side connection ever drops instead of only finding out
  from the logs.
