"""The phone door: lets your own phone, on your own Wi-Fi, talk to JARVIS by text or voice.

JARVIS itself still answers only this PC (see guard.py). The phone gets a separate, much smaller web server on its own port that
can do exactly five things: show the phone page, pair, check a pairing, send a chat message, and nothing else (every other
address is a 404; there is no API docs page, no files, no memory, no board).

How it stays safe:
  * Only addresses on your home network are served: anything from the internet side, or from a non-private address, is refused.
  * A phone must be paired first, with a six-digit code that only appears on the PC screen (status menu, Phone), is valid for ten
    minutes, works once, and is locked out for a minute after five wrong guesses. A paired phone gets a long random token that it
    sends in a header (never a cookie), so another web page cannot ride on it. The PC keeps only a hash of each token.
  * Anything that would normally ask "Allow?" on the PC (running code, sending a message, closing an app, fixes, anything after
    private data was read) is refused from the phone with a note; you do those on the PC itself.
  * Things the answer changes on the wall (notes, widgets, timers, holograms) happen on the PC page; the phone just gets a line saying so.
  * The privacy screen locks the phone out too, and every phone message is written to the activity log.
The connection is encrypted (HTTPS) with a certificate JARVIS makes for itself, because phone browsers only allow the microphone on
secure pages. The browser warns about it once; that is expected for a certificate that was not bought from an authority.
"""
from __future__ import annotations

import asyncio
import datetime
import hashlib
import hmac
import io
import ipaddress
import json
import os
import secrets
import socket
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Iterator

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import audit, runner, store

WEB_PHONE = Path(__file__).resolve().parent.parent / "web" / "phone"
PHONES_FILE = store.STATE / "phones.json"
CERT_FILE = store.STATE / "phone-cert.pem"
KEY_FILE = store.STATE / "phone-key.pem"
CODE_TTL_S = 600
MAX_TRIES = 5
LOCK_S = 60
MAX_PHONES = 5
CHAT_PER_MIN = 20

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

# Events that change the wall: the PC page performs them. Everything else useful goes to the phone itself.
WALL_EVENTS = frozenset({"add_note", "board_edit", "widget", "holo", "timer"})
PHONE_EVENTS = frozenset({"text", "notice", "error", "done", "step", "progress", "private", "summary", "memory"})


