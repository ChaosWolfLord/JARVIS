"""Google Calendar and Gmail for the agent: look-ups, plus two actions that always ask you first.

Email subjects, bodies and event titles are written by other people, so everything is wrapped as untrusted
data (anyone can send you an email that says "ignore your instructions"). Nothing here sends, deletes or
changes anything on its own: the look-ups are read-only, and the two actions (save a reply as a Gmail DRAFT, add a calendar
event) run only after you approve exactly what they will do. JARVIS never sends email: a draft waits in Gmail for you.
"""
from __future__ import annotations

import base64
import html
import re
from datetime import datetime, timedelta

from . import agent_tools, google_auth
from .agent_tools import httpx, wrap

CAL = "https://www.googleapis.com/calendar/v3"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
MAX_BODY = 4000


def available() -> bool:
    return google_auth.connected()


def _get(url: str, params: dict | None, client=None) -> dict:
    own = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        resp = client.get(url, params=params, headers={"Authorization": f"Bearer {google_auth.access_token()}"})
    except httpx.HTTPError:
        raise google_auth.GoogleAuthError("Couldn't reach Google. Check the internet connection.") from None
    finally:
        if own:
            client.close()
    if resp.status_code == 403:
        raise google_auth.GoogleAuthError(
            "Google refused: the Calendar or Gmail API may not be switched on for the project in Google Cloud Console "
            "(see the README), or the permission wasn't granted. Run connect.bat google again if needed.")
    if resp.status_code == 401:
        google_auth._cache.update(token=None, expires=0.0)
        raise google_auth.GoogleAuthError("Google rejected the sign-in. Run connect.bat google again.")
    if resp.status_code >= 400:
        raise google_auth.GoogleAuthError(f"Google answered HTTP {resp.status_code}.")
    return resp.json()


# ---- calendar -----------------------------------------------------------------

def _when(ev: dict) -> tuple[datetime, str]:
    start, end = ev.get("start", {}), ev.get("end", {})
    if "dateTime" in start:
        s = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00")).astimezone()
        e = datetime.fromisoformat(end.get("dateTime", start["dateTime"]).replace("Z", "+00:00")).astimezone()
        return s, f"{s:%a %d %b %H:%M}-{e:%H:%M}"
    day = datetime.fromisoformat(start.get("date", "1970-01-01")).astimezone()
    return day, f"{day:%a %d %b} all day"


