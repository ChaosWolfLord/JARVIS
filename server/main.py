"""FastAPI app: serves the whiteboard UI and the chat/memory API."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from . import agent, audit, browser as browser_mod, claude_usage, diagnostics, filefinder as filefinder_mod, fixes, guard, localcmd, lights as lights_mod, music as music_mod, news as news_mod, nudges as nudges_mod, persona, apps as apps_mod, notify as notify_mod, phone as phone_mod, pictures as pictures_mod, privacy, remote as remote_mod, reminders as reminders_mod, routines as routines_mod, runner, store, vision as vision_mod, wakeword
from . import mcp as mcp_client

WEB = Path(__file__).resolve().parent.parent / "web"


class _QuietResets(logging.Filter):
    """Windows' event loop logs a scary traceback ("Exception in callback _ProactorBasePipeTransport._call_connection_lost()") whenever a browser or
    phone drops a connection abruptly. It is harmless and common, and it made JARVIS report "many errors". Everything else is still logged."""

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        return not (isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)) and "_call_connection_lost" in record.getMessage())


logging.getLogger("asyncio").addFilter(_QuietResets())

@contextlib.asynccontextmanager
async def lifespan(_app):
    store.load_env()                # settings from .env even when the server is started without the supervisor (a variable already set is kept)
    mcp_client.manager.start()      # connect to the MCP servers in data/mcp.json in the background
    notify_mod.token()              # make sure the shared secret exists, so programs like the Claude Code hook can find it
    wake.loop = asyncio.get_running_loop()
    loop = wake.loop
    if os.getenv("JARVIS_WAKEWORD") == "1":
        start_wake()
    if os.getenv("JARVIS_DIAGNOSTICS", "1") != "0":
        monitor.notify = lambda event: on_monitor_event(event, loop)
        monitor.start()
    if os.getenv("JARVIS_LIGHTS", "1") != "0":
        threading.Thread(target=find_lights, daemon=True, name="lights").start()      # a scan takes a few seconds: don't hold up start-up
    if os.getenv("JARVIS_MUSIC", "1") != "0":
        threading.Thread(target=find_speakers, daemon=True, name="speakers").start()
    if os.getenv("JARVIS_PHONE", "1") != "0":
        def tell_page(event: dict) -> None:
            asyncio.run_coroutine_threadsafe(hub.send_all(hub.viewers, json.dumps(event)), loop)

        phone_service.start(
            agent.chat_turn,
            tell_page,
            privacy.locked,
            local_command=lambda text: localcmd.handle(text, tell_page),
            routines=_Routines(),
            on_events_connect=lambda: courier.deliver_due(),      # a phone just opened its page: hand over reminders that were waiting for it
            port=int(os.getenv("JARVIS_PHONE_PORT", "8443")),
            tls=os.getenv("JARVIS_PHONE_TLS", "1") != "0",
        )
    reminder_stop.clear()
    threading.Thread(target=reminder_loop, daemon=True, name="reminders").start()
    if os.getenv("JARVIS_NUDGES", "1") != "0":
        threading.Thread(target=nudge_loop, daemon=True, name="nudges").start()
    yield
    reminder_stop.set()
    phone_service.stop()
    monitor.stop()
    music_mod.instance.backend.stop()
    if wake.service:
        wake.service.stop()
    mcp_client.manager.stop()


phone_service = phone_mod.PhoneService()
reminder_stop = threading.Event()


def reminder_loop() -> None:
    """Every few seconds, hands any due reminder to the open pages and the phone."""
    while not reminder_stop.wait(5):
        try:
            courier.deliver_due()
        except Exception:  # noqa: BLE001 - a hiccup must not stop the reminders for good
            pass


def nudge_loop() -> None:
    """Every minute, asks the heads-up engine whether something needs saying, and says it (wall, phone). Nothing runs without Google connected or while the
    privacy screen is on."""
    from . import google_tools
    while not reminder_stop.wait(60):
        try:
            if privacy.locked() or not google_tools.available():
                continue
            settings = nudges_mod.instance.settings()
            for item in nudges_mod.instance.check():
                audit.record("nudge", item["kind"])
                tell_pages({"type": "nudge", "kind": item["kind"], "text": item["text"], "speak": settings["speak"]})
                if settings["phone"]:
                    phone_service.publish({"type": "push", "title": "JARVIS", "text": item["text"][:200]})
        except Exception:  # noqa: BLE001 - a hiccup must not stop the loop
            pass


def on_monitor_event(event: dict, loop) -> None:
    """The health monitor found (or cleared) a problem: every page hears it, and a new one also goes to the phone."""
    asyncio.run_coroutine_threadsafe(hub.send_all(hub.viewers, json.dumps(event)), loop)
    if event.get("type") == "alert" and event.get("state") == "new" and not privacy.locked():
        phone_service.publish({"type": "push", "title": str(event.get("title", "Alert"))[:60], "text": str(event.get("text", ""))[:200]})


class _Wake:
    service: "wakeword.WakeWord | None" = None
    loop: "asyncio.AbstractEventLoop | None" = None


wake = _Wake()


def google_available() -> bool:
    from . import google_tools
    return google_tools.available()


def tell_pages(event: dict) -> None:
    """Sends an event to every open page (the wall). Used by routines and the file finder, which run on a worker thread."""
    loop = wake.loop
    if loop is not None:
        asyncio.run_coroutine_threadsafe(hub.send_all(hub.viewers, json.dumps(event)), loop)


class _Routines:
    """What the phone door may do with routines: list them, and run one by its id (it can never change them)."""

    def list(self) -> list[dict]:
        return [{"id": r["id"], "name": r["name"], "steps": len(r["steps"])} for r in routines_mod.load()]

    def run(self, key: str) -> dict:
        r = routines_mod.find(key)
        if r is None:
            return {"ok": False, "text": "I don't have a routine called that."}
        out = routines_mod.run(r, lambda step: localcmd.commands(step, tell_pages), tell_pages)
        audit.record("routine", r["name"], "ok" if not out["problems"] else "error")
        return {"ok": not out["problems"], "text": out["text"]}


def find_lights() -> None:
    try:
        lights_mod.lights.discover()
        lights_mod.lights.refresh_states()
    except Exception:  # noqa: BLE001 - looking for lights must never stop JARVIS starting
        pass


def find_speakers() -> None:
    """Looks for speakers once at start-up (it takes ~15 s), so the first "play ..." isn't slow. Does nothing if the add-ons aren't installed."""
    try:
        music_mod.instance.devices()
    except Exception:  # noqa: BLE001
        pass


def start_wake() -> None:
    """Offline wake word: when the name is heard, tell every open page (so it can play its listening sound), then send what was said after it."""
    loop = wake.loop

    def tell(event: dict) -> None:
        asyncio.run_coroutine_threadsafe(hub.send_all(hub.viewers, json.dumps(event)), loop)

    wake.service = wakeword.WakeWord(
        lambda: tell({"type": "wake"}),
        device=os.getenv("JARVIS_WAKEWORD_DEVICE") or None,
        on_command=lambda text: tell({"type": "wake_command", "text": text}),
    )
    wake.service.start()


def restart_wake_word() -> str:
    if os.getenv("JARVIS_WAKEWORD") != "1" or not wake.loop:
        raise fixes.FixError("the offline wake word isn't turned on (JARVIS_WAKEWORD=1 in .env).")
    if wake.service:
        wake.service.stop()
    start_wake()
    return "The wake-word listener was restarted."


def reload_tools() -> str:
    mcp_client.manager.start()
    return "Reconnecting your tools; they show in the status menu as they come up."


fixes.hooks.update(restart_wake_word=restart_wake_word, reload_tools=reload_tools)


def jarvis_health() -> dict:
    """What the monitor needs to know about JARVIS itself."""
    mcp = mcp_client.manager.status()
    router = agent.status_info().get("openrouter")
    return {
        "wake_configured": os.getenv("JARVIS_WAKEWORD") == "1",
        "wake_running": bool(wake.service and wake.service.status()["running"]),
        "wake_error": (wake.service.status()["error"] if wake.service else ""),
        "tracker_expected": bool(os.getenv("JARVIS_TRACKER_ARGS", "").strip()),
        "tracker_connected": bool(hub.trackers),
        "mcp_errors": [{"name": s["name"], "error": s["error"]} for s in mcp["servers"] if s["state"] == "error"],
        "providers": len(agent.usable()),
        "free_requests": (max(0, router["limit"] - router["used_today"]) if router else None),
        "requests_today": store.requests_today(),
        "log_errors": diagnostics.recent_log_errors(),
        "data_mb": sum(diagnostics.folder_size_mb(store.STATE / d) for d in ("logs", "backups", "models")),
    }


monitor = diagnostics.current = diagnostics.Monitor(jarvis_probe=jarvis_health)
app = FastAPI(title="JARVIS", lifespan=lifespan)
app.add_middleware(privacy.Curtain)      # added first, so it runs inside the address check below
app.add_middleware(guard.LocalOnly, on_block=lambda path, why: audit.record("blocked", f"{path}: {why}", "blocked"))


class HistoryItem(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class Note(BaseModel):
    id: int
    text: str
    x: int
    y: int


class Board(BaseModel):
    png: str | None = None
    notes: list[Note] = []


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    history: list[HistoryItem] = []
    board: Board | None = None
    turn: str | None = Field(default=None, max_length=64)  # the page's id for this question, so Stop can find it
    summary: str = Field(default="", max_length=2000)      # a running summary of the older part of this conversation
    private: bool = False                                   # earlier turns of this conversation read private data


class FactRequest(BaseModel):
    fact: str = Field(min_length=1, max_length=300)
    kind: str = "fact"
    pinned: bool = False


class RunDecision(BaseModel):
    approve: bool


STARTED = int(time.time())          # when this server started: the page plays its start-up sequence once per start


@app.get("/api/status")
def status():
    return {**agent.status_info(), "requests_today": store.requests_today(),
            "wake": wake.service.status() if wake.service else {"running": False, "error": ""},
            "alerts": len(monitor.active_alerts()), "started": STARTED, "lights": len(lights_mod.lights.lights),
            "speakers": len(getattr(music_mod.instance.backend, "casts", {}) or {}), "news": news_mod.enabled()}


@app.get("/api/news")
def get_news():
    """Headlines for the ticker (public RSS feeds, re-read at most every 15 minutes)."""
    return news_mod.instance.view()


@app.get("/api/persona/showoff")
def persona_showoff(on: bool = True):
    """What JARVIS says when show-off mode is switched on or off, in its current personality."""
    return {"text": persona.line("showoff_on" if on else "showoff_off")}


@app.get("/api/persona/boot")
def persona_boot():
    """What JARVIS says when it has started up, in its current personality."""
    from datetime import datetime
    return {"text": persona.boot_line(datetime.now().hour)}


class LightCommand(BaseModel):
    target: str = Field(default="", max_length=60)
    power: bool | None = None
    brightness: int | None = Field(default=None, ge=1, le=100)
    color: str | None = Field(default=None, max_length=20)
    kelvin: int | None = Field(default=None, ge=2000, le=9000)


class LightName(BaseModel):
    id: str = Field(max_length=80)
    name: str = Field(max_length=40)


class SpokenLight(BaseModel):
    text: str = Field(min_length=1, max_length=300)


class WakeVote(BaseModel):
    client: str = Field(min_length=1, max_length=64)
    on: bool


@app.post("/api/wake")
def wake_vote(req: WakeVote):
    """A page says whether voice is on. The PC's microphone is open only while at least one page that said so lately wants it: with voice
    off, nothing on this PC listens for "Jarvis"."""
    if wake.service:
        wake.service.vote(req.client, req.on)
        return wake.service.status()
    return {"running": False, "listening": False, "error": ""}


@app.post("/api/wake/listen")
def wake_listen():
    """JARVIS just asked a question: the PC's microphone takes the next sentence as the answer, without the name. Only while voice is on here."""
    ok = bool(wake.service and wake.service.listen_for_reply())
    return {"listening": ok}


