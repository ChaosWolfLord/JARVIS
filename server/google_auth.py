"""Signing JARVIS in to your Google account (Calendar and Gmail, read-only).

You download an OAuth client file from Google once (see README, "Connect Calendar, Gmail and Discord") and
save it in %LOCALAPPDATA%\\jarvis. `connect.bat google` then opens Google's sign-in page in your browser.
Google sends the result back to a tiny web server on this PC (127.0.0.1) and JARVIS keeps only a refresh
token in %LOCALAPPDATA%\\jarvis, never in the project folder or OneDrive. Your Google password is never
seen by JARVIS. Revoke access any time at https://myaccount.google.com/permissions.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import secrets
import threading
import time
import urllib.parse
import webbrowser

from . import secretbox, store
from .agent_tools import httpx

SCOPES = (
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
)
# Only asked for by `connect.bat google write`: saving Gmail drafts (JARVIS never sends mail itself) and adding calendar events.
WRITE_SCOPES = (
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.events",
)
CLIENT_FILE = store.STATE / "google_client.json"
TOKEN_FILE = store.STATE / "google_token.json"
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
TOKEN_URI = "https://oauth2.googleapis.com/token"


class GoogleAuthError(Exception):
    """Something the user has to fix; the message says what."""


_cache: dict = {"token": None, "expires": 0.0}


def load_token() -> dict:
    """The saved sign-in ({refresh_token, scope, ...}), decrypted; {} if there is none or this account can't read it.

    The file is encrypted with Windows data protection. A plain one from an older version is read once and re-saved encrypted."""
    raw = store._read(TOKEN_FILE, {})
    if "sealed" in raw:
        try:
            return secretbox.unseal(raw["sealed"])
        except OSError:
            return {}
    if raw.get("refresh_token"):
        save_token(raw)                      # migrate the old plain-text file
        return raw
    return {}


def save_token(token: dict) -> None:
    store._write(TOKEN_FILE, {"v": 2, "sealed": secretbox.seal(token)})


def granted_scopes() -> set[str]:
    return set(str(load_token().get("scope", "")).split())


def has_write() -> bool:
    """Has the user granted permission to save drafts and add events (connect.bat google write)?"""
    return set(WRITE_SCOPES) <= granted_scopes()


def connected() -> bool:
    return bool(load_token().get("refresh_token"))


def client_info() -> dict:
    """client_id and client_secret from the file downloaded from Google Cloud Console."""
    raw = store._read(CLIENT_FILE, {})
    info = raw.get("installed") or raw.get("web") or {}
    if not info.get("client_id") or not info.get("client_secret"):
        raise GoogleAuthError(
            f"Google isn't set up yet: the OAuth client file is missing or wrong at {CLIENT_FILE}. "
            "The steps are in the README."
        )
    return {"client_id": info["client_id"], "client_secret": info["client_secret"],
            "auth_uri": info.get("auth_uri", AUTH_URI), "token_uri": info.get("token_uri", TOKEN_URI)}


def pkce_pair() -> tuple[str, str]:
    """(verifier, challenge): proves the program that asked for the sign-in is the one finishing it."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def auth_url(info: dict, redirect_uri: str, state: str, challenge: str, write: bool = False, login_hint: str | None = None) -> str:
    query = urllib.parse.urlencode({
        "client_id": info["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(SCOPES + (WRITE_SCOPES if write else ())), "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        "access_type": "offline", "prompt": "consent",
        **({"login_hint": login_hint} if login_hint else {}),      # Google opens on this account instead of whichever is first in the browser
    })
    return f"{info['auth_uri']}?{query}"


class _Catcher(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server's name
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        if "code" in params or "error" in params:
            self.server.result = params
            body = ("<h2>JARVIS is connected to Google.</h2><p>You can close this tab.</p>" if "code" in params
                    else "<h2>Google sign-in was cancelled.</h2><p>You can close this tab.</p>")
        else:
            body = "<p>Waiting for Google…</p>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<!doctype html><meta charset=utf-8><body style='font-family:sans-serif'>{body}".encode())

    def log_message(self, *args):  # keep the console quiet
        pass


def authorize(open_browser=webbrowser.open, timeout: float = 600.0, client=None, write: bool = False, login_hint: str | None = None) -> None:
    """Runs the whole sign-in: opens the browser, waits for Google's answer, saves the refresh token."""
    info = client_info()
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    server = http.server.HTTPServer(("127.0.0.1", 0), _Catcher)
    server.result = None
    server.timeout = 1.0
    redirect = f"http://127.0.0.1:{server.server_address[1]}"
    url = auth_url(info, redirect, state, challenge, write, login_hint)
    print("Opening Google's sign-in page. If nothing opens, paste this address into your browser:\n" + url, flush=True)
    open_browser(url)
    deadline = time.time() + timeout
    while server.result is None and time.time() < deadline:
        server.handle_request()
    server.server_close()
    result = server.result
    if not result:
        raise GoogleAuthError("No answer from Google within a few minutes. Run it again.")
    if result.get("error"):
        raise GoogleAuthError(f"Google said: {result['error']}.")
    if result.get("state") != state:
        raise GoogleAuthError("The answer didn't match the sign-in that was started, so it was ignored. Run it again.")
    own = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        resp = client.post(info["token_uri"], data={
            "client_id": info["client_id"], "client_secret": info["client_secret"], "code": result["code"],
            "code_verifier": verifier, "redirect_uri": redirect, "grant_type": "authorization_code",
        })
    finally:
        if own:
            client.close()
    data = resp.json() if resp.content else {}
    if resp.status_code != 200 or not data.get("refresh_token"):
        raise GoogleAuthError(f"Google didn't finish the sign-in ({data.get('error_description') or data.get('error') or resp.status_code}).")
    account = _profile_email(data.get("access_token"), None if own else client)
    if login_hint and account and account.lower() != login_hint.lower():
        raise GoogleAuthError(f"You signed in as {account}, but JARVIS is meant to use {login_hint}. Nothing was saved: run it again and choose {login_hint}.")
    save_token({"refresh_token": data["refresh_token"], "scope": data.get("scope", ""), "created": time.time(), "email": account or login_hint or ""})
    _cache.update(token=data.get("access_token"), expires=time.time() + float(data.get("expires_in", 0)) - 60)


def _profile_email(access: str | None, client=None) -> str | None:
    """The Gmail address an access token belongs to, or None if it can't be found out."""
    if not access:
        return None
    own = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        resp = client.get(PROFILE_URL, headers={"Authorization": f"Bearer {access}"})
        return resp.json().get("emailAddress") if resp.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None
    finally:
        if own:
            client.close()


def account_email(client=None) -> str | None:
    """The Google account JARVIS is connected to (remembered at sign-in; found out from Google for older sign-ins)."""
    saved = load_token().get("email")
    if saved:
        return saved
    try:
        return _profile_email(access_token(client), client)
    except GoogleAuthError:
        return None


def access_token(client=None) -> str:
    """A current access token, refreshed from the saved refresh token when needed."""
    if _cache["token"] and time.time() < _cache["expires"]:
        return _cache["token"]
    refresh = load_token().get("refresh_token")
    if not refresh:
        raise GoogleAuthError("Google isn't connected yet. Run connect.bat google.")
    info = client_info()
    own = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        resp = client.post(info["token_uri"], data={
            "client_id": info["client_id"], "client_secret": info["client_secret"],
            "refresh_token": refresh, "grant_type": "refresh_token",
        })
    except httpx.HTTPError:
        raise GoogleAuthError("Couldn't reach Google. Check the internet connection.") from None
    finally:
        if own:
            client.close()
    data = resp.json() if resp.content else {}
    if resp.status_code != 200 or not data.get("access_token"):
        # Google expires the sign-in after 7 days while the app is in "Testing" mode (see README).
        raise GoogleAuthError("Google no longer accepts the saved sign-in (it expires after 7 days while the app is in "
                              "Testing mode). Run connect.bat google again.")
    _cache.update(token=data["access_token"], expires=time.time() + float(data.get("expires_in", 3600)) - 60)
    return _cache["token"]
