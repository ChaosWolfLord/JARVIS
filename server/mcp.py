"""MCP connector: lets JARVIS use tools from any MCP server (the Model Context Protocol, a standard way for programs to
offer tools to an AI: files, GitHub, databases, home automation, calendars, thousands more).

Servers are listed in data/mcp.json (see data/mcp.example.json). JARVIS starts each one (a program on this PC, or a web
address), asks it which tools it has, and offers them to the AI as tools named mcp__<server>__<tool>. Every call asks
you first, unless you list that tool under "autoApprove" for its server, because a tool can do anything its program can.
What comes back is treated as outside data, never as instructions.

This is a small client written for JARVIS (no extra packages): it speaks JSON-RPC over a program's standard input and
output ("stdio") or over HTTP ("streamable HTTP").
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import store
from .agent_tools import httpx

log = logging.getLogger("jarvis")

CONFIG_FILE = store.DATA / "mcp.json"
PROTOCOL = "2025-06-18"
INIT_TIMEOUT = 90.0       # the first run of "npx" may download the server
CALL_TIMEOUT = 60.0
MAX_RESULT = 6000
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class McpError(Exception):
    """A server problem, in words the user can act on."""


# ---- config ---------------------------------------------------------------------

def expand(value, env=None):
    """${NAME} in the config is replaced from the environment (and .env), so tokens never sit in the config file."""
    env = os.environ if env is None else env
    if isinstance(value, str):
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: env.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [expand(v, env) for v in value]
    if isinstance(value, dict):
        return {k: expand(v, env) for k, v in value.items()}
    return value


def load_config(path: Path = CONFIG_FILE) -> dict[str, dict]:
    """{server name: settings} for the servers that are switched on. Bad entries are skipped, never fatal."""
    try:
        raw = json.loads(path.read_text("utf-8-sig"))   # Notepad saves a BOM; accept it
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("couldn't read %s: %s", path, e)
        return {}
    servers = raw.get("servers", raw.get("mcpServers", {})) if isinstance(raw, dict) else {}
    out = {}
    for name, cfg in (servers or {}).items():
        if not isinstance(cfg, dict) or cfg.get("disabled") or not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", str(name)):
            continue
        if not (cfg.get("command") or cfg.get("url")):
            continue
        out[name] = cfg
    return out


def tool_function_name(server: str, tool: str, taken: set[str]) -> str:
    """A name the AI services accept (letters, digits, _ and -, at most 64) that is stable and unique."""
    clean = re.sub(r"[^A-Za-z0-9_-]", "_", tool)
    name = f"mcp__{server}__{clean}"
    if len(name) > 64 or name in taken:
        digest = hashlib.sha1(f"{server}/{tool}".encode()).hexdigest()[:6]
        name = f"{name[:57]}_{digest}"
    taken.add(name)
    return name


def clean_schema(schema) -> dict:
    """The tool's input schema in a form the AI services accept: an object with properties, no $schema keys."""
    if not isinstance(schema, dict) or schema.get("type") not in (None, "object"):
        return {"type": "object", "properties": {}}

    def scrub(node):
        if isinstance(node, dict):
            return {k: scrub(v) for k, v in node.items() if k not in ("$schema", "$id")}
        if isinstance(node, list):
            return [scrub(v) for v in node]
        return node

    out = scrub(schema)
    out["type"] = "object"
    out.setdefault("properties", {})
    return out


def result_text(result: dict) -> str:
    """The text of a tools/call result."""
    parts = []
    for item in result.get("content") or []:
        kind = item.get("type")
        if kind == "text":
            parts.append(str(item.get("text", "")))
        elif kind == "resource":
            res = item.get("resource") or {}
            parts.append(str(res.get("text") or f"[resource {res.get('uri', '')}]"))
        elif kind == "image":
            parts.append("[an image was returned; images can't be shown here]")
        elif kind == "audio":
            parts.append("[audio was returned]")
    if not parts and result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"])[:MAX_RESULT])
    return "\n".join(parts).strip() or "(the tool returned nothing)"


# ---- connections ----------------------------------------------------------------

class Connection:
    """One server. Subclasses send a JSON-RPC request and return its result."""

    def __init__(self, name: str, cfg: dict) -> None:
        self.name = name
        self.cfg = cfg
        self.tools: list[dict] = []
        self.state = "starting"     # starting | ready | error
        self.error = ""

    def request(self, method: str, params: dict | None = None, timeout: float = CALL_TIMEOUT) -> dict:
        raise NotImplementedError

    def notify(self, method: str, params: dict | None = None) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def connect(self) -> None:
        self.start()
        self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "JARVIS", "version": "1.0"}}, INIT_TIMEOUT)
        self.notify("notifications/initialized")
        tools, cursor = [], None
        for _ in range(20):                                   # follow "next page" links, within reason
            page = self.request("tools/list", {"cursor": cursor} if cursor else {}, 30.0)
            tools += page.get("tools") or []
            cursor = page.get("nextCursor")
            if not cursor:
                break
        self.tools = [t for t in tools if isinstance(t, dict) and t.get("name")]

    def start(self) -> None:
        pass


