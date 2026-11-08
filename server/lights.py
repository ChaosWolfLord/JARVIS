"""Smart lights: Govee, over the home network (Govee's LAN API) or, if you give JARVIS an API key, through Govee's cloud.

This is deliberately the whole of what JARVIS can do to your home devices: switch lights on and off, set brightness, colour
and white temperature. There is no way to unlock a door, run a camera or touch any other device from here (music is a
separate, later piece). Lights are low-risk, so they don't ask first; every command is logged in the activity log.

Local control needs "LAN Control" switched on for the light in the Govee Home app (device > gear icon > LAN Control) and a
model that supports it. It talks UDP to the light directly (port 4003): nothing leaves the house and no key is needed.
Lights that don't support it can be driven through the cloud instead: ask Govee for an API key in the app (Settings >
Apply for API Key), then put GOVEE_API_KEY=... in .env.

.env (all optional): GOVEE_API_KEY, GOVEE_IPS=192.168.1.40,192.168.1.41 (when the automatic scan can't find them).
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import persona, store
from .agent_tools import httpx

log = logging.getLogger("jarvis")

MULTICAST, SCAN_PORT, LISTEN_PORT, CONTROL_PORT = "239.255.255.250", 4001, 4002, 4003
CLOUD = "https://openapi.api.govee.com/router/api/v1"
FILE = store.STATE / "lights.json"

COLORS = {
    "red": (255, 0, 0), "orange": (255, 100, 0), "yellow": (255, 210, 0), "green": (0, 255, 0), "cyan": (0, 220, 255), "blue": (0, 60, 255),
    "purple": (140, 0, 255), "violet": (140, 0, 255), "pink": (255, 40, 140), "magenta": (255, 0, 200), "white": (255, 255, 255),
}
WHITES = {"warm": 2700, "cool": 6500, "daylight": 5000, "candle": 2000, "soft": 3000, "neutral": 4000}
SCENES = {"relax": (30, 2200), "movie": (10, 2700), "night": (5, 2000), "reading": (70, 3500), "focus": (100, 5500), "bright": (100, 4500)}


class LightError(Exception):
    """Something the user can act on; the message says what."""


@dataclass
class Light:
    id: str
    sku: str = ""
    name: str = ""
    ip: str = ""
    cloud: bool = False                       # known to Govee's cloud (so it can be driven there)
    state: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.name or (f"{self.sku} light" if self.sku else "light")

    def public(self) -> dict:
        return {"id": self.id, "name": self.label, "sku": self.sku, "ip": self.ip, "via": "home network" if self.ip else "Govee cloud", "state": self.state}


# ---- the local (LAN) protocol ----------------------------------------------------------------------

def local_addresses() -> list[str]:
    """This PC's usable IPv4 addresses, one per network adapter (multicast has to be sent out of each)."""
    found: list[str] = []
    try:
        found += [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))                     # no packet is sent; this only asks which adapter would be used
        found.append(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    return [ip for ip in dict.fromkeys(found) if not ip.startswith(("127.", "169.254."))]


class Lan:
    """Talks to Govee lights over UDP. Replies always arrive on port 4002, so one exchange at a time."""

    def __init__(self, sock=socket.socket, addresses=local_addresses) -> None:
        self.sock, self.addresses = sock, addresses
        self.lock = threading.Lock()

    def _listener(self, ips: list[str]):
        rx = self.sock(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        rx.bind(("", LISTEN_PORT))
        for ip in ips:
            try:
                rx.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(MULTICAST) + socket.inet_aton(ip))
            except OSError:
                pass
        rx.settimeout(0.3)
        return rx

    def _collect(self, rx, cmd: str, until: float, want=None) -> list[dict]:
        """Answers to `cmd` until `until`. `want` is one address (stop when it has answered) or a set of them (stop when all have)."""
        out = []
        waiting = set(want) if isinstance(want, (set, frozenset, list, tuple)) else None
        while time.time() < until:
            try:
                data, addr = rx.recvfrom(4096)
            except socket.timeout:
                continue
            except ConnectionResetError:
                continue                                     # some other device said "nothing here": not an answer, keep listening
            except OSError:
                break
            try:
                msg = json.loads(data)["msg"]
            except (ValueError, KeyError, TypeError):
                continue
            if msg.get("cmd") == cmd and isinstance(msg.get("data"), dict):
                out.append({**msg["data"], "_from": addr[0]})
                if waiting is not None:
                    waiting.discard(addr[0])
                    if not waiting:
                        break
                elif want and addr[0] == want:
                    break
        return out

    def scan(self, extra_ips=(), timeout: float = 3.0) -> list[dict]:
        """Lights that answer a scan: [{ip, device, sku, ...}]. Tries multicast out of every adapter, plus a direct ask of any known address.

        Everything is sent from the same socket that listens on port 4002. The lights answer to port 4002 whatever the sender's port was,
        and Windows Firewall lets such an answer in only when it is addressed to the socket that asked (a separate listener sees nothing)."""
        payload = json.dumps({"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}).encode()
        ips = self.addresses()
        with self.lock:
            rx = self._listener(ips)
            try:
                for ip in ips:
                    try:
                        rx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                        rx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                        rx.sendto(payload, (MULTICAST, SCAN_PORT))
                    except OSError:
                        pass
                for ip in extra_ips:
                    try:
                        rx.sendto(payload, (ip, SCAN_PORT))
                    except OSError:
                        pass
                found = self._collect(rx, "scan", time.time() + timeout)
            finally:
                rx.close()
        by_ip = {d["ip"]: d for d in found if d.get("ip")}
        return list(by_ip.values())

    def send(self, ip: str, cmd: str, data: dict) -> None:
        tx = self.sock(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            tx.sendto(json.dumps({"msg": {"cmd": cmd, "data": data}}).encode(), (ip, CONTROL_PORT))
        except OSError as e:
            raise LightError(f"couldn't reach the light at {ip} ({e.__class__.__name__}).") from None
        finally:
            tx.close()

    def statuses(self, ips: list[str], timeout: float = 2.0) -> dict[str, dict]:
        """{ip: devStatus data} for the lights that answer. Windows Firewall drops a light's direct reply unless it follows a multicast
        packet sent from the same socket (it lets such replies in for a few seconds), so a multicast scan goes out first."""
        ips = list(dict.fromkeys(ips))
        if not ips:
            return {}
        scan = json.dumps({"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}).encode()
        ask = json.dumps({"msg": {"cmd": "devStatus", "data": {}}}).encode()
        local = self.addresses()
        with self.lock:
            rx = self._listener(local)
            try:
                for ip in local:
                    try:
                        rx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                        rx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                        rx.sendto(scan, (MULTICAST, SCAN_PORT))
                    except OSError:
                        pass
                for ip in ips:
                    try:
                        rx.sendto(ask, (ip, CONTROL_PORT))
                    except OSError:
                        pass
                got = self._collect(rx, "devStatus", time.time() + timeout, want=set(ips))
            finally:
                rx.close()
        return {g["_from"]: g for g in got if g["_from"] in ips}

    def status(self, ip: str, timeout: float = 2.0) -> dict | None:
        return self.statuses([ip], timeout).get(ip)


# ---- Govee's cloud ----------------------------------------------------------------------------------

class Cloud:
    def __init__(self, key: str, client=None) -> None:
        self.key, self.client = key, client

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        own = self.client is None
        client = self.client or httpx.Client(timeout=12.0)
        try:
            resp = client.request(method, CLOUD + path, json=body, headers={"Govee-API-Key": self.key})
        except httpx.HTTPError:
            raise LightError("couldn't reach Govee's cloud. Check the internet connection.") from None
        finally:
            if own:
                client.close()
        if resp.status_code == 401 or resp.status_code == 403:
            raise LightError("Govee didn't accept the API key (GOVEE_API_KEY in .env).")
        if resp.status_code == 429:
            raise LightError("Govee's cloud is rate-limiting (10 commands a minute per light). Try again in a moment.")
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code != 200 or data.get("code") not in (200, None):
            raise LightError(f"Govee's cloud said: {data.get('message') or data.get('msg') or resp.status_code}.")
        return data

    def devices(self) -> list[dict]:
        return [d for d in self._call("GET", "/user/devices").get("data", []) if "light" in str(d.get("type", "")).lower()]

    def control(self, sku: str, device: str, cap_type: str, instance: str, value) -> None:
        self._call("POST", "/device/control", {"requestId": str(uuid.uuid4()), "payload": {
            "sku": sku, "device": device, "capability": {"type": cap_type, "instance": instance, "value": value}}})

    def state(self, sku: str, device: str) -> dict:
        caps = self._call("POST", "/device/state", {"requestId": str(uuid.uuid4()), "payload": {"sku": sku, "device": device}}).get("payload", {})
        out: dict = {}
        for c in caps.get("capabilities", []):
            value = (c.get("state") or {}).get("value")
            if c.get("instance") == "powerSwitch":
                out["on"] = bool(value)
            elif c.get("instance") == "brightness":
                out["brightness"] = value
            elif c.get("instance") == "colorRgb" and isinstance(value, int):
                out["color"] = {"r": value >> 16 & 255, "g": value >> 8 & 255, "b": value & 255}
            elif c.get("instance") == "colorTemperatureK":
                out["kelvin"] = value
        return out


# ---- the set of lights ------------------------------------------------------------------------------

def _hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(value).strip())
    return tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4)) if m else None


def parse_color(text) -> tuple[int, int, int] | None:
    t = str(text or "").strip().lower()
    return COLORS.get(t) or _hex_to_rgb(t)


class Lights:
    def __init__(self, lan: Lan | None = None, cloud=None, path=FILE) -> None:
        self.lan = lan or Lan()
        self._cloud = cloud
        self.path = path
        self.lights: dict[str, Light] = {}
        self.lock = threading.Lock()
        self.scanned = 0.0
        self.error = ""
        self._load()

    # -- known lights are remembered, so they are usable the moment JARVIS starts --
    def _load(self) -> None:
        saved = store._read(self.path, {})
        for d in saved.get("lights", []):
            if d.get("id"):
                self.lights[d["id"]] = Light(id=d["id"], sku=d.get("sku", ""), name=d.get("name", ""), ip=d.get("ip", ""), cloud=bool(d.get("cloud")))

    def _save(self) -> None:
        try:
            store._write(self.path, {"lights": [{"id": l.id, "sku": l.sku, "name": l.name, "ip": l.ip, "cloud": l.cloud} for l in self.lights.values()]})
        except OSError:
            log.warning("couldn't save the list of lights")

    @property
    def cloud(self) -> Cloud | None:
        if self._cloud:
            return self._cloud
        key = os.getenv("GOVEE_API_KEY", "").strip()
        return Cloud(key) if key else None

    def available(self) -> bool:
        """Is the lights feature on? (Always, unless JARVIS_LIGHTS=0, so the AI can answer "find my lights" before any are known.)"""
        return os.getenv("JARVIS_LIGHTS", "1") != "0"

    # -- finding lights --
    def discover(self) -> list[Light]:
        """Scans the home network (and asks Govee's cloud if there is a key); returns the lights now known."""
        self.error = ""
        extra = [ip.strip() for ip in os.getenv("GOVEE_IPS", "").split(",") if ip.strip()] + [l.ip for l in self.lights.values() if l.ip]
        try:
            found = self.lan.scan(extra_ips=list(dict.fromkeys(extra)))
        except OSError as e:
            found = []
            self.error = f"The network scan failed ({e.__class__.__name__})."
        with self.lock:
            for d in found:
                dev = str(d.get("device", d.get("ip")))
                light = self.lights.setdefault(dev, Light(id=dev))
                light.sku, light.ip = d.get("sku", light.sku), d["ip"]
        if self.cloud:
            try:
                for d in self.cloud.devices():
                    with self.lock:
                        light = self.lights.setdefault(d["device"], Light(id=d["device"]))
                        light.sku, light.cloud = d.get("sku", light.sku), True
                        light.name = light.name or d.get("deviceName", "")
            except LightError as e:
                self.error = str(e)
        self.scanned = time.time()
        self._save()
        return list(self.lights.values())

    def refresh_states(self) -> None:
        local = [l for l in self.lights.values() if l.ip]
        answers = self.lan.statuses([l.ip for l in local]) if local else {}
        for light in local:
            a = answers.get(light.ip)
            if a:
                light.state = {"on": bool(a.get("onOff")), "brightness": a.get("brightness"), "color": a.get("color"), "kelvin": a.get("colorTemInKelvin"), "reachable": True}
            else:
                light.state = {**light.state, "reachable": False}

        def from_cloud(light: Light) -> None:
            try:
                light.state = {**self.cloud.state(light.sku, light.id), "reachable": True}
            except LightError:
                light.state = {**light.state, "reachable": False}
        remote = [l for l in self.lights.values() if l.cloud and self.cloud and not l.state.get("reachable")]
        if remote:
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(from_cloud, remote))

    def rename(self, light_id: str, name: str) -> Light:
        name = re.sub(r"\s+", " ", str(name)).strip()[:40]
        light = self.lights.get(light_id)
        if not light:
            raise LightError("no such light.")
        if not name:
            raise LightError("give it a name.")
        light.name = name
        self._save()
        return light

    # -- choosing which lights a command is for --
    def pick(self, target: str = "") -> list[Light]:
        lights = list(self.lights.values())
        if not lights:
            raise LightError("I don't know of any lights yet. Turn on LAN Control in the Govee Home app (or add GOVEE_API_KEY to .env), then say “find my lights”.")
        t = re.sub(r"\b(the|my|all|every|lights?|lamps?|leds?)\b", " ", str(target or "").lower()).strip()
        t = re.sub(r"\s+", " ", t)
        if not t:
            return lights
        exact = [l for l in lights if l.name.lower() == t or l.id.lower() == t or l.ip == t]
        if exact:
            return exact
        words = [w for w in t.split() if len(w) > 1]
        match = [l for l in lights if all(w in l.name.lower() for w in words)] if words else []
        if not match:
            names = ", ".join(l.label for l in lights)
            raise LightError(f"no light called “{target}”. Known lights: {names}.")
        return match

    # -- commands --
    def command(self, target: str = "", power: bool | None = None, brightness: int | None = None, delta: int | None = None,
                color=None, kelvin: int | None = None) -> str:
        """Applies the changes to the chosen lights and returns a sentence about what happened."""
        chosen = self.pick(target)
        rgb = None
        if color not in (None, ""):
            rgb = parse_color(color)
            if not rgb:
                raise LightError(f"I don't know the colour “{color}”. Try a name like blue, or a hex code like #ff8800.")
        if kelvin is not None:
            kelvin = int(max(2000, min(9000, kelvin)))
        if brightness is not None:
            brightness = int(max(1, min(100, brightness)))
        if power is None and brightness is None and delta is None and rgb is None and kelvin is None:
            raise LightError("nothing to change: say on, off, a brightness, or a colour.")
        done, failed = [], []
        for light in chosen:
            try:
                self._apply(light, power, brightness, delta, rgb, kelvin)
                done.append(light.label)
            except LightError as e:
                failed.append(str(e) if str(e).startswith(light.label) else f"{light.label}: {e}")
        what = []
        if power is not None:
            what.append("on" if power else "off")
        if delta is not None and brightness is None:
            what.append("brighter" if delta > 0 else "dimmer")
        if brightness is not None:
            what.append(f"{brightness}% brightness")
        if rgb:
            what.append(f"colour {color}")
        if kelvin:
            what.append(f"{kelvin}K white")
        text = f"{', '.join(done)}: {' and '.join(what)}." if done else ""
        if failed:
            text = (text + " " if text else "Error: ") + "Problem with " + "; ".join(failed)
        return text.strip()

    def confirm_reachable(self, light: Light) -> bool:
        """Does the light answer right now? Sending is fire-and-forget (UDP), so without this a command to a light that is off, or on another
        network, would be reported as done. If it does not answer, one more look around the network in case it has a new address."""
        if not light.ip:
            return False
        st = light.state
        if st.get("reachable") and time.time() - st.get("checked", 0) < 45:
            return True

        def answers() -> bool:
            try:
                reply = self.lan.statuses([light.ip], timeout=1.2).get(light.ip)
            except OSError:
                reply = None
            if reply:
                st.update({"reachable": True, "checked": time.time()})
                return True
            st.update({"reachable": False})
            return False

        if answers():
            return True
        try:
            found = self.lan.scan(extra_ips=[], timeout=1.8)
        except OSError:
            found = []
        for d in found:
            if str(d.get("device", "")) == light.id and d.get("ip") and d["ip"] != light.ip:
                light.ip = d["ip"]                                   # it moved (a new address from the router)
                self._save()
                return answers()
        return answers() if any(d.get("ip") == light.ip for d in found) else False

    def why_unreachable(self, light: Light) -> str:
        mine = local_addresses()
        prefix = (light.ip or "").rsplit(".", 1)[0]
        if mine and light.ip and not any(m.rsplit(".", 1)[0] == prefix for m in mine):
            return (f"{light.label} is on a different network: it was last at {light.ip}, but this PC is on {mine[0].rsplit('.', 1)[0]}.x. "
                    "The lights have to be on the same Wi-Fi as this PC.")
        return (f"{light.label} didn't answer at {light.ip}. Is it plugged in and on this Wi-Fi? "
                "(In the Govee app, LAN Control has to be switched on for the light.)")

    def _apply(self, light: Light, power, brightness, delta, rgb, kelvin) -> None:
        if light.ip and not self.confirm_reachable(light):
            if light.cloud and self.cloud:
                self._apply_cloud(light, power, brightness, rgb, kelvin)
                return
            raise LightError(self.why_unreachable(light))
        st = light.state
        if delta is not None and brightness is None:
            brightness = int(max(1, min(100, (st.get("brightness") or 50) + delta)))
        if power is None and (brightness is not None or rgb or kelvin) and not st.get("on", True):
            power = True                                             # changing a colour or brightness switches it on
        if light.ip:
            try:
                if power is not None:
                    self.lan.send(light.ip, "turn", {"value": 1 if power else 0})
                if brightness is not None:
                    self.lan.send(light.ip, "brightness", {"value": brightness})
                if rgb:
                    self.lan.send(light.ip, "colorwc", {"color": {"r": rgb[0], "g": rgb[1], "b": rgb[2]}, "colorTemInKelvin": 0})
                elif kelvin:
                    self.lan.send(light.ip, "colorwc", {"color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": kelvin})
            except LightError:
                if not (light.cloud and self.cloud):
                    raise
                self._apply_cloud(light, power, brightness, rgb, kelvin)
        elif light.cloud and self.cloud:
            self._apply_cloud(light, power, brightness, rgb, kelvin)
        else:
            raise LightError("it isn't reachable (no home-network address and no Govee key).")
        if power is not None:
            st["on"] = power
        if brightness is not None:
            st["brightness"] = brightness
        if rgb:
            st["color"] = {"r": rgb[0], "g": rgb[1], "b": rgb[2]}
        if kelvin and not rgb:
            st["kelvin"] = kelvin

    def _apply_cloud(self, light: Light, power, brightness, rgb, kelvin) -> None:
        c = self.cloud
        if power is not None:
            c.control(light.sku, light.id, "devices.capabilities.on_off", "powerSwitch", 1 if power else 0)
        if brightness is not None:
            c.control(light.sku, light.id, "devices.capabilities.range", "brightness", brightness)
        if rgb:
            c.control(light.sku, light.id, "devices.capabilities.color_setting", "colorRgb", rgb[0] << 16 | rgb[1] << 8 | rgb[2])
        elif kelvin:
            c.control(light.sku, light.id, "devices.capabilities.color_setting", "colorTemperatureK", kelvin)


# ---- spoken commands ----------------------------------------------------------------------------------

LIGHT_WORD = re.compile(r"\b(lights?|lamps?|leds?|lighting)\b")
_STOP = {"turn", "switch", "set", "make", "change", "put", "the", "my", "all", "please", "on", "off", "dim", "brighten", "lower", "raise", "to", "color",
         "colour", "up", "down", "a", "bit", "little", "can", "you", "could", "of", "in", "at", "mode", "everything", "kill", "shut", "and", "is", "it",
         "lights", "light", "lamp", "lamps", "led", "leds", "lighting", "percent", "brightness", "brighter", "dimmer", "full", "max", "half", "more", "less",
         "scene", "go", "back", "then", "now", "jarvis", "hey", "ok", "okay", "for", "me"}
_WORDNUM = {"zero": 0, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100}
_UNITS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine"}
_FILLER = _STOP | _UNITS | set(COLORS) | set(WHITES) | set(SCENES)


def parse_command(text: str) -> dict | None:
    """Turns "turn the desk lights blue" into {target, color} etc., or None if it isn't about the lights."""
    t = re.sub(r"[^a-z0-9#% ]", " ", str(text).lower())
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(jarvis|hey jarvis) ", "", t)
    if not LIGHT_WORD.search(t) and not re.search(r"\b(relax|movie|night|reading|focus) (mode|lighting|scene)\b", t):
        return None
    if re.match(r"(what|which|how|why|who|when|where|are|is|do|does|did|has|have)\b", t):
        return None                                  # a question, not a command: the AI can look at the lights and answer
    words = t.split()
    out: dict = {}
    # a number: "to 40", "40 percent", "forty percent"
    m = re.search(r"\b(\d{1,3})\s*(?:%|percent)?(?=\s|$)", t)
    if m and 0 < int(m.group(1)) <= 100 and re.search(r"(%|percent|brightness|to \d|at \d)", t) and not re.search(r"#[0-9a-f]{6}", t):
        out["brightness"] = int(m.group(1))
    elif (m := re.search(r"\b(ten|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?: (one|two|three|four|five|six|seven|eight|nine))? percent\b", t)):
        out["brightness"] = _WORDNUM[m.group(1)] + {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}.get(m.group(2) or "", 0)
    elif re.search(r"\b(full brightness|max(imum)?|brightest|100)\b", t):
        out["brightness"] = 100
    elif re.search(r"\bhalf\b", t):
        out["brightness"] = 50
    elif re.search(r"\b(dim|dimmer|lower|darker)\b", t):
        out["delta"] = -25
    elif re.search(r"\b(brighten|brighter|raise|lighter|brightness up)\b", t):
        out["delta"] = 25
    # a scene
    scene = next((s for s in SCENES if re.search(rf"\b{s}\b", t)), None)
    if scene and ("mode" in words or "scene" in words or "lighting" in words or LIGHT_WORD.search(t)):
        out["brightness"], out["kelvin"] = SCENES[scene]
        out["scene"] = scene
        out.pop("delta", None)
    # colour or white temperature
    hexa = re.search(r"#([0-9a-f]{6})\b", t)
    color = next((c for c in COLORS if re.search(rf"\b{c}\b", t)), None)
    white = next((w for w in WHITES if re.search(rf"\b{w}\b", t)), None)
    if hexa:
        out["color"] = "#" + hexa.group(1)
    elif color == "white" and not white:
        out["kelvin"] = 4500
    elif color:
        out["color"] = color
    elif white:
        out["kelvin"] = WHITES[white]
    # on / off
    if re.search(r"\b(off|kill|shut)\b", t):
        out["power"] = False
    elif re.search(r"\bon\b", t) or re.search(r"\b(wake|light up)\b", t):
        out["power"] = True
    elif not out:
        return None
    # which lights: what stands before the word "lights", minus the command words
    idx = next((i for i, w in enumerate(words) if LIGHT_WORD.fullmatch(w)), len(words))
    name = [w for w in words[:idx] if w not in _FILLER and not w.isdigit() and w not in _WORDNUM and not w.startswith("#")]
    after = [w for w in words[idx + 1:] if w not in _FILLER and not w.isdigit() and w not in _WORDNUM and not w.startswith("#")] if not name else []
    target = " ".join(name or after[:3])
    if target:
        out["target"] = target
    return out


lights = Lights()


def available() -> bool:
    return lights.available()


def describe_lights(items: list[Light]) -> str:
    out = []
    for l in items:
        s = l.state
        bits = ["on" if s.get("on") else "off" if "on" in s else "state unknown"]
        if s.get("brightness") is not None:
            bits.append(f"{s['brightness']}%")
        if s.get("reachable") is False:
            bits.append("not answering")
        out.append(f"- {l.label} ({l.sku or 'unknown model'}, {'home network' if l.ip else 'Govee cloud'}): {', '.join(bits)}")
    return "\n".join(out) or "No lights are known yet."


def tool(args: dict, registry: Lights | None = None) -> str:
    """The AI's `lights` tool: list, find, or change lights. Errors come back as text starting with 'Error'."""
    reg = registry or lights
    action = str(args.get("action") or "set")
    try:
        if action == "scan":
            reg.discover()
            reg.refresh_states()
            return describe_lights(list(reg.lights.values())) + (f"\n{reg.error}" if reg.error else "")
        if action == "list":
            reg.refresh_states()
            return describe_lights(list(reg.lights.values()))
        brightness = args.get("brightness")
        kelvin = args.get("kelvin")
        scene = SCENES.get(str(args.get("scene") or "").lower())
        if scene:
            brightness, kelvin = scene
        return reg.command(
            target=str(args.get("target") or ""), power=args.get("power") if isinstance(args.get("power"), bool) else None,
            brightness=int(brightness) if brightness is not None else None, color=args.get("color"),
            kelvin=int(kelvin) if kelvin is not None else None,
        )
    except (LightError, ValueError, TypeError) as e:
        return f"Error: {e}"


def handle_voice(text: str, registry: Lights | None = None) -> dict:
    """A spoken or typed light command: {handled, text}. handled is False when it isn't about the lights."""
    reg = registry or lights
    cmd = parse_command(text)
    if cmd is None:
        return {"handled": False, "text": ""}
    try:
        result = reg.command(target=cmd.get("target", ""), power=cmd.get("power"), brightness=cmd.get("brightness"), delta=cmd.get("delta"),
                             color=cmd.get("color"), kelvin=cmd.get("kelvin"))
    except LightError as e:
        return {"handled": True, "ok": False, "text": persona.failure(str(e))}
    if result.startswith("Error"):                                    # every light failed: say why, never a cheerful "done"
        return {"handled": True, "ok": False, "text": persona.failure(result.removeprefix("Error:").replace("Problem with ", "", 1).strip())}
    text = persona.light_reply(cmd)
    if "Problem with " in result:                                     # some worked and some didn't
        text += " But " + result.split("Problem with ", 1)[1].strip()
    return {"handled": True, "ok": True, "text": text}