def _light_view() -> dict:
    reg = lights_mod.lights
    return {"available": reg.available(), "cloud": bool(reg.cloud), "error": reg.error, "scanned": int(reg.scanned),
            "lights": [l.public() for l in reg.lights.values()]}


@app.get("/api/lights")
def get_lights():
    return _light_view()


@app.post("/api/lights/scan")
def scan_lights():
    lights_mod.lights.discover()
    lights_mod.lights.refresh_states()
    audit.record("lights", "scan", "ok")
    return _light_view()


@app.post("/api/lights/refresh")
def refresh_lights():
    lights_mod.lights.refresh_states()
    return _light_view()


@app.post("/api/lights/command")
def command_lights(req: LightCommand):
    detail = f"{req.target or 'all'} {req.model_dump(exclude={'target'}, exclude_none=True)}"
    try:
        text = lights_mod.lights.command(target=req.target, power=req.power, brightness=req.brightness, color=req.color, kelvin=req.kelvin)
    except lights_mod.LightError as e:
        audit.record("lights", detail, "error")
        raise HTTPException(400, str(e)) from None
    audit.record("lights", detail, "error" if text.startswith("Error") else "ok")
    return {"ok": not text.startswith("Error"), "text": text, **_light_view()}


@app.post("/api/lights/voice")
def voice_lights(req: SpokenLight):
    """A spoken light command ("lights off", "make the desk lights blue"). Handled here, with no AI request."""
    result = lights_mod.handle_voice(req.text)
    if result["handled"]:
        audit.record("lights", req.text[:100], "ok" if result.get("ok") else "error")
    return result