class StdioConnection(Connection):
    def __init__(self, name: str, cfg: dict) -> None:
        super().__init__(name, cfg)
        self.proc: subprocess.Popen | None = None
        self.next_id = 0
        self.waiting: dict[int, dict] = {}
        self.lock = threading.Lock()
        self.stderr_tail: list[str] = []

    def start(self) -> None:
        command = str(self.cfg["command"])
        exe = shutil.which(command) or command            # finds npx.cmd, uvx.exe, python and so on
        env = {**os.environ, **{k: str(v) for k, v in expand(self.cfg.get("env") or {}).items()}}
        args = [str(a) for a in expand(self.cfg.get("args") or [])]
        try:
            self.proc = subprocess.Popen(
                [exe, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                cwd=expand(self.cfg.get("cwd")) or None, creationflags=NO_WINDOW,
            )
        except OSError as e:
            raise McpError(f"couldn't start {command!r}: {e.strerror or e}. Is it installed?") from None
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._stderr_loop, daemon=True).start()

    def _stderr_loop(self) -> None:
        for raw in self.proc.stderr:
            self.stderr_tail = (self.stderr_tail + [raw.decode("utf-8", "replace").rstrip()])[-8:]

    def _read_loop(self) -> None:
        for raw in self.proc.stdout:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue                                    # the server printed something that isn't a message
            if "id" in msg and ("result" in msg or "error" in msg):
                with self.lock:
                    slot = self.waiting.pop(msg["id"], None)
                if slot:
                    slot["msg"] = msg
                    slot["event"].set()
            elif "id" in msg and "method" in msg:            # the server is asking us something
                if msg["method"] == "ping":
                    self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
                else:
                    self._send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "JARVIS doesn't support that request"}})
        with self.lock:                                      # the program ended: let everyone waiting know
            for slot in self.waiting.values():
                slot["msg"] = {"error": {"message": "the server program stopped"}}
                slot["event"].set()
            self.waiting.clear()

    def _send(self, message: dict) -> None:
        try:
            self.proc.stdin.write((json.dumps(message) + "\n").encode())
            self.proc.stdin.flush()
        except (OSError, ValueError):
            raise McpError("the server program isn't running") from None

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def request(self, method: str, params: dict | None = None, timeout: float = CALL_TIMEOUT) -> dict:
        slot = {"event": threading.Event(), "msg": None}
        with self.lock:
            self.next_id += 1
            rid = self.next_id
            self.waiting[rid] = slot
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        if not slot["event"].wait(timeout):
            with self.lock:
                self.waiting.pop(rid, None)
            tail = f" It said: {self.stderr_tail[-1]}" if self.stderr_tail else ""
            raise McpError(f"no answer to {method} within {timeout:.0f}s.{tail}")
        msg = slot["msg"]
        if "error" in msg:
            raise McpError(str(msg["error"].get("message", msg["error"])))
        return msg.get("result") or {}

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class HttpConnection(Connection):
    """Streamable HTTP: every message is a POST; the answer is JSON, or an event stream that contains it."""

    def __init__(self, name: str, cfg: dict, client=None) -> None:
        super().__init__(name, cfg)
        self.client = client or httpx.Client(timeout=CALL_TIMEOUT)
        self.session: str | None = None
        self.next_id = 0
        self.url = str(expand(cfg["url"]))

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             **{k: str(v) for k, v in expand(self.cfg.get("headers") or {}).items()}}
        if self.session:
            h["Mcp-Session-Id"] = self.session
        return h

    def _post(self, body: dict, timeout: float):
        try:
            return self.client.post(self.url, json=body, headers=self._headers(), timeout=timeout)
        except httpx.HTTPError as e:
            raise McpError(f"couldn't reach {self.url}: {e.__class__.__name__}") from None

    def request(self, method: str, params: dict | None = None, timeout: float = CALL_TIMEOUT) -> dict:
        self.next_id += 1
        rid = self.next_id
        resp = self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}, timeout)
        if resp.status_code in (401, 403):
            raise McpError("the server refused access: check its token in the config")
        if resp.status_code >= 400:
            raise McpError(f"the server answered HTTP {resp.status_code}")
        if resp.headers.get("mcp-session-id"):
            self.session = resp.headers["mcp-session-id"]
        msg = self._find_response(resp, rid)
        if "error" in msg:
            raise McpError(str(msg["error"].get("message", msg["error"])))
        return msg.get("result") or {}

    @staticmethod
    def _find_response(resp, rid: int) -> dict:
        kind = resp.headers.get("content-type", "")
        if "text/event-stream" in kind:
            for line in resp.text.splitlines():
                if line.startswith("data:"):
                    try:
                        msg = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    if msg.get("id") == rid:
                        return msg
            raise McpError("the server's answer didn't contain a reply")
        try:
            msg = resp.json()
        except ValueError:
            raise McpError("the server's answer wasn't JSON") from None
        if isinstance(msg, list):
            msg = next((m for m in msg if m.get("id") == rid), {})
        return msg

    def notify(self, method: str, params: dict | None = None) -> None:
        self._post({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})}, 15.0)

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:  # noqa: BLE001
            pass


