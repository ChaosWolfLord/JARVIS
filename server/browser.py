"""Opening a web page in Chrome, with limits.

What it can do: open one http or https address in a new tab of Chrome (or, if Chrome isn't installed, the PC's default browser).
What it cannot do, and why this is considered safe enough to give an AI:

- Only web addresses (http and https). Never file:, javascript:, data:, chrome:, ms-settings:, ftp: or any other kind of link that could
  run something or reach into the PC. An address with a user name or password in it, with spaces or control characters, or longer than
  2,000 characters is refused.
- Only public websites. This PC and the home network are off limits (localhost, 192.168.x.x, 10.x.x.x, the router, a name that turns out to
  point at one): the page JARVIS itself serves and the things on the network must not be reachable by an address an AI was talked into.
- It never passes Chrome anything but the address: no flags, no profiles, no scripts.
- At most 6 pages a minute, so a confused AI cannot flood the screen.
- When the AI (not you) picks the address, JARVIS asks you to press Allow on a card showing the exact address in the cases that matter:
  after it has read your private data (an address can carry data out in its text), after it has read a web page or search result (the page
  could be telling it where to go), and whenever the site isn't one you named yourself. Opening a site you just asked for ("open YouTube")
  needs no click. See agent.py.
- Every opening is written to the activity log.

JARVIS_BROWSER=0 in .env turns it off. JARVIS_CHROME=C:\\path\\to\\chrome.exe says where Chrome is if it isn't found by itself.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from urllib.parse import urlsplit, urlunsplit

OPEN_LIMIT = (6, 60.0)          # at most 6 pages a minute
MAX_URL = 2000
NO_WINDOW = getattr(subprocess, "DETACHED_PROCESS", 0)

# For "open <site>" typed or said by you: a bare name only counts as a web address when it ends in a common top-level domain.
TLDS = ("com", "org", "net", "edu", "gov", "io", "dev", "app", "ai", "co", "tv", "me", "us", "uk", "ca", "de", "fr", "es", "it", "nl", "se", "no", "fi",
        "dk", "pl", "ru", "jp", "kr", "cn", "in", "au", "nz", "br", "mx", "ch", "at", "be", "ie", "info", "xyz", "gg", "fm", "ly", "sh", "to", "cc", "wiki", "news")
DOMAIN = re.compile(r"^(?:www\.)?(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:%s)(?::\d{1,5})?(?:[/?#]\S*)?$" % "|".join(TLDS), re.I)
LOCAL_NAMES = re.compile(r"(^|\.)(localhost|local|lan|internal|intranet|home|corp|localdomain|home\.arpa)$", re.I)


class BrowserError(Exception):
    """Something the user can act on; the message says what."""


def available() -> bool:
    return os.getenv("JARVIS_BROWSER", "1") != "0"


def _public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if getattr(addr, "ipv4_mapped", None):
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


def _literal_ip(host: str) -> str | None:
    """The IP address a host is, when it is written as one (also the old forms: 127.1, 2130706433, 0x7f000001), else None."""
    try:
        return str(ipaddress.ip_address(host.strip("[]")))
    except ValueError:
        pass
    try:
        return socket.inet_ntoa(socket.inet_aton(host))
    except (OSError, ValueError, UnicodeError):
        return None


def clean(raw: str, resolve=socket.getaddrinfo) -> str:
    """The address to open, tidied (a bare "example.com" becomes https://example.com), or a BrowserError saying why it will not be opened."""
    text = str(raw or "").strip()
    if not text:
        raise BrowserError("which page should I open?")
    if len(text) > MAX_URL:
        raise BrowserError("that address is too long.")
    if re.search(r"[\x00-\x1f\x7f\\<>\"`]", text):              # control characters, backslashes (they confuse where the host ends), markup
        raise BrowserError("that doesn't look like a web address.")
    text = text.replace(" ", "%20")                              # a search written with spaces in it is fine
    if "://" not in text:
        if re.match(r"^[a-z][a-z0-9+.-]*:", text, re.I) and not re.match(r"^[^/?#:]+:\d{1,5}(?:[/?#]|$)", text):
            raise BrowserError("I only open web addresses (http or https).")             # javascript:..., mailto:..., ms-settings:...
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https"):
        raise BrowserError("I only open web addresses (http or https).")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise BrowserError("addresses with a user name or password in them are not opened.")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise BrowserError("that doesn't look like a web address.")
    try:
        parts.port
    except ValueError:
        raise BrowserError("that address has a strange port.") from None
    if LOCAL_NAMES.search(host) or "." not in host and not host.startswith("["):
        if not re.fullmatch(r"[0-9a-fx.:]+", host):                                      # a name with no dot is a name on this network; digits are checked below
            raise BrowserError("that is an address on this PC or your home network; I only open public websites.")
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise BrowserError("that doesn't look like a web address.") from None
    literal = _literal_ip(ascii_host)                                                   # an address written out as numbers is judged as it is, not looked up
    try:
        found = {literal} if literal else {info[4][0] for info in resolve(ascii_host, None)}
    except OSError:
        raise BrowserError(f"I can't find a website called {host}.") from None
    if not found or not all(_public(ip) for ip in found):
        raise BrowserError("that is an address on this PC or your home network; I only open public websites.")
    netloc = ascii_host + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme.lower(), netloc, parts.path, parts.query, parts.fragment))


