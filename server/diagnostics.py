"""System diagnostics: how the PC, the network and JARVIS itself are doing, and a monitor that raises alerts.

Everything here is read-only and needs no extra packages or administrator rights: quick numbers come straight from Windows
through ctypes (CPU, memory, disks, uptime) and sockets (internet), and slower facts (drive health, antivirus, firewall,
recent errors, the busiest programs, Wi-Fi) from short PowerShell commands that are run rarely and cached. Nothing leaves
the PC unless you ask JARVIS about it, and then only a short summary, never raw logs.

The Monitor samples in the background, keeps a few hours of history for the graphs, and turns problems into alerts
(see `evaluate`) which the page shows as red sticky notes and speaks.
"""
from __future__ import annotations

import collections
import ctypes
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from ctypes import wintypes

from . import store

log = logging.getLogger("jarvis")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
WINDOWS = sys.platform == "win32"

FAST_EVERY = 5.0         # seconds between CPU/memory samples
HISTORY_EVERY = 10.0     # seconds between points kept for the graphs
HISTORY_POINTS = 1080    # 3 hours of graph points
DISKS_EVERY = 60.0
NET_EVERY = 30.0
SLOW_EVERY = 900.0       # drive health, antivirus, firewall, error log (each look starts a PowerShell, so not every few minutes)
CHECK_EVERY = 30.0       # how often the alert rules are looked at


def _env_num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


# ---- quick metrics ------------------------------------------------------------------------------

class _MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def memory() -> dict:
    """{pct, used_gb, total_gb} of physical memory."""
    if not WINDOWS:
        return {"pct": 0.0, "used_gb": 0.0, "total_gb": 0.0}
    s = _MemStatus()
    s.dwLength = ctypes.sizeof(s)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
    total, free = s.ullTotalPhys / 2**30, s.ullAvailPhys / 2**30
    return {"pct": float(s.dwMemoryLoad), "used_gb": round(total - free, 1), "total_gb": round(total, 1)}


class CpuMeter:
    """Whole-PC processor load since the previous call, from Windows' own idle/busy time counters."""

    def __init__(self, read=None) -> None:
        self.read = read or self._read_windows
        self.prev = self.read()

    @staticmethod
    def _read_windows() -> tuple[int, int, int]:
        if not WINDOWS:
            return (0, 0, 0)
        idle, kernel, user = (wintypes.FILETIME() for _ in range(3))
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
        value = lambda f: (f.dwHighDateTime << 32) | f.dwLowDateTime  # noqa: E731
        return value(idle), value(kernel), value(user)

    def percent(self) -> float:
        now = self.read()
        d_idle, d_kernel, d_user = (a - b for a, b in zip(now, self.prev))
        self.prev = now
        busy_and_idle = d_kernel + d_user          # Windows counts idle time inside kernel time
        return round(max(0.0, min(100.0, 100.0 * (1 - d_idle / busy_and_idle))), 1) if busy_and_idle > 0 else 0.0


def uptime_hours() -> float:
    if not WINDOWS:
        return 0.0
    ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
    return round(ctypes.windll.kernel32.GetTickCount64() / 3_600_000, 1)


def disks() -> list[dict]:
    """The fixed drives: letter, free and total space, percent free."""
    out = []
    if not WINDOWS:
        return out
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        if not mask & (1 << i):
            continue
        letter = chr(65 + i)
        if ctypes.windll.kernel32.GetDriveTypeW(f"{letter}:\\") != 3:     # 3 = a fixed (not removable or network) drive
            continue
        try:
            u = shutil.disk_usage(f"{letter}:\\")
        except OSError:
            continue
        out.append({"drive": f"{letter}:", "free_gb": round(u.free / 2**30, 1), "total_gb": round(u.total / 2**30, 1),
                    "free_pct": round(100 * u.free / u.total, 1) if u.total else 0.0,
                    "system": letter == os.getenv("SystemDrive", "C:")[0].upper()})
    return out