@app.post("/api/lights/rename")
def rename_light(req: LightName):
    try:
        lights_mod.lights.rename(req.id, req.name)
    except lights_mod.LightError as e:
        raise HTTPException(400, str(e)) from None
    return _light_view()


class MusicCommand(BaseModel):
    action: str = Field(pattern="^(play|pause|resume|stop|next|previous|volume|status)$")
    query: str = Field(default="", max_length=200)
    device: str = Field(default="", max_length=60)
    level: int | None = Field(default=None, ge=0, le=100)
    direction: str = Field(default="", pattern="^(up|down)?$")


@app.get("/api/music")
def get_music():
    return music_mod.instance.view()


@app.post("/api/music/command")
def command_music(req: MusicCommand):
    detail = f"{req.action} {req.query} {req.device}".strip()
    args = {"action": req.action, "query": req.query, "device": req.device, "volume": req.level, "direction": req.direction}
    text = music_mod.tool(args)
    audit.record("music", detail, "error" if text.startswith("Error") else "ok")
    return {"ok": not text.startswith("Error"), "text": text.removeprefix("Error: "), **music_mod.instance.view()}


@app.post("/api/music/voice")
def voice_music(req: SpokenLight):
    """A spoken music command ("play ...", "pause", "volume down"). Handled here, with no AI request."""
    result = music_mod.handle_voice(req.text)
    if result["handled"]:
        audit.record("music", req.text[:100], "ok" if result.get("ok") else "error")
    return result


