"""Discord for the agent: read-only look-ups, plus one action (sending a message) that always asks you first, through a bot you create and invite to your own server.

Discord doesn't let programs read a personal account's messages (using your own login for that breaks its
rules and can get the account banned), so JARVIS reads the servers a bot of yours has been added to. The bot
needs "View Channels", "Read Message History" and the Message Content intent; see the README. It can't send
anything: JARVIS only calls Discord's read endpoints.
"""
from __future__ import annotations

import os
import re
from datetime import datetime

from .agent_tools import httpx, wrap

API = "https://discord.com/api/v10"
TEXT_CHANNELS = (0, 5)   # text and announcement channels


class DiscordError(Exception):
    """Something the user has to fix; the message says what."""


def available() -> bool:
    return bool(os.getenv("DISCORD_BOT_TOKEN"))


def _get(path: str, params: dict | None = None, client=None):
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise DiscordError("Discord isn't connected. Put DISCORD_BOT_TOKEN in .env (see the README).")
    own = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        resp = client.get(f"{API}{path}", params=params,
                          headers={"Authorization": f"Bot {token}", "User-Agent": "DiscordBot (https://localhost, 1.0)"})
    except httpx.HTTPError:
        raise DiscordError("Couldn't reach Discord. Check the internet connection.") from None
    finally:
        if own:
            client.close()
    if resp.status_code == 401:
        raise DiscordError("Discord rejected the bot token. Check DISCORD_BOT_TOKEN in .env.")
    if resp.status_code in (403, 404):
        raise DiscordError("The bot can't see that. Invite it to the server and give it View Channels and Read Message History.")
    if resp.status_code == 429:
        raise DiscordError("Discord says slow down. Try again in a few seconds.")
    if resp.status_code >= 400:
        raise DiscordError(f"Discord answered HTTP {resp.status_code}.")
    return resp.json()


def _channels(client=None) -> list[tuple[str, str, str]]:
    """(server name, channel name, channel id) for every text channel the bot can list."""
    out = []
    for guild in _get("/users/@me/guilds", None, client)[:10]:
        for ch in _get(f"/guilds/{guild['id']}/channels", None, client):
            if ch.get("type") in TEXT_CHANNELS:
                out.append((guild["name"], ch["name"], ch["id"]))
    return out


def discord_channels(client=None) -> str:
    try:
        rows = _channels(client)
    except DiscordError as e:
        return f"Error: {e}"
    if not rows:
        return "The bot isn't in any server yet (or can't see any text channels). Invite it from the Developer Portal."
    return wrap("\n".join(f"{server} / #{name} (id {cid})" for server, name, cid in rows[:80]))


def _resolve(channel: str, client=None) -> str:
    """A channel id from an id, '#name', 'name' or 'server/#name'."""
    channel = channel.strip()
    if re.fullmatch(r"\d{15,25}", channel):
        return channel
    server, _, name = channel.rpartition("/")
    name = name.lstrip("#").lower()
    hits = [cid for s, n, cid in _channels(client) if n.lower() == name and (not server or server.lower() in s.lower())]
    if not hits:
        raise DiscordError(f"No channel called {channel!r}. Use discord_channels to see the names.")
    if len(hits) > 1:
        raise DiscordError(f"More than one channel is called {channel!r}; say it as 'server/#channel' or use its id.")
    return hits[0]


def discord_read(channel: str, limit: int = 15, client=None) -> str:
    limit = max(1, min(int(limit), 30))
    try:
        cid = _resolve(str(channel), client)
        messages = _get(f"/channels/{cid}/messages", {"limit": limit}, client)
    except DiscordError as e:
        return f"Error: {e}"
    if not messages:
        return "No messages in that channel."
    lines = []
    for m in reversed(messages):
        when = datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00")).astimezone()
        extras = f" [+{len(m['attachments'])} attachment(s)]" if m.get("attachments") else ""
        text = (m.get("content") or "").replace("\n", " ")[:300]
        lines.append(f"[{when:%a %H:%M}] {m.get('author', {}).get('username', '?')}: {text}{extras}")
    note = ""
    if all(not (m.get("content") or "") for m in messages):
        note = "\n(Every message came back empty: switch on the Message Content intent for the bot in the Developer Portal.)"
    return wrap("\n".join(lines) + note)


def _post(path: str, body: dict, client=None):
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise DiscordError("Discord isn't connected. Put DISCORD_BOT_TOKEN in .env (see the README).")
    own = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        resp = client.post(f"{API}{path}", json=body, headers={"Authorization": f"Bot {token}", "User-Agent": "DiscordBot (https://localhost, 1.0)"})
    except httpx.HTTPError:
        raise DiscordError("Couldn't reach Discord. Check the internet connection.") from None
    finally:
        if own:
            client.close()
    if resp.status_code in (401, 403, 404):
        raise DiscordError("Discord refused: the bot may not be allowed to send messages in that channel (give it the Send Messages permission).")
    if resp.status_code == 429:
        raise DiscordError("Discord says slow down. Try again in a few seconds.")
    if resp.status_code >= 400:
        raise DiscordError(f"Discord answered HTTP {resp.status_code}.")
    return resp.json()


def prepare_send(channel: str, text: str, client=None) -> dict:
    """Works out which channel is meant and returns {channel_id, text, preview} without sending anything."""
    text = str(text or "").strip()
    if not text:
        raise DiscordError("the message is empty")
    cid = _resolve(str(channel), client)
    name = next(((s, n) for s, n, c in _channels(client) if c == cid), ("?", "?"))
    return {"channel_id": cid, "text": text[:2000], "preview": f"To: {name[0]} / #{name[1]}\n\n{text[:2000]}", "summary": f"#{name[1]}"}


def send_message(prepared: dict, client=None) -> str:
    # allowed_mentions with nothing in parse: the message can't ping @everyone, @here or roles.
    _post(f"/channels/{prepared['channel_id']}/messages", {"content": prepared["text"], "allowed_mentions": {"parse": []}}, client)
    return f"Message sent to {prepared['summary']}."