# ---- the manager ------------------------------------------------------------------

class Manager:
    """All configured servers, started in the background; offers their tools and runs calls."""

    def __init__(self, config_path: Path = CONFIG_FILE, make=None) -> None:
        self.config_path = config_path
        self.make = make or self._make
        self.servers: dict[str, Connection] = {}
        self.names: dict[str, tuple[str, str]] = {}       # function name -> (server, tool)
        self.lock = threading.Lock()
        self.generation = 0

    @staticmethod
    def _make(name: str, cfg: dict) -> Connection:
        return HttpConnection(name, cfg) if cfg.get("url") and not cfg.get("command") else StdioConnection(name, cfg)

    def start(self, wait: bool = False) -> None:
        """(Re)reads the config and connects to every server in the background."""
        self.stop()
        config = load_config(self.config_path)
        with self.lock:
            self.generation += 1
            mine = self.generation
            self.servers = {name: self.make(name, cfg) for name, cfg in config.items()}
        threads = []
        for conn in list(self.servers.values()):
            t = threading.Thread(target=self._connect, args=(conn, mine), daemon=True)
            t.start()
            threads.append(t)
        if wait:
            for t in threads:
                t.join()

    def _connect(self, conn: Connection, generation: int) -> None:
        try:
            conn.connect()
        except McpError as e:
            conn.state, conn.error = "error", str(e)
            log.warning("MCP server %s: %s", conn.name, e)
            conn.close()
            return
        except Exception as e:  # noqa: BLE001 - one broken server must not take the others down
            conn.state, conn.error = "error", f"{e.__class__.__name__}: {e}"
            log.exception("MCP server %s failed", conn.name)
            conn.close()
            return
        with self.lock:
            if generation != self.generation:                # reloaded while this was starting
                conn.close()
                return
            taken = set(self.names)
            for tool in conn.tools:
                self.names[tool_function_name(conn.name, tool["name"], taken)] = (conn.name, tool["name"])
            conn.state = "ready"

    def stop(self) -> None:
        with self.lock:
            servers, self.servers, self.names = list(self.servers.values()), {}, {}
            self.generation += 1
        for conn in servers:
            conn.close()

    # -- what the AI sees --
    def openai_tools(self) -> list[dict]:
        out = []
        with self.lock:
            items = list(self.names.items())
            servers = dict(self.servers)
        for fname, (server, tool) in items:
            conn = servers.get(server)
            spec = next((t for t in (conn.tools if conn else []) if t["name"] == tool), None)
            if not spec:
                continue
            desc = f"[{server}] {spec.get('description') or tool}"[:900]
            out.append({"type": "function", "function": {"name": fname, "description": desc, "parameters": clean_schema(spec.get("inputSchema"))}})
        return out

    def owns(self, fname: str) -> bool:
        return fname in self.names

    def describe(self, fname: str, args: dict) -> tuple[str, str]:
        """(title, pretty arguments) for the approval card."""
        server, tool = self.names.get(fname, ("?", fname))
        return f"JARVIS wants to use {tool} from {server}", json.dumps(args, indent=2, ensure_ascii=False)[:2000]

    def needs_approval(self, fname: str) -> bool:
        server, tool = self.names.get(fname, ("", ""))
        auto = (self.servers.get(server).cfg.get("autoApprove") if server in self.servers else None) or []
        return not (auto is True or tool in auto)

    def call(self, fname: str, args: dict) -> str:
        """Runs a tool and returns its text (an "Error: ..." message if it fails; never raises)."""
        server, tool = self.names.get(fname, (None, None))
        conn = self.servers.get(server) if server else None
        if not conn:
            return "Error: that tool isn't available any more."
        try:
            if isinstance(conn, StdioConnection) and not conn.alive():
                raise McpError("the server program stopped. Use Reload in the status menu to start it again")
            result = conn.request("tools/call", {"name": tool, "arguments": args}, CALL_TIMEOUT)
        except McpError as e:
            return f"Error: {server}/{tool} failed: {e}."
        text = result_text(result)
        if len(text) > MAX_RESULT:
            text = text[:MAX_RESULT] + "\n[trimmed]"
        return ("Error: the tool reported a problem:\n" if result.get("isError") else "") + text

    # -- for the status menu --
    def status(self) -> dict:
        with self.lock:
            servers = list(self.servers.values())
        return {
            "configured": bool(servers),
            "servers": [{"name": c.name, "state": c.state, "tools": len(c.tools), "error": c.error,
                         "kind": "http" if isinstance(c, HttpConnection) else "program"} for c in servers],
        }


manager = Manager()