class UiSettings(BaseModel):
    values: dict[str, str | None] = Field(default_factory=dict, max_length=40)


@app.get("/api/ui-settings")
def get_ui_settings():
    """The page's saved settings (widget layout, weather place, voice...). Kept on the PC so a new browser or profile doesn't lose them."""
    return {"values": store.ui_settings()}


@app.put("/api/ui-settings")
def put_ui_settings(req: UiSettings):
    return {"values": store.set_ui_settings(req.values)}


class Notice(BaseModel):
    kind: str = Field(pattern="^(finished|permission|idle|failed)$")
    project: str = Field(default="", max_length=80)


@app.post("/api/notify")
async def post_notify(req: Notice, x_jarvis_token: str | None = Header(default=None)):
    """A program on this PC (the Claude Code hook) asks JARVIS to announce something. Needs the token in %LOCALAPPDATA%\\jarvis\\notify.token."""
    if not notify_mod.valid(x_jarvis_token):
        audit.record("blocked", "/api/notify: wrong or missing token", "blocked")
        raise HTTPException(403, "That needs JARVIS's notify token.")
    if os.getenv("JARVIS_CLAUDE_NOTIFY", "1") == "0" or not notify_mod.limiter.allow():
        return {"ok": True, "sent": 0}
    event = notify_mod.compose(req.kind, req.project)
    await hub.send_all(hub.viewers, json.dumps({"type": "notify", **event}))
    if not privacy.locked():
        phone_service.publish({"type": "push", "title": event["title"], "text": event["text"]})
    audit.record("notify", f"claude {req.kind} {notify_mod.clean_project(req.project)}".strip(), "ok")
    return {"ok": True, "sent": len(hub.viewers)}


@app.get("/api/apps")
def get_apps():
    """The apps JARVIS may open (from the Start Menu, minus everything unsafe) and the programs currently running."""
    return {"enabled": apps_mod.available(), "apps": apps_mod.apps.names(), "running": apps_mod.apps.running()}


class RoutinesIn(BaseModel):
    routines: list[dict] = Field(default=[], max_length=routines_mod.MAX_ROUTINES)


class RoutineRun(BaseModel):
    id: str = Field(min_length=1, max_length=60)


@app.get("/api/routines")
def routines_list():
    """The routines you made (status menu, Routines)."""
    return {"routines": routines_mod.load()}


@app.put("/api/routines")
def routines_save(req: RoutinesIn):
    try:
        saved = routines_mod.save(req.routines)
    except routines_mod.RoutineError as e:
        raise HTTPException(400, str(e)) from None
    audit.record("routine", f"routines saved: {len(saved)}")
    return {"routines": saved}