def lan_ip() -> str:
    """This PC's address on the home network (nothing is sent: connecting a UDP socket only picks a route)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def private_address(host: str | None) -> bool:
    """True for addresses of the home network (and this PC); False for anything that came from the internet."""
    try:
        ip = ipaddress.ip_address(str(host).split("%")[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback or ip.is_link_local


class Phones:
    """Pairing codes and the list of paired phones."""

    def __init__(self, path: Path | None = None, now: Callable[[], float] = time.time) -> None:
        self.path = path or PHONES_FILE
        self.now = now
        self._lock = threading.Lock()
        self._code = ""
        self._expires = 0.0
        self._fails = 0
        self._locked_until = 0.0
        self._sent: dict[str, deque] = {}

    # -- the saved list ---------------------------------------------------------------------------------------
    def _read(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
            return [p for p in data.get("phones", []) if isinstance(p, dict) and p.get("hash")]
        except (OSError, ValueError):
            return []

    def _write(self, phones: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"phones": phones}, indent=1), "utf-8")
        os.replace(tmp, self.path)

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(str(token).encode()).hexdigest()

    def names(self) -> list[str]:
        return [p.get("name", "phone") for p in self._read()]

    def forget_all(self) -> int:
        with self._lock:
            n = len(self._read())
            self._write([])
            return n

    # -- pairing ----------------------------------------------------------------------------------------------
    def new_code(self) -> dict:
        """A fresh six-digit code (replacing any earlier one). Only the PC's own screen ever shows it."""
        with self._lock:
            self._code = f"{secrets.randbelow(10**6):06d}"
            self._expires = self.now() + CODE_TTL_S
            self._fails = 0
            return {"code": self._code, "expires_in": CODE_TTL_S}

    def pair(self, code: str, name: str = "") -> tuple[str | None, int]:
        """(token, 0) when the code is right; (None, seconds_to_wait) when locked out; (None, 0) for a wrong or expired code."""
        with self._lock:
            now = self.now()
            if now < self._locked_until:
                return None, int(self._locked_until - now) + 1
            ok = bool(self._code) and now <= self._expires and hmac.compare_digest(str(code).strip().encode(), self._code.encode())
            if not ok:
                self._fails += 1
                if self._fails >= MAX_TRIES:
                    self._code, self._fails, self._locked_until = "", 0, now + LOCK_S
                    return None, LOCK_S
                return None, 0
            self._code, self._fails = "", 0                     # a code works once
            token = secrets.token_urlsafe(32)
            phones = self._read()[-(MAX_PHONES - 1):]           # the oldest pairing makes room
            clean = "".join(c for c in str(name) if c.isalnum() or c in " ._-")[:30].strip() or "phone"
            phones.append({"hash": self._hash(token), "name": clean, "added": datetime.datetime.now().isoformat(timespec="seconds")})
            self._write(phones)
            return token, 0

    def check(self, token: str | None) -> bool:
        if not token or len(token) > 200:
            return False
        digest = self._hash(token)
        found = False
        for p in self._read():                                  # compare against all, so timing says nothing
            found |= hmac.compare_digest(p["hash"], digest)
        return found

    def allow_chat(self, token: str) -> bool:
        """At most CHAT_PER_MIN messages a minute per phone."""
        q = self._sent.setdefault(self._hash(token), deque())
        now = self.now()
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= CHAT_PER_MIN:
            return False
        q.append(now)
        return True


# -- the certificate ------------------------------------------------------------------------------------------------
def ensure_cert(ip: str, cert: Path | None = None, key: Path | None = None) -> tuple[Path, Path]:
    """A self-signed certificate for this PC's address, made once and reused until the address changes or it nears its end."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    cert, key = cert or CERT_FILE, key or KEY_FILE
    wanted = {ipaddress.ip_address(ip), ipaddress.ip_address("127.0.0.1")}
    try:
        have = x509.load_pem_x509_certificate(cert.read_bytes())
        names = set(have.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress))
        ends = have.not_valid_after_utc if hasattr(have, "not_valid_after_utc") else have.not_valid_after.replace(tzinfo=datetime.timezone.utc)
        if wanted <= names and key.exists() and ends - datetime.datetime.now(datetime.timezone.utc) > datetime.timedelta(days=30):
            return cert, key
    except (OSError, ValueError, x509.ExtensionNotFound):
        pass
    private = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "JARVIS phone")])
    now = datetime.datetime.now(datetime.timezone.utc)
    built = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private.public_key())
             .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
             .not_valid_after(now + datetime.timedelta(days=397))
             .add_extension(x509.SubjectAlternativeName([x509.IPAddress(a) for a in sorted(wanted, key=str)] + [x509.DNSName("localhost")]), critical=False)
             .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
             .sign(private, hashes.SHA256()))
    cert.parent.mkdir(parents=True, exist_ok=True)
    key.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert.write_bytes(built.public_bytes(serialization.Encoding.PEM))
    return cert, key


def qr_svg(text: str) -> bytes:
    import segno
    out = io.BytesIO()
    segno.make(text, error="m").save(out, kind="svg", scale=6, border=2, dark="#f2f5fb", light=None)
    return out.getvalue()


class Events:
    """Things the PC wants the phone page to know about (a reminder is due, Claude finished, an alert): pushed to every phone page that has
    the event stream open. Nothing is stored here: a phone that is not connected simply doesn't hear it (reminders wait for it on the PC)."""

    def __init__(self) -> None:
        self.queues: set = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    @staticmethod
    def _put(q, event) -> None:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass

    def publish(self, event: dict) -> int:
        """Returns how many phone pages were told."""
        loop, queues = self.loop, list(self.queues)
        if not loop or not queues:
            return 0
        for q in queues:
            loop.call_soon_threadsafe(self._put, q, event)
        return len(queues)


