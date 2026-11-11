"""One-time set-up for the Google and Discord connections:  connect.bat google   or   connect.bat discord"""
from __future__ import annotations

import sys

from . import discord_tools, google_auth, google_tools, store

LOG = store.STATE / "connect.log"

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


SIGN_IN_HINTS = (
    ("access_denied", "Google refused the sign-in. In Google Cloud Console (APIs & Services > OAuth consent screen) check that your own Gmail address is under \"Test users\" "
                      "and that you signed in with that account. When Google says the app is unverified, choose Advanced, then Continue: it is your own app."),
    ("no answer", "The sign-in page has to be finished in the browser that opened (choose your account, then Advanced > Continue, then Allow). If nothing opened, paste the long address "
                  "printed above into your browser. The window waits ten minutes."),
    ("didn't match", "Another sign-in page from an earlier try may still be open in the browser. Close it and run this again."),
    ("didn't finish", "Google answered but did not hand over the sign-in. Run it again and approve every permission it asks for (do not untick any boxes)."),
    ("no longer accepts", "While the Google app is in \"Testing\" mode the sign-in lasts 7 days. Press \"Publish app\" on the OAuth consent screen so it stops expiring, then run this again."),
    ("couldn't reach google", "JARVIS could not reach Google. Check the internet connection (and that a firewall is not blocking Python) and try again."),
)


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
        for key, hint in SIGN_IN_HINTS:
            if key in str(e).lower():
                print(hint)
                break
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


class _Tee:
    """Writes what the window shows to connect.log too, so a window that closes (or a message that was hard to copy) is not lost."""

    def __init__(self, stream, log) -> None:
        self.stream, self.log = stream, log

    def write(self, text: str) -> int:
        try:
            self.log.write(text)
            self.log.flush()
        except (OSError, ValueError):
            pass
        return self.stream.write(text)

    def flush(self) -> None:
        self.stream.flush()


def main() -> int:
    """connect.bat google [write] [you@gmail.com] | connect.bat discord.  With nothing after it, it signs in to Google (the usual reason to run it)."""
    import datetime
    import traceback

    log = None
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        log = LOG.open("a", encoding="utf-8")
        log.write(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S}  connect.bat {' '.join(sys.argv[1:]) or '(google)'} =====\n")
        sys.stdout = _Tee(sys.stdout, log)
    except OSError:
        pass
    try:
        args = sys.argv[1:] or ["google"]
        target = args[0].lower()
        if target == "google":
            extra = args[1:]
            return google(write="write" in [a.lower() for a in extra], email=next((a for a in extra if "@" in a), None))
        if target == "discord":
            return discord()
        print("Usage: connect.bat google [write] [you@gmail.com]   |   connect.bat discord")
        return 2
    except KeyboardInterrupt:
        print("\nStopped.")
        return 1
    except Exception as e:  # noqa: BLE001 - whatever went wrong is shown in plain words and written to the log, never a bare traceback in a closing window
        print(f"\nSomething unexpected stopped it: {e.__class__.__name__}: {e}")
        print("The details were saved in " + str(LOG) + " so they can be looked at.")
        traceback.print_exc(file=sys.stdout)
        return 1
    finally:
        if log:
            sys.stdout = sys.__stdout__
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