@app.post("/api/routines/run")
def routines_run(req: RoutineRun):
    """Runs one routine (by id or name) and says how it went."""
    result = _Routines().run(req.id)
    if not result["ok"] and result["text"].startswith("I don't have"):
        raise HTTPException(404, result["text"])
    return result


class FinderFolders(BaseModel):
    folders: list[str] = Field(default=[], max_length=filefinder_mod.MAX_FOLDERS)


class FinderQuery(BaseModel):
    query: str = Field(min_length=1, max_length=300)


class FinderOpen(BaseModel):
    path: str = Field(min_length=1, max_length=600)
    how: str = Field(pattern="^(open|folder|wall)$")


@app.get("/api/finder")
def finder_settings():
    """The folders the file finder may look in (none until you add some), and the usual places to add with one click."""
    return {"folders": filefinder_mod.folders(), "suggestions": filefinder_mod.suggestions()}


@app.put("/api/finder")
def finder_set_folders(req: FinderFolders):
    try:
        saved = filefinder_mod.set_folders(req.folders)
    except filefinder_mod.FinderError as e:
        raise HTTPException(400, str(e)) from None
    audit.record("files", f"folders the finder may search: {len(saved)}")
    return {"folders": saved}


@app.post("/api/finder/search")
def finder_search(req: FinderQuery):
    try:
        found = filefinder_mod.search(req.query)
    except filefinder_mod.FinderError as e:
        raise HTTPException(400, str(e)) from None
    audit.record("files", f"search: {req.query[:100]}")
    return {"text": filefinder_mod.summary(found), "event": filefinder_mod.event(req.query, found)}


@app.post("/api/finder/voice")
def finder_voice(req: SpokenLight):
    """"Find the doc I edited yesterday about the budget": answered here, with no AI request. Anything else is left for the AI."""
    result = filefinder_mod.handle_voice(req.text)
    if result["handled"]:
        audit.record("files", f"search: {req.text[:100]}", "ok" if result.get("ok") else "error")
    return result


@app.post("/api/finder/open")
def finder_open(req: FinderOpen):
    """Opens a found document, shows it in its folder, or puts a found picture on the wall. Only files inside the chosen folders; never a program or script."""
    try:
        if req.how == "open":
            text = filefinder_mod.open_file(req.path)
            audit.record("files", f"opened: {os.path.basename(req.path)[:80]}")
            return {"text": text}
        if req.how == "folder":
            text = filefinder_mod.reveal(req.path)
            audit.record("files", f"shown in folder: {os.path.basename(req.path)[:80]}")
            return {"text": text}
        pid = pictures_mod.save(filefinder_mod.image_bytes(req.path))
        return {"text": "On the wall.", "event": pictures_mod.event(pid, os.path.splitext(os.path.basename(req.path))[0])}
    except (filefinder_mod.FinderError, pictures_mod.PictureError) as e:
        raise HTTPException(400, str(e)) from None
    except OSError:
        raise HTTPException(400, "That file could not be opened.") from None


class NudgeSettings(BaseModel):
    enabled: bool | None = None
    calendar: bool | None = None
    minutes: int | None = Field(default=None, ge=1, le=60)
    mail: bool | None = None
    speak: bool | None = None
    phone: bool | None = None
    quiet_from: str | None = Field(default=None, max_length=5)
    quiet_to: str | None = Field(default=None, max_length=5)


@app.get("/api/nudges")
def api_nudges():
    return {**nudges_mod.instance.status(), "google": google_available()}


@app.post("/api/nudges")
def api_nudges_set(req: NudgeSettings):
    nudges_mod.instance.update(req.model_dump(exclude_none=True))
    return {**nudges_mod.instance.status(), "google": google_available()}


@app.post("/api/nudges/snooze")
def api_nudges_snooze(minutes: float = Query(60, ge=0, le=1440)):
    """Quiet for a while (0 ends a snooze)."""
    nudges_mod.instance.snooze(minutes)
    return {**nudges_mod.instance.status(), "google": google_available()}


@app.post("/api/nudges/voice")
def api_nudges_voice(text: str = Query("", max_length=300)):
    """The page heard something like "don't interrupt me for an hour": snoozes the heads-ups when that is what it was."""
    return nudges_mod.handle_voice(text)


@app.post("/api/look")
async def api_look(request: Request, question: str = ""):
    """"What is this?": the page sends one picture from the PC's webcam (the body is the JPEG) and the question; the AI model that can see answers.
    Nothing is saved, and the camera is only ever opened by the page when you ask."""
    try:
        body = await vision_mod.read_body(request)
        out = await run_in_threadpool(vision_mod.look, body, question)
    except vision_mod.VisionError as e:
        raise HTTPException(400, str(e)) from None
    audit.record("vision", f"looked: {vision_mod.clean_question(question)[:80]} ({len(body) // 1024} KB, webcam)")
    return out