def network(connect=socket.create_connection, resolve=socket.getaddrinfo, wifi=None) -> dict:
    """Is the internet reachable (and how fast), does name lookup work, and how strong is the Wi-Fi?"""
    result = {"internet": False, "ms": None, "dns": False, "wifi": None}
    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53)):
        t0 = time.perf_counter()
        try:
            connect((host, port), timeout=2.0).close()
            result["internet"], result["ms"] = True, int((time.perf_counter() - t0) * 1000)
            break
        except OSError:
            continue
    try:
        resolve("example.com", 443)
        result["dns"] = True
    except OSError:
        pass
    result["wifi"] = (wifi or wifi_info)()
    return result


def wifi_info(run=None) -> dict | None:
    """{ssid, signal} from `netsh wlan show interfaces`, or None on a wired PC."""
    if not WINDOWS:
        return None
    try:
        text = (run or (lambda: subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, timeout=8, creationflags=NO_WINDOW).stdout))()
    except (OSError, subprocess.SubprocessError):
        return None
    ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", text, re.M)
    signal = re.search(r"^\s*Signal\s*:\s*(\d+)%", text, re.M)
    return {"ssid": ssid.group(1).strip(), "signal": int(signal.group(1))} if ssid and signal else None


# ---- slower facts (PowerShell, run rarely) --------------------------------------------------------

_SLOW_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$o = @{}
$o.disk_health = @(Get-PhysicalDisk | ForEach-Object { @{ name = [string]$_.FriendlyName; health = [string]$_.HealthStatus; status = [string]$_.OperationalStatus } })
$mp = Get-MpComputerStatus
$o.defender = @{ realtime = [bool]$mp.RealTimeProtectionEnabled; sig_age_days = [int]$mp.AntivirusSignatureAge }
$o.firewall = @(Get-NetFirewallProfile | ForEach-Object { @{ name = [string]$_.Name; enabled = [bool]$_.Enabled } })
$ev = @(Get-WinEvent -FilterHashtable @{ LogName = 'System','Application'; Level = 1,2; StartTime = (Get-Date).AddHours(-24) } -MaxEvents 300)
$o.errors_24h = @{ count = $ev.Count; top = @($ev | Group-Object ProviderName | Sort-Object Count -Descending | Select-Object -First 5 | ForEach-Object { @{ provider = [string]$_.Name; count = $_.Count } }) }
$o | ConvertTo-Json -Depth 5 -Compress
"""

_PROCESS_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$a = @{}; Get-Process | ForEach-Object { $a[$_.Id] = $_.CPU }
Start-Sleep -Seconds 1
$cores = [Environment]::ProcessorCount
$all = Get-Process | ForEach-Object { @{ name = [string]$_.ProcessName; id = $_.Id; mb = [int]($_.WorkingSet64 / 1MB); cpu = [math]::Round((($_.CPU - $a[$_.Id]) / $cores) * 100, 1) } }
@{ by_memory = @($all | Sort-Object { $_.mb } -Descending | Select-Object -First 6); by_cpu = @($all | Sort-Object { $_.cpu } -Descending | Select-Object -First 6) } | ConvertTo-Json -Depth 4 -Compress
"""


