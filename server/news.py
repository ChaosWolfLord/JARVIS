"""Headlines for the news ticker and for "read me the headlines": public RSS feeds, read on this PC.

No account or key. The default feeds are BBC World, BBC Technology and Hacker News; put your own in .env as
JARVIS_NEWS_FEEDS=https://example.com/a.rss,https://example.com/b.xml  (JARVIS_NEWS=0 turns the ticker's feed off).
Only public https/http addresses are read (never anything on this PC or your home network), the feeds are re-read at most
every 15 minutes, and a headline is just text: it is shown, and read out when you ask, but nothing in it is ever acted on.
"""
from __future__ import annotations

import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

from . import agent_tools
from .agent_tools import httpx

DEFAULT_FEEDS = (
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "https://hnrss.org/frontpage",
)
CACHE_SECONDS = 15 * 60
MAX_BYTES = 600_000
MAX_ITEMS = 24
PER_FEED = 10


def feeds() -> list[str]:
    custom = [f.strip() for f in os.getenv("JARVIS_NEWS_FEEDS", "").split(",") if f.strip()]
    return custom or list(DEFAULT_FEEDS)


def enabled() -> bool:
    return os.getenv("JARVIS_NEWS", "1") != "0"


def clean(text: str, limit: int = 160) -> str:
    """One line of plain text: tags, entities-as-markup and runs of blanks removed."""
    text = re.sub(r"<[^>]*>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _when(text: str | None) -> int:
    if not text:
        return 0
    try:
        return int(parsedate_to_datetime(text).timestamp())
    except (TypeError, ValueError):
        pass
    try:
        return int(datetime.fromisoformat(text.strip().replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def parse_feed(text: str, fallback_source: str = "") -> list[dict]:
    """[{title, source, time}] from RSS or Atom, newest first. A feed with a DOCTYPE or entity tricks is refused, not parsed."""
    head = text[:4000].upper()
    if "<!DOCTYPE" in head or "<!ENTITY" in text.upper()[:20000]:
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    source = fallback_source
    title_el = next((c for c in root.iter() if _local(c.tag) == "title"), None)
    if title_el is not None and title_el.text:
        source = clean(title_el.text, 28) or source
    source = re.sub(r"^BBC News\s*[-–]\s*", "BBC ", source)
    items = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        fields = {_local(c.tag): "".join(c.itertext()) for c in node}      # nested tags keep their text
        title = clean(fields.get("title", ""))
        if title:
            items.append({"title": title, "source": source, "time": _when(fields.get("pubDate") or fields.get("published") or fields.get("updated"))})
    return sorted(items, key=lambda i: -i["time"])[:PER_FEED]


class News:
    def __init__(self, client=None, resolve=None) -> None:
        self.client = client
        self.resolve = resolve
        self.lock = threading.Lock()
        self.items: list[dict] = []
        self.updated = 0.0
        self.error = ""

    def _get(self, url: str) -> str:
        why = agent_tools.check_url(url, **({"resolve": self.resolve} if self.resolve else {}))
        if why:
            raise ValueError(why)
        own = self.client is None
        client = self.client or httpx.Client(timeout=8.0, follow_redirects=False, headers={"User-Agent": agent_tools.USER_AGENT})
        try:
            with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    raise ValueError(f"HTTP {resp.status_code}")
                body = b""
                for chunk in resp.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        break
                return body.decode(resp.encoding or "utf-8", errors="replace")
        finally:
            if own:
                client.close()

    def refresh(self, force: bool = False) -> list[dict]:
        with self.lock:
            if self.items and not force and time.time() - self.updated < CACHE_SECONDS:
                return self.items
            lists, problems = [], []
            for url in feeds():
                try:
                    lists.append(parse_feed(self._get(url)))
                except (ValueError, httpx.HTTPError) as e:
                    problems.append(f"{url.split('/')[2]}: {e}" if isinstance(e, ValueError) else f"{url.split('/')[2]}: unreachable")
            merged: list[dict] = []
            for row in range(PER_FEED):                      # take turns between the feeds so one can't crowd out the rest
                for items in lists:
                    if row < len(items):
                        merged.append(items[row])
            if merged:
                self.items, self.updated = merged[:MAX_ITEMS], time.time()
            self.error = "; ".join(problems) if not merged else ""
            return self.items

    def view(self) -> dict:
        items = self.refresh() if enabled() else []
        return {"enabled": enabled(), "items": items, "updated": int(self.updated), "error": self.error}


def headlines_text(count: int = 8, news: News | None = None) -> str:
    """For the AI: the latest headlines as plain lines, marked as outside content."""
    items = (news or instance).refresh()[:max(1, min(count, 15))]
    if not items:
        return "Error: couldn't read any headlines right now."
    return agent_tools.wrap("\n".join(f"- {i['title']} ({i['source']})" for i in items))


instance = News()