@app.get("/api/picture/{pid}")
def get_picture(pid: str):
    """A picture the wall is showing (found by an id that only this PC makes, so no other file can be asked for)."""
    found = pictures_mod.find(pid)
    if not found:
        raise HTTPException(404, "No such picture.")
    path, mime = found
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


@app.post("/api/picture/voice")
def voice_picture(req: SpokenLight):
    """"Show me a picture of a red panda": found and put on the wall with no AI request. Anything else is left for the AI."""
    result = pictures_mod.handle_voice(req.text)
    if result["handled"]:
        audit.record("pictures", req.text[:100], "ok" if result.get("ok") else "error")
    return result


@app.post("/api/apps/voice")
def voice_apps(req: SpokenLight):
    """"Open Discord" or "open youtube.com": handled here with no AI request. A website opens in Chrome; an app opens from the Start Menu;
    anything else is left for the AI."""
    result = browser_mod.handle_voice(req.text)
    if result["handled"]:
        audit.record("browser", req.text[:100], "ok" if result.get("ok") else "error")
        return result
    result = apps_mod.handle_voice(req.text) if apps_mod.available() else {"handled": False, "text": ""}
    if result["handled"]:
        audit.record("apps", f"open {req.text[:80]}", "ok" if result.get("ok") else "error")
    return result


@app.get("/api/system")
def system():
    return {**monitor.snapshot(), "enabled": monitor.thread is not None}


@app.get("/api/system/summary")
def system_summary():
    text = diagnostics.summary(monitor.snapshot())
    return {"text": text.replace("The system looks healthy.", persona.line("health_ok"), 1)}


@app.get("/api/persona/timer")
def persona_timer(what: str = Query("timer", max_length=60)):
    """What JARVIS says when a timer finishes, in its current personality."""
    return {"text": persona.line("timer_done", what=str(what)[:60])}


@app.get("/api/system/{area}")
def system_area(area: str):
    return {"text": diagnostics.details(area, monitor.snapshot())}


class BoardIn(BaseModel):
    strokes: list[dict] = Field(default_factory=list, max_length=200_000)
    notes: list[dict] = Field(default_factory=list, max_length=2_000)
    nextId: int = 1
    savedAt: int = 0  # milliseconds since 1970, set by the page when it last changed the board


class RestoreRequest(BaseModel):
    name: str = Field(max_length=80)


@app.get("/api/board")
def get_board():
    """The saved whiteboard ({strokes, notes, nextId, savedAt}), or {"board": null} if nothing is saved yet."""
    try:
        return {"board": store.load_board()}
    except OSError:
        raise HTTPException(503, "The board file is busy right now. Try again in a moment.") from None


@app.put("/api/board")
def put_board(board: BoardIn):
    data = board.model_dump()
    data["savedAt"] = data["savedAt"] or int(time.time() * 1000)
    try:
        store.save_board(data)
    except OSError:
        raise HTTPException(503, "Couldn't write the board file. Try again in a moment.") from None
    return {"ok": True, "savedAt": data["savedAt"]}


@app.get("/api/board/backups")
def board_backups():
    return store.list_board_backups()


@app.post("/api/board/restore")
def restore_board(req: RestoreRequest):
    try:
        return {"board": store.restore_board_backup(req.name)}
    except (ValueError, OSError):
        raise HTTPException(404, "No such backup.") from None


@app.get("/api/mcp")
def mcp_status():
    return mcp_client.manager.status()


@app.post("/api/mcp/reload")
def mcp_reload():
    """Re-reads data/mcp.json and reconnects (the status menu's Reload button)."""
    mcp_client.manager.start()
    return {"ok": True}


class UnlockRequest(BaseModel):
    code: str = Field(default="", max_length=20)


class CodeRequest(BaseModel):
    code: str | None = Field(default=None, max_length=20)      # the new code; empty or missing removes it
    current: str = Field(default="", max_length=20)


@app.get("/api/privacy")
def privacy_status():
    return privacy.status()


@app.post("/api/privacy/lock")
def privacy_lock():
    audit.record("privacy", "screen locked")
    return privacy.lock()