def calendar_events(days_ahead: int = 7, days_back: int = 0, now: datetime | None = None, client=None) -> str:
    days_ahead = max(0, min(int(days_ahead), 60))
    days_back = max(0, min(int(days_back), 14))
    now = now or datetime.now().astimezone()
    start = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = (now + timedelta(days=days_ahead + 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    calendars = _get(f"{CAL}/users/me/calendarList", {"minAccessRole": "reader"}, client).get("items", [])
    chosen = [c for c in calendars if c.get("selected", c.get("primary", False))][:6] or calendars[:1]
    events: list[tuple[datetime, str]] = []
    for cal in chosen:
        data = _get(f"{CAL}/calendars/{_quote(cal['id'])}/events", {"timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true",
                          "orderBy": "startTime", "maxResults": 25}, client)
        for ev in data.get("items", []):
            if ev.get("status") == "cancelled":
                continue
            when, label = _when(ev)
            place = f" @ {ev['location']}" if ev.get("location") else ""
            which = f" ({cal.get('summaryOverride') or cal.get('summary', '')})" if len(chosen) > 1 else ""
            events.append((when, f"{label} · {ev.get('summary', '(no title)')}{place}{which}"))
    if not events:
        return f"No events between {start:%a %d %b} and {(end - timedelta(days=1)):%a %d %b}."
    events.sort(key=lambda e: e[0])
    return wrap("\n".join(line for _, line in events[:40]))


def _quote(value: str) -> str:
    from urllib.parse import quote
    return quote(value, safe="")


# ---- gmail --------------------------------------------------------------------

def _header(msg: dict, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def gmail_search(query: str = "", max_results: int = 5, client=None) -> str:
    max_results = max(1, min(int(max_results), 10))
    query = (query or "in:inbox").strip()[:200]
    found = _get(f"{GMAIL}/messages", {"q": query, "maxResults": max_results}, client).get("messages", [])
    if not found:
        return f"No emails matched {query!r}."
    lines = []
    for m in found:
        msg = _get(f"{GMAIL}/messages/{m['id']}", {"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]}, client)
        lines.append(f"id {m['id']} | {_header(msg, 'Date')[:25]} | {_header(msg, 'From')[:60]} | "
                     f"{_header(msg, 'Subject')[:100]} | {html.unescape(msg.get('snippet', ''))[:160]}")
    return wrap("\n".join(lines))


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _body(payload: dict) -> str:
    """Plain text of a message: the text/plain part if there is one, else the HTML part turned into text."""
    plain, rich = [], []

    def walk(part: dict) -> None:
        mime, data = part.get("mimeType", ""), part.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            rich.append(_decode(data))
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    if plain:
        return "\n".join(plain)
    return agent_tools.html_to_text("\n".join(rich))[1] if rich else ""


def gmail_read(message_id: str, client=None) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{6,32}", str(message_id).strip()):
        return "Error: that isn't a message id from gmail_search."
    msg = _get(f"{GMAIL}/messages/{message_id.strip()}", {"format": "full"}, client)
    text = re.sub(r"\n{3,}", "\n\n", _body(msg.get("payload", {}))).strip()
    head = f"From: {_header(msg, 'From')}\nTo: {_header(msg, 'To')[:100]}\nDate: {_header(msg, 'Date')}\nSubject: {_header(msg, 'Subject')}\n\n"
    return wrap(head + (text[:MAX_BODY] or "(no readable text)") + ("\n[trimmed]" if len(text) > MAX_BODY else ""))


# ---- look-ups for "JARVIS speaks first" (structured, read-only; nothing here goes to the AI) ----------------

def upcoming_events(minutes: int = 10, now: datetime | None = None, client=None) -> list[dict]:
    """Timed events that start within the next `minutes` minutes: [{id, title, start, where}]. All-day events are left out."""
    now = now or datetime.now().astimezone()
    end = now + timedelta(minutes=max(1, min(int(minutes), 120)))
    calendars = _get(f"{CAL}/users/me/calendarList", {"minAccessRole": "reader"}, client).get("items", [])
    chosen = [c for c in calendars if c.get("selected", c.get("primary", False))][:6] or calendars[:1]
    found: list[dict] = []
    for cal in chosen:
        data = _get(f"{CAL}/calendars/{_quote(cal['id'])}/events", {"timeMin": now.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true",
                                                                    "orderBy": "startTime", "maxResults": 10}, client)
        for ev in data.get("items", []):
            if ev.get("status") == "cancelled" or "dateTime" not in ev.get("start", {}):
                continue
            start, _ = _when(ev)
            if start > now:
                found.append({"id": str(ev.get("id", ""))[:80], "title": str(ev.get("summary", "(no title)"))[:80], "start": start, "where": str(ev.get("location", ""))[:60]})
    found.sort(key=lambda e: e["start"])
    return found


def important_unread(max_results: int = 10, client=None) -> list[dict]:
    """Unread, important mail in the inbox from the last day: [{id, sender, when_ms}]. Subjects and bodies are never read."""
    found = _get(f"{GMAIL}/messages", {"q": "is:unread in:inbox is:important newer_than:1d", "maxResults": max(1, min(int(max_results), 20))}, client).get("messages", [])
    out = []
    for m in found:
        msg = _get(f"{GMAIL}/messages/{m['id']}", {"format": "metadata", "metadataHeaders": ["From"]}, client)
        sender = re.sub(r'["<>]', "", _header(msg, "From").split("<")[0]).strip() or _header(msg, "From").strip("<> ")
        out.append({"id": m["id"], "sender": sender[:40] or "someone", "when_ms": int(msg.get("internalDate", 0) or 0)})
    return out


# ---- actions (each is prepared, shown to you, and only then carried out) -------------------------------

def _post(url: str, body: dict, client=None) -> dict:
    own = client is None
    client = client or httpx.Client(timeout=20.0)
    try:
        resp = client.post(url, json=body, headers={"Authorization": f"Bearer {google_auth.access_token()}"})
    except httpx.HTTPError:
        raise google_auth.GoogleAuthError("Couldn't reach Google. Check the internet connection.") from None
    finally:
        if own:
            client.close()
    if resp.status_code == 403:
        raise google_auth.GoogleAuthError("Google refused: JARVIS hasn't been given permission to do that. Run connect.bat google write.")
    if resp.status_code == 401:
        google_auth._cache.update(token=None, expires=0.0)
        raise google_auth.GoogleAuthError("Google rejected the sign-in. Run connect.bat google write again.")
    if resp.status_code >= 400:
        raise google_auth.GoogleAuthError(f"Google answered HTTP {resp.status_code}.")
    return resp.json()


def write_available() -> bool:
    return google_auth.connected() and google_auth.has_write()


def _parse_when(text: str) -> tuple[datetime, bool]:
    """(moment, is_date_only) from 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM[:SS][+hh:mm]'. Times without an offset are this PC's local time."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("a start time is needed")
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return datetime.fromisoformat(text), True
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"couldn't understand the time {text!r}; use a form like 2026-10-30T14:00") from None
    return (moment if moment.tzinfo else moment.astimezone()), False


def prepare_event(args: dict) -> dict:
    """Checks an event and returns {payload, preview} without touching Google. Raises ValueError for anything unusable."""
    title = str(args.get("title", "")).strip()[:200]
    if not title:
        raise ValueError("the event needs a title")
    start, all_day = _parse_when(args.get("start"))
    if args.get("end"):
        end, end_date_only = _parse_when(args["end"])
        if end_date_only != all_day:
            raise ValueError("start and end must both be dates, or both be times")
    else:
        end = start + (timedelta(days=1) if all_day else timedelta(hours=1))
    if end <= start:
        raise ValueError("the event must end after it starts")
    if end - start > timedelta(days=14):
        raise ValueError("that event is longer than two weeks; check the dates")
    location = str(args.get("location", "")).strip()[:200]
    description = str(args.get("description", "")).strip()[:2000]
    if all_day:
        payload = {"summary": title, "start": {"date": start.date().isoformat()}, "end": {"date": end.date().isoformat()}}
        when = f"{start:%A %d %B %Y} (all day)"
    else:
        payload = {"summary": title, "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}}
        when = f"{start:%A %d %B %Y, %H:%M} to {end:%H:%M}" if start.date() == end.date() else f"{start:%a %d %b %H:%M} to {end:%a %d %b %H:%M}"
    if location:
        payload["location"] = location
    if description:
        payload["description"] = description
    lines = [f"Title: {title}", f"When: {when}"] + ([f"Where: {location}"] if location else []) + ([f"Notes: {description}"] if description else [])
    return {"payload": payload, "preview": "\n".join(lines), "summary": f"{title} on {start:%a %d %b}" + ("" if all_day else f" at {start:%H:%M}")}


def insert_event(prepared: dict, client=None) -> str:
    _post(f"{CAL}/calendars/primary/events", prepared["payload"], client)
    return f"Event added to the calendar: {prepared['summary']}."


def prepare_reply(message_id: str, body: str, client=None) -> dict:
    """Builds a reply to one email as a draft (to the original sender only) and returns {raw, thread_id, preview}."""
    from email.message import EmailMessage

    if not re.fullmatch(r"[0-9a-fA-F]{6,32}", str(message_id).strip()):
        raise ValueError("that isn't a message id from gmail_search")
    body = str(body or "").strip()
    if not body:
        raise ValueError("the reply is empty")
    msg = _get(f"{GMAIL}/messages/{message_id.strip()}", {"format": "metadata", "metadataHeaders": ["From", "Reply-To", "Subject", "Message-ID", "References"]}, client)
    to = _header(msg, "Reply-To") or _header(msg, "From")
    if not to:
        raise ValueError("the original email has no sender to reply to")
    subject = _header(msg, "Subject")
    reply = EmailMessage()
    try:
        reply["To"] = to
        reply["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        if _header(msg, "Message-ID"):
            reply["In-Reply-To"] = _header(msg, "Message-ID")
            reply["References"] = (_header(msg, "References") + " " + _header(msg, "Message-ID")).strip()
        reply.set_content(body[:8000])
    except ValueError:
        raise ValueError("the email's headers couldn't be used for a reply") from None
    raw = base64.urlsafe_b64encode(reply.as_bytes()).decode("ascii")
    return {"raw": raw, "thread_id": msg.get("threadId"), "preview": f"To: {to}\nSubject: {reply['Subject']}\n\n{body[:8000]}", "summary": f"to {to}"}


def save_draft(prepared: dict, client=None) -> str:
    message = {"raw": prepared["raw"]}
    if prepared.get("thread_id"):
        message["threadId"] = prepared["thread_id"]
    _post(f"{GMAIL}/drafts", {"message": message}, client)
    return f"Reply saved as a draft in Gmail ({prepared['summary']}). It has NOT been sent: open Gmail to review and send it."