def find_chrome() -> str | None:
    """Where Chrome is: JARVIS_CHROME, the registry's App Paths, then the usual folders."""
    given = os.getenv("JARVIS_CHROME", "").strip()
    if given and os.path.isfile(given):
        return given
    if sys.platform == "win32":
        try:
            import winreg
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:
                        path = winreg.QueryValue(key, None)
                        if path and os.path.isfile(path):
                            return path
                except OSError:
                    continue
        except ImportError:
            pass
    for base in (os.getenv("ProgramFiles"), os.getenv("ProgramFiles(x86)"), os.getenv("LOCALAPPDATA")):
        if base:
            path = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            if os.path.isfile(path):
                return path
    return None


_recent: deque[float] = deque()
_lock = threading.Lock()


def _allowed_now() -> bool:
    now = time.monotonic()
    with _lock:
        while _recent and now - _recent[0] > OPEN_LIMIT[1]:
            _recent.popleft()
        if len(_recent) >= OPEN_LIMIT[0]:
            return False
        _recent.append(now)
        return True


def open_url(raw: str, resolve=socket.getaddrinfo, launch=subprocess.Popen) -> str:
    """Opens the page in Chrome. Returns what to tell the user; raises BrowserError when it will not."""
    if not available():
        raise BrowserError("opening web pages is turned off (JARVIS_BROWSER=0).")
    url = clean(raw, resolve)
    if not _allowed_now():
        raise BrowserError("that is a lot of pages at once. Give it a moment.")
    chrome = find_chrome()
    shown = urlsplit(url).netloc.removeprefix("www.")
    try:
        if chrome:
            launch([chrome, url], close_fds=True, creationflags=NO_WINDOW) if sys.platform == "win32" else launch([chrome, url])
            return f"Opened {shown} in Chrome."
        os.startfile(url) if sys.platform == "win32" and launch is subprocess.Popen else launch(["xdg-open", url])        # no Chrome here: the default browser
        return f"Opened {shown} in your default browser (Chrome wasn't found)."
    except OSError as e:
        raise BrowserError(f"I couldn't start the browser ({e.__class__.__name__}).") from None


# ---- said or typed by you: "open youtube.com", "go to github.com in chrome" ------------------------------------------------------

COMMAND = re.compile(r"^(?:please\s+)?(?:(?:hey\s+)?jarvis[,\s]+)?(?:open|go\s+to|visit|browse\s+to|pull\s+up|load|navigate\s+to|take\s+me\s+to)\s+(?:the\s+(?:website|site|page)\s+)?"
                     r"(?P<where>\S+)(?:\s+(?:in|on|with|using)\s+(?:google\s+)?chrome)?\s*[.!]?$", re.I)


def spoken_address(text: str) -> str | None:
    """The web address in a spoken or typed command, or None when it isn't one ("open Discord" is an app, not a website)."""
    t = str(text or "").strip()
    t = re.sub(r"\s+dot\s+", ".", t, flags=re.I)                              # "youtube dot com"
    t = re.sub(r"\s+slash\s+", "/", t, flags=re.I)
    m = COMMAND.match(t)
    if not m:
        return None
    where = m.group("where").strip(".,!?;")
    if re.match(r"^https?://\S+$", where, re.I) or DOMAIN.match(where):
        return where
    return None


def handle_voice(text: str) -> dict:
    """{handled, ok, text}: opens the page when the command names a website; leaves everything else (apps, questions) to the others."""
    where = spoken_address(text)
    if where is None or not available():
        return {"handled": False, "text": ""}
    try:
        return {"handled": True, "ok": True, "text": open_url(where)}
    except BrowserError as e:
        return {"handled": True, "ok": False, "text": f"Sorry, {e}"}


def tool(args: dict) -> str:
    """The AI's `open_url` tool. Errors come back as text starting with 'Error'."""
    try:
        return open_url(str(args.get("url", "")))
    except BrowserError as e:
        return f"Error: {e}"