@app.post("/api/privacy/unlock")
def privacy_unlock(req: UnlockRequest):
    ok, wait = privacy.unlock(req.code)
    audit.record("privacy", "screen unlocked" if ok else f"wrong code{f' (wait {wait}s)' if wait else ''}", "ok" if ok else "denied")
    return {**privacy.status(), "ok": ok, "wait": wait}


@app.post("/api/privacy/code")
def privacy_code(req: CodeRequest):
    if privacy.locked():
        raise HTTPException(423, "Unlock first.")
    if not privacy.set_code(req.code or None, req.current):
        raise HTTPException(403, "That didn't work: the current code is wrong, or the new code isn't 4 to 8 digits.")
    audit.record("privacy", "unlock code removed" if not req.code else "unlock code changed")
    return privacy.status()


@app.get("/api/activity")
def activity(limit: int = 100):
    """What JARVIS has done on your behalf (newest first): tools used, what they were asked for, and anything blocked."""
    return audit.recent(limit)


@app.get("/api/usage")
def usage():
    """Token totals and per-day averages for the usage widget (today, 7/30/365 days, and daily/weekly/monthly/yearly series)."""
    return store.usage_summary()


@app.get("/api/claude-usage")
def claude_code_usage(measure: str = "all"):
    """Claude Code token totals from its local session logs (first call reads them all, which takes a while)."""
    return claude_usage.summary(measure)


@app.get("/api/phone")
def phone_status():
    """Is the phone door running, where is it, and which phones are paired (the status menu shows this)."""
    return phone_service.status()


@app.post("/api/phone/code")
def phone_code():
    """A new six-digit pairing code, shown on the PC screen only. The phone page asks for it once."""
    if not phone_service.status()["running"]:
        raise HTTPException(409, "The phone door isn't running" + (f": {phone_service.error}" if phone_service.error else "."))
    audit.record("phone", "pairing code shown")
    return phone_service.phones.new_code()


class PhonePush(BaseModel):
    title: str = Field(max_length=60)
    text: str = Field(default="", max_length=200)


@app.post("/api/phone/push")
def phone_push(req: PhonePush):
    """The page tells the phone about something that only the page knows (a timer ended). Nothing goes out while the privacy screen is up."""
    if privacy.locked():
        return {"sent": 0}
    return {"sent": phone_service.publish({"type": "push", "title": req.title, "text": req.text})}


class RemoteOn(BaseModel):
    minutes: float = Field(default=remote_mod.DEFAULT_MINUTES, ge=1, le=remote_mod.MAX_MINUTES)


remote_mod.remote.log = lambda text: audit.record("remote", text)


@app.get("/api/phone/remote")
def remote_status():
    """Is the phone remote switched on, and for how much longer? (Only this PC's own page can switch it on or off.)"""
    return remote_mod.remote.status()


@app.post("/api/phone/remote")
def remote_on(req: RemoteOn):
    """"Let my phone be a remote" for a limited time. It switches itself off afterwards."""
    if not remote_mod.remote.status()["supported"]:
        raise HTTPException(409, "The phone remote only works on Windows.")
    return remote_mod.remote.arm(req.minutes)


@app.delete("/api/phone/remote")
def remote_off():
    return remote_mod.remote.disarm()


@app.post("/api/phone/find")
def phone_find():
    """"Find my phone": every paired phone that is listening is told to ring (and says so if it is on silent, unless its owner allowed that)."""
    sent = phone_service.publish({"type": "find"})
    audit.record("phone", f"find my phone: asked {sent} phone(s)")
    return {"sent": sent}


@app.delete("/api/phone/find")
def phone_find_stop():
    return {"sent": phone_service.publish({"type": "find_stop"})}


@app.delete("/api/phone")
def phone_forget():
    """Un-pairs every phone: each has to be paired again with a new code."""
    n = phone_service.phones.forget_all()
    audit.record("phone", f"forgot {n} phone(s)")
    return {"forgot": n}


@app.get("/api/phone/qr.svg")
def phone_qr():
    """A QR code of the phone page's address, so the phone can open it with its camera."""
    url = phone_service.status()["url"]
    if not url:
        raise HTTPException(409, "The phone door isn't running.")
    from fastapi.responses import Response
    return Response(phone_mod.qr_svg(url), media_type="image/svg+xml")


@app.post("/api/chat")
def chat(req: ChatRequest):
    history = [h.model_dump() for h in req.history]
    board = req.board.model_dump() if req.board else None

    cancel = threading.Event()
    if req.turn:
        _turns[req.turn] = cancel

    def events():
        try:
            for event in agent.chat_turn(req.message, history, board, cancel, req.summary, req.private):
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            cancel.set()  # also reached when the page goes away mid-answer: stop spending requests on it
            if req.turn:
                _turns.pop(req.turn, None)

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


