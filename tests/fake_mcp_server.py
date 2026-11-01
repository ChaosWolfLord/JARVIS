"""A tiny MCP server for the tests: speaks JSON-RPC lines on stdin/stdout. Tools: echo, add, boom (reports an error),
slow (never answers), and it exits when asked to by "die". Not part of JARVIS."""
import json
import sys
import time

TOOLS = [
    {"name": "echo", "description": "Repeat the text back.", "inputSchema": {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object",
     "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}},
    {"name": "add", "description": "Add two numbers.", "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}}},
    {"name": "boom", "description": "Always reports an error.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "slow", "description": "Never answers.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "weird name!", "description": "A tool whose name needs cleaning.", "inputSchema": {}},
    {"name": "die", "description": "Exits the server.", "inputSchema": {"type": "object", "properties": {}}},
]


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    method, rid = msg.get("method"), msg.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "0"}}})
        send({"jsonrpc": "2.0", "id": 900, "method": "ping"})                      # servers may ask the client things
    elif method == "tools/list":
        cursor = (msg.get("params") or {}).get("cursor")
        if not cursor:
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS[:3], "nextCursor": "page2"}})
        else:
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS[3:]}})
    elif method == "tools/call":
        params = msg["params"]
        name, args = params["name"], params.get("arguments") or {}
        if name == "echo":
            send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": f"echo: {args.get('text')}"}]}})
        elif name == "add":
            send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": str(args.get("a", 0) + args.get("b", 0))}]}})
        elif name == "boom":
            send({"jsonrpc": "2.0", "id": rid, "result": {"isError": True, "content": [{"type": "text", "text": "it went wrong"}]}})
        elif name == "slow":
            time.sleep(60)
        elif name == "die":
            sys.exit(0)
        else:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"unknown tool {name}"}})
    elif rid is not None:
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}})
