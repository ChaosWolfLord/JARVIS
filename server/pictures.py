"""Pictures for the wall: "show me a picture of a red panda", a link to an image, or a photo shared from the phone.

A picture is checked before it is kept: it must really be a JPEG, PNG, GIF or WebP (by its first bytes, whatever a server claims; SVG and
anything that could carry a script is refused), at most MAX_BYTES, from a public address only (never this PC or the home network). It is
stored under a name made from its own contents in the pictures folder, the newest KEEP are kept, and the wall shows it from there
(GET /api/picture/<id>). Pictures found by a search come from Openverse (openly licensed photos, with the author and licence), which needs no key.
"""
from __future__ import annotations

import hashlib
import re
import socket
import time
from html import unescape
from pathlib import Path

try:
    import httpx
except ImportError:  # newer OpenAI SDKs install the same library under the name httpx2
    import httpx2 as httpx

from . import agent_tools, store

DIR = store.STATE / "pictures"
MAX_BYTES = 12_000_000          # one picture
KEEP = 40                       # how many stay on disk (the oldest go first)
MAX_REDIRECTS = 3
USER_AGENT = "Mozilla/5.0 (compatible; JARVIS-whiteboard/1.0)"      # the same plain name the page fetcher uses: no personal details are sent
OPENVERSE = "https://api.openverse.org/v1/images/"
ID = re.compile(r"^[0-9a-f]{24}$")

_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
)


class PictureError(ValueError):
    """What went wrong, in words the AI (or the phone) can pass on."""


def sniff(data: bytes) -> tuple[str, str] | None:
    """(mime type, file extension) when these bytes are a picture we accept, else None."""
    head = bytes(data[:16])
    for magic, mime, ext in _SIGNATURES:
        if head.startswith(magic):
            return mime, ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def _text(value, limit: int) -> str:
    return " ".join(unescape(re.sub(r"<[^>]*>", " ", str(value or ""))).split())[:limit]


def save(data: bytes, directory: Path | None = None) -> str:
    """Keeps a picture and returns its id. Refuses anything that is not a picture or is too big."""
    if not data:
        raise PictureError("that picture is empty.")
    if len(data) > MAX_BYTES:
        raise PictureError(f"that picture is bigger than {MAX_BYTES // 1_000_000} MB.")
    kind = sniff(data)
    if not kind:
        raise PictureError("that is not a JPEG, PNG, GIF or WebP picture.")
    folder = directory or DIR
    folder.mkdir(parents=True, exist_ok=True)
    pid = hashlib.sha256(data).hexdigest()[:24]
    target = folder / f"{pid}.{kind[1]}"
    if not target.exists():
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
    target.touch()                                             # the newest use is kept longest
    _prune(folder)
    return pid


