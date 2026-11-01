"""One-time set-up for the Google and Discord connections:  connect.bat google   or   connect.bat discord"""
from __future__ import annotations

import sys

from . import discord_tools, google_auth, google_tools, store

store.load_env()

GOOGLE_STEPS = f"""
Google needs a one-time set-up (about 10 minutes, free, no card):
 1. Open https://console.cloud.google.com/ and create a project (any name, e.g. JARVIS).
 2. APIs & Services > Library: enable "Google Calendar API" and "Gmail API".
 3. APIs & Services > OAuth consent screen: User type External, fill in the app name and your email.
    Add your own Gmail address under "Test users". Then press "Publish app" so the sign-in doesn't expire
    after 7 days (Google will show an "unverified app" warning when you sign in: that's your own app, choose
    Advanced > Continue).
 4. APIs & Services > Credentials > Create credentials > OAuth client ID > Application type: Desktop app.
 5. Download the JSON file and save it as:
    {google_auth.CLIENT_FILE}
 6. Run this again:  connect.bat google
"""

DISCORD_STEPS = """
Discord needs a bot of your own (about 5 minutes, free):
 1. Open https://discord.com/developers/applications > New Application.
 2. Bot tab: Reset Token and copy it. Turn ON "Message Content Intent" under Privileged Gateway Intents.
 3. OAuth2 > URL Generator: scope "bot"; permissions "View Channels" and "Read Message History". Open the
    generated link and add the bot to your own server.
 4. Paste the token into .env as   DISCORD_BOT_TOKEN=...   (you do this yourself; never share it).
 5. Run this again:  connect.bat discord
Discord doesn't let programs read a personal account's DMs, so JARVIS reads the servers your bot is in.
"""


def google(write: bool = False, email: str | None = None) -> int:
    try:
        google_auth.client_info()
    except google_auth.GoogleAuthError as e:
        print(e)
        print(GOOGLE_STEPS)
        return 1
    try:
        email = email or google_auth.account_email()          # sign in again as the account JARVIS already uses
        if email:
            print(f"Signing in as {email} (Google opens on that account).", flush=True)
        google_auth.authorize(write=write, login_hint=email)
        print("Signed in. Checking Calendar and Gmail...")
        print(google_tools.calendar_events(days_ahead=1)[:400])
        print("Gmail:", google_tools.gmail_search("in:inbox", 1)[:300])
    except google_auth.GoogleAuthError as e:
        print(f"Problem: {e}")
        return 1
    if write:
        print("\nGoogle is connected, with permission to save Gmail drafts and add calendar events (each one still asks you first).")
    else:
        print("\nGoogle is connected (read-only). Restart the board and ask JARVIS: what's on my calendar today?")
    return 0


def discord() -> int:
    if not discord_tools.available():
        print(DISCORD_STEPS)
        return 1
    result = discord_tools.discord_channels()
    print(result[:1500])
    if result.startswith("Error"):
        return 1
    print("\nDiscord is connected. Restart the board and ask JARVIS: what's new in #general?")
    return 0


def main() -> int:
    target = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    if target == "google":
        extra = sys.argv[2:]
        return google(write="write" in [a.lower() for a in extra], email=next((a for a in extra if "@" in a), None))
    if target == "discord":
        return discord()
    print("Usage: connect.bat google [write] [you@gmail.com]   |   connect.bat discord")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