_turns: dict[str, threading.Event] = {}  # answers in progress, so the Stop button can reach them


class SummarizeRequest(BaseModel):
    messages: list[HistoryItem] = Field(max_length=40)
    previous: str = Field(default="", max_length=2000)


@app.post("/api/summarize")
def summarize_chat(req: SummarizeRequest):
    """Condenses older messages into a short summary, so a long conversation keeps its thread without sending it all."""
    return {"summary": agent.summarize([m.model_dump() for m in req.messages], req.previous)}


@app.post("/api/chat/cancel/{turn}")
def cancel_chat(turn: str):
    """The Stop button: the answer ends at its next safe point (after the model call that is running)."""
    event = _turns.get(turn)
    if event:
        event.set()
    return {"ok": bool(event)}


@app.post("/api/run/{run_id}")
def decide_run(run_id: str, req: RunDecision):
    if not runner.decide(run_id, req.approve):
        raise HTTPException(404, "No code is waiting for approval")
    return {"ok": True}


class FactUpdate(BaseModel):
    fact: str | None = Field(default=None, min_length=1, max_length=300)
    kind: str | None = None
    pinned: bool | None = None


@app.get("/api/memory")
def get_memory(q: str = ""):
    """Everything remembered, newest first; with q, only what matches those words, best first."""
    facts = store.list_facts()
    if q.strip():
        return store.search_facts(q, 50, facts)
    return sorted(facts, key=lambda f: (not f["pinned"], -f["id"]))


@app.post("/api/memory")
def add_memory(req: FactRequest):
    return store.add_fact(req.fact.strip(), req.kind, req.pinned)


@app.put("/api/memory/{fact_id}")
def edit_memory(fact_id: int, req: FactUpdate):
    entry = store.update_fact(fact_id, req.fact.strip() if req.fact else None, req.kind, req.pinned)
    if not entry:
        raise HTTPException(404, "No such fact")
    return entry


@app.delete("/api/memory/{fact_id}")
def delete_memory(fact_id: int):
    if not store.remove_fact(fact_id):
        raise HTTPException(404, "No such fact")
    return {"ok": True}


class PenHub:
    """Relays between the pen tracker program and the browser(s): pen events go one way, calibration requests the other."""

    def __init__(self) -> None:
        self.viewers: set[WebSocket] = set()
        self.trackers: set[WebSocket] = set()

    async def send_all(self, group: set[WebSocket], text: str) -> None:
        for ws in list(group):
            try:
                await ws.send_text(text)
            except Exception:  # noqa: BLE001 - a closed socket: drop it
                group.discard(ws)


hub = PenHub()


def _to_pages(event: dict) -> int:
    """Sends an event to every open JARVIS page; returns how many pages there were."""
    n = len(hub.viewers)
    if n and wake.loop:
        asyncio.run_coroutine_threadsafe(hub.send_all(hub.viewers, json.dumps(event)), wake.loop)
    return n


courier = reminders_mod.Courier(reminders_mod.reminders, _to_pages, lambda event: phone_service.publish(event), privacy.locked)


@app.websocket("/ws/pen")
async def pen_socket(ws: WebSocket, role: str = "view"):
    await ws.accept()
    is_tracker = role == "tracker"
    mine, theirs = (hub.trackers, hub.viewers) if is_tracker else (hub.viewers, hub.trackers)
    mine.add(ws)
    if is_tracker:
        await hub.send_all(hub.viewers, json.dumps({"type": "tracker", "connected": True}))
    else:
        await ws.send_text(json.dumps({"type": "tracker", "connected": bool(hub.trackers)}))
        # a page that just opened (or reconnected) learns which alerts are active, so it can add and clear its red notes
        await ws.send_text(json.dumps({"type": "alerts", "alerts": monitor.active_alerts()}))
        threading.Timer(2.0, courier.deliver_due).start()       # reminders that came due while no page was open arrive now (marked late)
    try:
        while True:
            await hub.send_all(theirs, await ws.receive_text())
    except WebSocketDisconnect:
        pass
    finally:
        mine.discard(ws)
        if is_tracker and not hub.trackers:
            await hub.send_all(hub.viewers, json.dumps({"type": "tracker", "connected": False}))


class NoCacheStatic(StaticFiles):
    """Always make the browser re-check the page files, so edits show up on a normal refresh."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", NoCacheStatic(directory=WEB, html=True), name="web")
