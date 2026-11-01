"""Keeps other web pages, and other computers, from using JARVIS.

JARVIS only listens on this PC, but that alone doesn't stop a web page you happen to have open from sending requests to
http://localhost:8000: browsers allow it, and a page can even trick the browser into treating its own address as
"localhost" (DNS rebinding). Such a page could read your memory and board or ask JARVIS about your email. So every request
must (1) be addressed to localhost, 127.0.0.1 or [::1], and (2) if the browser says which page it came from (the Origin
header), come from JARVIS's own page. Programs that send no Origin header, like the pen tracker, are unaffected.

It also adds browser safety headers to every page: no framing, no content-type guessing, and a policy that lets the page
load only its own scripts and talk only to JARVIS and the weather service.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit

ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# connect-src lists the only outside address the page itself uses (weather forecasts); everything else is blocked.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "media-src 'self' blob:; font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; "
    "connect-src 'self' ws://localhost:* ws://127.0.0.1:* "
    "https://geocoding-api.open-meteo.com https://api.open-meteo.com"
)
SECURITY_HEADERS = (
    ("Content-Security-Policy", CSP),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
)


def host_name(host_header: str | None) -> str:
    """The host part of a Host header, without its port: 'localhost:8000' -> 'localhost', '[::1]:8000' -> '::1'."""
    if not host_header:
        return ""
    host = host_header.strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def host_ok(host_header: str | None) -> bool:
    return host_name(host_header) in ALLOWED_HOSTS


def origin_ok(origin: str | None, host_header: str | None) -> bool:
    """No Origin header is fine (not a cross-site browser request). If there is one it must be JARVIS's own address."""
    if origin is None:
        return True
    parts = urlsplit(origin)
    return parts.scheme in ("http", "https") and parts.netloc.lower() == (host_header or "").strip().lower() and host_ok(host_header)


class LocalOnly:
    """An ASGI wrapper: refuses requests that fail the checks above, and adds the safety headers to the rest."""

    def __init__(self, app, on_block=None) -> None:
        self.app = app
        self.on_block = on_block

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        host, origin = headers.get("host"), headers.get("origin")
        reason = None
        if not host_ok(host):
            reason = f"wrong address ({host or 'no Host header'})"
        elif not origin_ok(origin, host):
            reason = f"request from another page ({origin})"
        if reason:
            if self.on_block:
                self.on_block(scope.get("path", ""), reason)
            if scope["type"] == "websocket":
                await receive()                                   # the connect message, which must be answered
                return await send({"type": "websocket.close", "code": 1008})
            body = json.dumps({"detail": "JARVIS only answers requests from its own page on this PC."}).encode()
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            return await send({"type": "http.response.body", "body": body})
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_safe(message):
            if message["type"] == "http.response.start":
                have = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k.encode(), v.encode()) for k, v in SECURITY_HEADERS if k.lower().encode() not in have]
                message = {**message, "headers": list(message.get("headers", [])) + extra}
            await send(message)

        return await self.app(scope, receive, send_safe)