# -- the phone's web app --------------------------------------------------------------------------------------------
class PairRequest(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(default="", max_length=60)


class Turn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=4000)


class PhoneChat(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[Turn] = Field(default=[], max_length=24)
    private: bool = False
    show: bool = True          # put the question and answer on the wall
    speak: bool = False        # also say the answer on the PC's speakers


def wall_line(ev: dict) -> str:
    """What the phone is told when an answer changed the wall."""
    kind = ev.get("type")
    if kind == "timer":
        return "Timer started on the wall" if ev.get("action") == "start" else "Timer cancelled"
    if kind == "widget":
        return f"{'Showing' if ev.get('show') else 'Hid'} the {ev.get('name', '')} widget on the wall"
    if kind == "holo":
        return f"Showing on the wall: {str(ev.get('title', ''))[:60]}"
    if kind == "add_note":
        return "Added a note to the board"
    return "Changed the board"


def build_app(phones: Phones, chat_turn: Callable[..., Iterator[dict]], broadcast: Callable[[dict], None],
              is_locked: Callable[[], bool] = lambda: False, events: "Events | None" = None,
              on_events_connect: Callable[[], None] | None = None) -> FastAPI:
    events = events if events is not None else Events()
    app = FastAPI(title="JARVIS phone", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def only_home_network(request: Request, call_next):
        host = request.client.host if request.client else ""
        if not private_address(host):
            audit.record("blocked", f"phone door: non-home address {host}", "blocked")
            return JSONResponse({"detail": "Not available from here."}, status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def page(name: str, kind: str):
        path = WEB_PHONE / name
        return FileResponse(path, media_type=kind)

    @app.get("/")
    def index():
        return page("phone.html", "text/html; charset=utf-8")

    @app.get("/phone.js")
    def script():
        return page("phone.js", "text/javascript; charset=utf-8")

    @app.get("/phone.css")
    def style():
        return page("phone.css", "text/css; charset=utf-8")

    def bearer(authorization: str | None) -> str:
        token = (authorization or "").removeprefix("Bearer ").strip()
        if not phones.check(token):
            raise HTTPException(401, "This phone isn't paired (or was forgotten). Pair it again.")
        return token

    @app.post("/pair")
    def pair(req: PairRequest):
        token, wait = phones.pair(req.code, req.name)
        if token:
            audit.record("phone", f"paired: {phones.names()[-1:]}")
            return {"token": token}
        audit.record("phone", "pairing refused", "denied")
        if wait:
            raise HTTPException(429, f"Too many wrong codes. Try again in {wait} seconds.")
        raise HTTPException(403, "That code isn't right, or it ran out. Ask for a new one on the PC (status menu, Phone).")

    @app.get("/ping")
    def ping(authorization: str | None = Header(default=None)):
        bearer(authorization)
        return {"ok": True, "locked": is_locked()}

    @app.get("/events")
    async def event_stream(authorization: str | None = Header(default=None)):
        token = bearer(authorization)
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        events.loop = asyncio.get_running_loop()
        events.queues.add(q)
        if on_events_connect:
            threading.Timer(1.0, on_events_connect).start()      # anything that was waiting for a phone can be handed over now

        async def stream():
            try:
                yield ": connected\n\n"
                while True:
                    try:
                        ev = await asyncio.wait_for(q.get(), 15)
                    except asyncio.TimeoutError:
                        if not phones.check(token):               # forgotten on the PC: the stream ends
                            return
                        yield ": ping\n\n"
                        continue
                    yield f"data: {json.dumps(ev)}\n\n"
            finally:
                events.queues.discard(q)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/chat")
    def chat(req: PhoneChat, authorization: str | None = Header(default=None)):
        token = bearer(authorization)
        if is_locked():
            raise HTTPException(423, "The privacy screen is on.")
        if not phones.allow_chat(token):
            raise HTTPException(429, "Slow down a little.")
        audit.record("phone", f"asked: {req.message[:100]}")
        history = [t.model_dump() for t in req.history]
        cancel = threading.Event()

        def events():
            reply, summary = [], ""
            try:
                for ev in chat_turn(req.message, history, None, cancel, "", req.private):
                    kind = ev.get("type")
                    if kind == "run_request":                    # needs an Allow on the PC: not from the phone
                        runner.decide(ev.get("id", ""), False)
                        yield f"data: {json.dumps({'type': 'notice', 'text': 'That needs your OK on the PC screen, so I skipped it. Ask me there.'})}\n\n"
                        continue
                    if kind == "run_result":
                        continue
                    if kind in WALL_EVENTS:
                        broadcast({"type": "phone_event", "event": ev})
                        yield f"data: {json.dumps({'type': 'did', 'text': wall_line(ev)})}\n\n"
                        continue
                    if kind not in PHONE_EVENTS:
                        continue
                    if kind == "text":
                        reply.append(ev.get("delta", ""))
                    elif kind == "summary":
                        summary = ev.get("text", "")
                    yield f"data: {json.dumps(ev)}\n\n"
            except GeneratorExit:
                raise
            except Exception:  # noqa: BLE001 - a broken turn is a message, not a crash
                yield f"data: {json.dumps({'type': 'error', 'message': 'Something went wrong on the PC.'})}\n\n"
            finally:
                cancel.set()
                text = "".join(reply).strip() or summary.strip()
                if req.show and text:
                    broadcast({"type": "notify", "title": f"Phone: {req.message[:60]}", "text": text[:300], "speak": text[:400] if req.speak else ""})

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    return app


class PhoneService:
    """Runs the phone web server on its own thread, next to the main one."""

    def __init__(self, phones: Phones | None = None) -> None:
        self.phones = phones or Phones()
        self.server = None
        self.thread: threading.Thread | None = None
        self.error = ""
        self.ip = ""
        self.port = 0
        self.tls = True
        self.events = Events()

    def publish(self, event: dict) -> int:
        return self.events.publish(event)

    @property
    def url(self) -> str:
        return f"{'https' if self.tls else 'http'}://{self.ip}:{self.port}" if self.port else ""

    def start(self, chat_turn, broadcast, is_locked, port: int = 8443, tls: bool = True, host: str = "0.0.0.0", on_events_connect=None) -> None:
        import uvicorn
        self.ip, self.port, self.tls, self.error = lan_ip(), port, tls, ""
        try:
            kwargs = {}
            if tls:
                cert, key = ensure_cert(self.ip)
                kwargs = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
            app = build_app(self.phones, chat_turn, broadcast, is_locked, self.events, on_events_connect)
            self.server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False, **kwargs))
        except Exception as e:  # noqa: BLE001 - a phone door that can't start must never stop JARVIS starting
            self.error = f"{e.__class__.__name__}: {e}"
            return

        def run():
            try:
                asyncio.run(self.server.serve())
            except BaseException as e:  # noqa: BLE001 - uvicorn exits the thread when the port is taken
                self.error = self.error or f"the phone door stopped ({e.__class__.__name__}); is port {port} in use?"

        self.thread = threading.Thread(target=run, daemon=True, name="phone")
        self.thread.start()

    def stop(self) -> None:
        if self.server:
            self.server.should_exit = True

    def status(self) -> dict:
        running = bool(self.server and self.server.started and self.thread and self.thread.is_alive())
        return {"running": running, "url": self.url if running else "", "error": self.error, "paired": self.phones.names(), "tls": self.tls}