def powershell_json(script: str, timeout: float = 40.0, run=None):
    """Runs a PowerShell script that prints one line of JSON; returns it parsed, or None if anything went wrong."""
    if not WINDOWS:
        return None
    try:
        if run:
            text = run(script)
        else:
            text = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                                  capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW).stdout
        return json.loads(text.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def slow_facts(run=None) -> dict:
    return powershell_json(_SLOW_SCRIPT, run=run) or {}


def busiest_processes(run=None) -> dict:
    return powershell_json(_PROCESS_SCRIPT, run=run) or {"by_memory": [], "by_cpu": []}


# ---- JARVIS's own health --------------------------------------------------------------------------

def folder_size_mb(path, limit: int = 200_000) -> int:
    total = 0
    try:
        for i, f in enumerate(path.rglob("*")):
            if i > limit:
                break
            if f.is_file():
                total += f.stat().st_size
    except OSError:
        pass
    return round(total / 2**20)


_log_watch: dict[str, dict] = {}


def count_errors(text: str) -> int:
    """How many errors the lines of log text hold: a traceback is one error, and so is a lone ERROR line (uvicorn's "ERROR: Exception in ASGI
    application" is followed by a traceback, which must not make it two)."""
    lines = text.splitlines()
    total = 0
    for i, ln in enumerate(lines):
        if ln.startswith("Traceback (most recent"):
            total += 1
        elif re.search(r"\bERROR\b", ln) and not (i + 1 < len(lines) and lines[i + 1].startswith("Traceback (most recent")):
            total += 1
    return total


def recent_log_errors(minutes: int = 10, path=None, now: float | None = None) -> int:
    """How many errors JARVIS's log has gained in the last few minutes. The log lines carry no timestamps, so this watches the file as it grows:
    each look counts what was added since the last one, and what was already in the log when JARVIS started (or when this was first asked) is
    not new. Before, it counted errors among the last 400 lines whatever their age, so an old burst kept the alert up for days on a quiet log."""
    path = path or (store.STATE / "logs" / "jarvis.log")
    now = time.time() if now is None else now
    try:
        size = path.stat().st_size
    except OSError:
        _log_watch.setdefault(str(path), {"offset": 0, "hits": collections.deque()})        # no log yet: whatever it gets from now on is new
        return 0
    watch = _log_watch.get(str(path))
    if watch is None or size < watch["offset"]:                      # first look, or a fresh log: start from here
        _log_watch[str(path)] = {"offset": size, "hits": collections.deque()}
        return 0
    if size > watch["offset"]:
        try:
            with path.open("rb") as f:
                f.seek(watch["offset"])
                added = f.read(size - watch["offset"]).decode("utf-8", errors="replace")
        except OSError:
            return sum(n for _, n in watch["hits"])
        watch["offset"] = size
        found = count_errors(added)
        if found:
            watch["hits"].append((now, found))
    while watch["hits"] and watch["hits"][0][0] < now - minutes * 60:
        watch["hits"].popleft()
    return sum(n for _, n in watch["hits"])


# ---- alerts ----------------------------------------------------------------------------------------

def alert(id_: str, level: str, title: str, text: str, speak: str | None = None) -> dict:
    return {"id": id_, "level": level, "title": title, "text": text, "speak": speak or f"{title}. {text}"}


def evaluate(latest: dict, history: list[dict], now: float | None = None) -> dict[str, dict]:
    """The problems visible in the latest measurements, as {alert id: alert}. Pure: it only looks at what it is given.

    Thresholds can be changed in .env: JARVIS_ALERT_DISK_FREE_PCT (10), JARVIS_ALERT_DISK_FREE_GB (8), JARVIS_ALERT_MEM_PCT (92),
    JARVIS_ALERT_CPU_PCT (95)."""
    now = time.time() if now is None else now
    out: dict[str, dict] = {}

    for d in latest.get("disks", []):
        if d["free_pct"] < _env_num("JARVIS_ALERT_DISK_FREE_PCT", 10) or d["free_gb"] < _env_num("JARVIS_ALERT_DISK_FREE_GB", 8):
            out[f"disk-low-{d['drive']}"] = alert(f"disk-low-{d['drive']}", "warn", f"Drive {d['drive']} is almost full",
                                                   f"Only {d['free_gb']:.0f} GB free ({d['free_pct']:.0f}%).",
                                                   f"Warning. Drive {d['drive'][0]} is almost full. Only {d['free_gb']:.0f} gigabytes are free.")

    def sustained(key: str, limit: float, seconds: float, minimum: int) -> float | None:
        recent = [p for p in history if p["t"] >= now - seconds and key in p]
        return min(p[key] for p in recent) if len(recent) >= minimum and min(p[key] for p in recent) >= limit else None

    if (low := sustained("mem", _env_num("JARVIS_ALERT_MEM_PCT", 92), 180, 12)) is not None:
        out["memory-high"] = alert("memory-high", "warn", "Memory is nearly full", f"Memory has been over {low:.0f}% for 3 minutes. Closing programs will help.",
                                   "Warning. The computer's memory has been nearly full for three minutes.")
    if (low := sustained("cpu", _env_num("JARVIS_ALERT_CPU_PCT", 95), 300, 20)) is not None:
        out["cpu-high"] = alert("cpu-high", "warn", "The processor is maxed out", f"CPU has been over {low:.0f}% for 5 minutes.",
                                "Warning. The processor has been working flat out for five minutes.")

    net = latest.get("net") or {}
    if latest.get("net_failures", 0) >= 2:
        out["internet-down"] = alert("internet-down", "critical", "No internet", "The PC can't reach the internet, so the AI, weather and mail won't work.",
                                     "Warning. There is no internet connection.")
    elif net.get("internet") and not net.get("dns"):
        out["dns-broken"] = alert("dns-broken", "warn", "Name lookups are failing", "The internet is reachable but web addresses won't resolve.",
                                  "Warning. Web addresses are not resolving.")
    wifi = net.get("wifi")
    if wifi and wifi["signal"] < 25 and net.get("internet"):
        out["wifi-weak"] = alert("wifi-weak", "warn", "Wi-Fi signal is very weak", f"Signal is {wifi['signal']}% on {wifi['ssid']}.", "Warning. The Wi-Fi signal is very weak.")

    slow = latest.get("slow") or {}
    for disk in slow.get("disk_health", []):
        if disk.get("health") not in (None, "", "Healthy"):
            out[f"disk-health-{disk.get('name', '?')}"] = alert(f"disk-health-{disk.get('name', '?')}", "critical", "A drive reports a problem",
                                                                 f"{disk.get('name', 'A drive')} says it is {disk.get('health')}. Back up your files.",
                                                                 "Warning. A drive is reporting a health problem. Back up your files.")
    if (slow.get("defender") or {}).get("realtime") is False:
        out["defender-off"] = alert("defender-off", "warn", "Antivirus protection is off", "Windows real-time protection is switched off.", "Warning. Antivirus protection is switched off.")
    if any(p.get("name") == "Public" and p.get("enabled") is False for p in slow.get("firewall", [])):
        out["firewall-off"] = alert("firewall-off", "warn", "Firewall is off for public networks", "Turn it back on in Windows Security.", "Warning. The firewall is off for public networks.")

    j = latest.get("jarvis") or {}
    if j.get("wake_configured") and not j.get("wake_running"):
        out["wake-down"] = alert("wake-down", "warn", "The wake word listener stopped", j.get("wake_error") or "JARVIS can't hear its name offline right now.",
                                 "Warning. The offline wake word listener has stopped.")
    if j.get("tracker_expected") and not j.get("tracker_connected"):
        out["tracker-down"] = alert("tracker-down", "warn", "The pen tracker isn't connected", "Touch input won't work until it reconnects.", "Warning. The pen tracker is not connected.")
    for s in j.get("mcp_errors", []):
        out[f"mcp-{s['name']}"] = alert(f"mcp-{s['name']}", "warn", f"Tool connection '{s['name']}' failed", s.get("error") or "It isn't working.", f"Warning. The tool connection {s['name']} failed.")
    if j.get("log_errors", 0) >= 10:
        out["jarvis-errors"] = alert("jarvis-errors", "warn", "JARVIS is logging many errors", f"{j['log_errors']} recent errors. See %LOCALAPPDATA%\\jarvis\\logs.", "Warning. JARVIS is logging many errors.")
    return out


# ---- the monitor ----------------------------------------------------------------------------------

class Monitor:
    """Samples in a background thread, keeps the history, and reports alerts as they appear and clear."""

    def __init__(self, jarvis_probe=None, notify=None, cpu_meter=None, fast=None, slow=None, nets=None, disk_fn=None) -> None:
        self.jarvis_probe = jarvis_probe or (lambda: {})
        self.notify = notify or (lambda event: None)
        self.cpu = cpu_meter or CpuMeter()
        self._fast, self._slow, self._net, self._disks = fast or memory, slow or slow_facts, nets or network, disk_fn or disks
        self.history: deque = deque(maxlen=HISTORY_POINTS)
        self.latest: dict = {}
        self.alerts: dict[str, dict] = {}
        self.stop_flag = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.net_failures = 0
        self._due = {"history": 0.0, "disks": 0.0, "net": 0.0, "slow": 0.0, "check": 0.0}

    def start(self) -> None:
        if self.thread:
            return
        self.thread = threading.Thread(target=self._run, daemon=True, name="diagnostics")
        self.thread.start()

    def stop(self) -> None:
        self.stop_flag.set()

    def _run(self) -> None:
        while not self.stop_flag.is_set():
            try:
                self.step(time.time())
            except Exception:  # noqa: BLE001 - monitoring must never take the server down
                log.exception("diagnostics step failed")
            self.stop_flag.wait(FAST_EVERY)

    def step(self, now: float) -> None:
        """One pass: take the quick measurements, and whichever slower ones are due; check the alert rules when due."""
        mem, cpu = self._fast(), self.cpu.percent()
        with self.lock:
            self.latest.update(t=now, cpu=cpu, mem=mem, uptime_h=uptime_hours())
        if now >= self._due["history"]:
            self._due["history"] = now + HISTORY_EVERY
            self.history.append({"t": now, "cpu": cpu, "mem": mem["pct"]})
        if now >= self._due["disks"]:
            self._due["disks"] = now + DISKS_EVERY
            with self.lock:
                self.latest["disks"] = self._disks()
        if now >= self._due["net"]:
            self._due["net"] = now + NET_EVERY
            net = self._net()
            self.net_failures = 0 if net["internet"] else self.net_failures + 1
            with self.lock:
                self.latest.update(net=net, net_failures=self.net_failures)
        if now >= self._due["slow"]:
            self._due["slow"] = now + SLOW_EVERY
            facts = self._slow()
            with self.lock:
                self.latest["slow"] = facts
        with self.lock:
            self.latest["jarvis"] = self.jarvis_probe()
        if now >= self._due["check"] and os.getenv("JARVIS_ALERTS", "1") != "0":
            self._due["check"] = now + CHECK_EVERY
            self.check(now)

    def check(self, now: float | None = None) -> None:
        with self.lock:
            latest = dict(self.latest)
        found = evaluate(latest, list(self.history), now)
        for id_, a in found.items():
            if id_ not in self.alerts:
                self.alerts[id_] = {**a, "since": time.time()}
                self.notify({"type": "alert", "state": "new", **self.alerts[id_]})
        for id_ in [i for i in self.alerts if i not in found]:
            gone = self.alerts.pop(id_)
            self.notify({"type": "alert", "state": "resolved", "id": id_, "title": gone["title"]})

    def snapshot(self) -> dict:
        with self.lock:
            latest = json.loads(json.dumps(self.latest, default=str))
        return {**latest, "alerts": list(self.alerts.values()),
                "history": [{"t": int(p["t"]), "cpu": p["cpu"], "mem": p["mem"]} for p in list(self.history)[-360:]]}

    def active_alerts(self) -> list[dict]:
        return list(self.alerts.values())


current: Monitor | None = None      # the running monitor (set by main.py), so the AI tools can read it


# ---- text for the AI and for speaking -------------------------------------------------------------------

def summary(snap: dict) -> str:
    """A short plain-English status, good to read aloud."""
    if not snap.get("cpu") and snap.get("cpu") != 0:
        return "I haven't taken my first measurements yet. Ask again in a few seconds."
    parts = []
    alerts = snap.get("alerts") or []
    parts.append("The system looks healthy." if not alerts else f"There {'is' if len(alerts) == 1 else 'are'} {len(alerts)} problem{'s' if len(alerts) != 1 else ''}: " +
                 "; ".join(a["title"] for a in alerts) + ".")
    m = snap.get("mem") or {}
    parts.append(f"The processor is at {snap['cpu']:.0f} percent and memory is {m.get('pct', 0):.0f} percent used, {m.get('used_gb', 0):.0f} of {m.get('total_gb', 0):.0f} gigabytes.")
    system = next((d for d in snap.get("disks", []) if d.get("system")), None) or (snap.get("disks") or [None])[0]
    if system:
        parts.append(f"Drive {system['drive'][0]} has {system['free_gb']:.0f} gigabytes free.")
    net = snap.get("net") or {}
    if net:
        parts.append(("The internet is up" + (f", {net['ms']} milliseconds away" if net.get("ms") else "") + ".") if net.get("internet") else "The internet is down.")
    j = snap.get("jarvis") or {}
    if j:
        bits = [f"{'the wake word is listening' if j['wake_running'] else 'the wake word is off'}" if j.get("wake_configured") else None,
                f"{j['free_requests']} free requests left today" if j.get("free_requests") is not None else None]
        parts.append("JARVIS: " + ", ".join(b for b in bits if b) + "." if any(bits) else "JARVIS is running normally.")
    up = snap.get("uptime_h")
    if up:
        parts.append(f"The PC has been on for {up:.0f} hours.")
    return " ".join(parts)


def details(area: str, snap: dict, run=None) -> str:
    """More detail on one area for the AI: processes, disks, network, security, errors or jarvis."""
    area = (area or "").lower()
    if area == "processes":
        p = busiest_processes(run)
        fmt = lambda rows, key, unit: "; ".join(f"{r['name']} (id {r['id']}) {r[key]}{unit}" for r in rows) or "none"  # noqa: E731
        return f"Using the most memory: {fmt(p['by_memory'], 'mb', ' MB')}.\nUsing the most processor: {fmt(p['by_cpu'], 'cpu', '%')}."
    if area == "disks":
        return "\n".join(f"{d['drive']} {d['free_gb']:.0f} GB free of {d['total_gb']:.0f} GB ({d['free_pct']:.0f}% free)" for d in snap.get("disks", [])) or "No drive information yet."
    if area == "network":
        n = snap.get("net") or {}
        wifi = n.get("wifi")
        return (f"Internet: {'up' if n.get('internet') else 'down'}" + (f" ({n['ms']} ms)" if n.get("ms") else "") + f". Name lookups: {'working' if n.get('dns') else 'failing'}. "
                + (f"Wi-Fi: {wifi['ssid']} at {wifi['signal']}%." if wifi else "Wired or no Wi-Fi."))
    if area == "security":
        s = snap.get("slow") or {}
        d, fw = s.get("defender") or {}, s.get("firewall") or []
        return (f"Antivirus real-time protection: {'on' if d.get('realtime') else 'OFF' if d else 'unknown'}"
                + (f", definitions {d.get('sig_age_days')} days old" if d.get("sig_age_days") is not None else "")
                + ". Firewall: " + (", ".join(f"{p['name']} {'on' if p['enabled'] else 'OFF'}" for p in fw) or "unknown") + ".")
    if area == "errors":
        e = (snap.get("slow") or {}).get("errors_24h") or {}
        top = ", ".join(f"{t['provider']} x{t['count']}" for t in e.get("top", []))
        return f"{e.get('count', 0)} serious errors in the Windows logs in the last 24 hours" + (f". Most from: {top}." if top else ".")
    if area == "jarvis":
        return json.dumps(snap.get("jarvis") or {}, indent=1)
    return "Areas: processes, disks, network, security, errors, jarvis."