def _prune(folder: Path) -> None:
    files = sorted((p for p in folder.glob("*.*") if ID.match(p.stem)), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[KEEP:]:
        old.unlink(missing_ok=True)


def find(pid: str, directory: Path | None = None) -> tuple[Path, str] | None:
    """(file, mime type) for a stored picture id, or None. The id must be exactly what save() made, so no path can be smuggled in."""
    if not ID.match(str(pid)):
        return None
    for ext, mime in (("jpg", "image/jpeg"), ("png", "image/png"), ("gif", "image/gif"), ("webp", "image/webp")):
        path = (directory or DIR) / f"{pid}.{ext}"
        if path.is_file():
            return path, mime
    return None


def event(pid: str, title: str = "", credit: str = "") -> dict:
    """What the wall is told: show this picture."""
    return {"type": "picture", "id": pid, "src": f"/api/picture/{pid}", "title": _text(title, 80) or "Picture", "credit": _text(credit, 120)}


# ---- getting a picture from the internet -------------------------------------------------------------------------------
def download(url: str, client: "httpx.Client | None" = None, resolve=socket.getaddrinfo) -> bytes:
    """The bytes of a picture at a public http(s) address. Redirects are followed a few times, and every hop is checked."""
    own = client is None
    client = client or httpx.Client(timeout=12.0, follow_redirects=False, headers={"User-Agent": USER_AGENT})
    try:
        current = str(url).strip()
        for _ in range(MAX_REDIRECTS + 1):
            why = agent_tools.check_url(current, resolve)
            if why:
                raise PictureError(f"can't fetch that picture: {why}.")
            with client.stream("GET", current) as resp:
                if resp.is_redirect and resp.headers.get("location"):
                    current = str(httpx.URL(current).join(resp.headers["location"]))
                    continue
                if resp.status_code >= 400:
                    raise PictureError(f"the picture's site answered HTTP {resp.status_code}.")
                if int(resp.headers.get("content-length") or 0) > MAX_BYTES:
                    raise PictureError("that picture is too big.")
                body = b""
                for chunk in resp.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise PictureError("that picture is too big.")
                return body
        raise PictureError("too many redirects.")
    except httpx.HTTPError as e:
        raise PictureError(f"couldn't download the picture ({e.__class__.__name__}).") from None
    finally:
        if own:
            client.close()


def openverse(query: str, client: "httpx.Client", limit: int) -> list[dict]:
    """Openly licensed photos for a few words, with the author and licence. Openverse takes about ten seconds for a search it has not seen before
    (and a fraction of a second for one it has), so the caller says "looking" first. Wikipedia and Wikimedia are not used: they refuse programs that
    do not give a contact address, and none is sent from here."""
    try:
        r = client.get(OPENVERSE, params={"q": query, "page_size": limit, "mature": "false", "category": "photograph,illustration"}, timeout=25.0)
        r.raise_for_status()
        results = r.json().get("results") or []
    except (httpx.HTTPError, ValueError, AttributeError) as e:
        raise PictureError(f"couldn't search for pictures ({e.__class__.__name__}).") from None
    found = []
    for item in results:
        if not isinstance(item, dict) or item.get("mature"):
            continue
        thumb = str(item.get("thumbnail") or "")
        if not thumb.startswith("https://api.openverse.org/"):
            continue
        if min(item.get("width") or 9999, item.get("height") or 9999) < 300:
            continue
        original = str(item.get("url") or "")
        licence = " ".join(x for x in (str(item.get("license") or "").upper(), str(item.get("license_version") or "")) if x)
        found.append({"url": thumb, "fallback": original if original.startswith("https://") else "", "title": _text(item.get("title"), 80) or _text(query, 80),
                      "credit": " · ".join(x for x in (_text(item.get("creator"), 60), licence, "Openverse") if x)})
    return found


def search(query: str, client: "httpx.Client | None" = None, limit: int = 8) -> list[dict]:
    """Pictures for a few words, best first: [{url, fallback, title, credit}]. `url` is Openverse's own copy at a size the wall can use
    (about 600 pixels wide); `fallback` is the original, tried if that fails to download."""
    query = _text(query, 100)
    if not query:
        raise PictureError("say what the picture should show.")
    own = client is None
    client = client or httpx.Client(timeout=10.0, headers={"User-Agent": USER_AGENT})
    try:
        return openverse(query, client, limit)
    finally:
        if own:
            client.close()


def show(query: str = "", url: str = "", title: str = "", client: "httpx.Client | None" = None) -> dict:
    """Gets the picture (a web address wins over a search) and returns the event that puts it on the wall."""
    if str(url or "").strip():
        pid = save(download(url, client))
        return event(pid, title or "Picture", "")
    last = "nothing matched."
    for hit in search(query, client)[:3]:                       # the first that downloads is used
        for address in (hit["url"], hit["fallback"]):
            if not address:
                continue
            try:
                pid = save(download(address, client))
            except PictureError as e:
                last = str(e)
                continue
            return event(pid, title or hit["title"], hit["credit"])
    raise PictureError(f"I couldn't find a picture of {_text(query, 60)!r}: {last}")


def tool(args: dict) -> tuple[str, dict | None]:
    """The AI's `picture` tool: (what the model is told, the event for the wall)."""
    try:
        ev = show(str(args.get("query") or ""), str(args.get("url") or ""), str(args.get("title") or ""))
    except PictureError as e:
        return f"Error: {e}", None
    return f"The picture \"{ev['title']}\" is on the wall.", ev


def from_words(text: str) -> str | None:
    """The thing to look for in "show me a picture of a red panda" (also photo/image/pic, "put ... on the wall"), else None."""
    t = " ".join(re.sub(r"[^a-z0-9' \-]", " ", str(text).lower()).split())
    t = re.sub(r"^(?:hey )?jarvis ", "", t)
    m = re.match(r"^(?:please )?(?:can you |could you )?(?:show|pull up|bring up|put up|display|get)(?: me| us)?(?: a| an| the| some)? (?:picture|photo|image|pic|photograph)s? (?:of|for|showing) (.{2,80}?)(?: on the (?:wall|board|screen))?$", t)
    if not m:
        m = re.match(r"^(?:please )?(?:put|show|display) (?:a |an |the |some )?(?:picture|photo|image|pic) of (.{2,80}?) on the (?:wall|board|screen)$", t)
    return m.group(1).strip() if m else None


def handle_voice(text: str, tell_page=None) -> dict:
    """{handled, ok, text, event}: "show me a picture of ..." is answered here, with no AI request. `tell_page` (when the words came from the
    phone) puts the event on the PC's page; the PC's own page gets the event in the answer and shows it itself."""
    what = from_words(text)
    if not what:
        return {"handled": False, "text": ""}
    try:
        ev = show(what)
    except PictureError as e:
        return {"handled": True, "ok": False, "text": f"Sorry, {e}"}
    if tell_page is not None:
        tell_page({"type": "phone_event", "event": ev})
    return {"handled": True, "ok": True, "text": f"Here is {ev['title']}, on the wall.", "event": ev}


def cleanup_old(max_age_days: int = 30, directory: Path | None = None) -> int:
    """Removes pictures nobody has shown for a month (the newest KEEP are also the only ones that stay, see save)."""
    folder, gone, cutoff = directory or DIR, 0, time.time() - max_age_days * 86400
    for p in folder.glob("*.*") if folder.is_dir() else []:
        if ID.match(p.stem) and p.stat().st_mtime < cutoff:
            p.unlink(missing_ok=True)
            gone += 1
    return gone
