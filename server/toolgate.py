"""Sends the AI only the tools (and the instructions for them) that a message could need.

Every request used to carry all 36 tools and their instructions: about 7,000 tokens before the question. That is slow, it burns the free
allowance of every model, and it is more than the free tier of the fast back-up models allows in a whole minute, so they could never
answer and JARVIS fell through to the slowest model. Most messages need a handful of tools, and the words say which: nobody needs the
Gmail tools to be told the capital of France.

The rule is deliberately generous (a group is included if any of its words appears in this message or the last few lines of the
conversation, so "make it blue" after "turn the lights on" still works) and the always-needed tools are never dropped: the board,
memory, lookups on the web and in files, and any app connected through MCP. Set JARVIS_TOOLS=all to turn this off.
"""
from __future__ import annotations

import os
import re

# group -> (the tools in it, words that bring it in, the instruction lines in the persona that belong to it)
GROUPS: dict[str, tuple[frozenset, re.Pattern, tuple[str, ...]]] = {
    "lights": (frozenset({"lights"}),
               re.compile(r"\b(lights?|lamps?|bulbs?|brightness|bright|dim|dimmer|colou?rs?|scenes?|govee|glow|dark|candle|mood|ambiance|ambience|"
                          r"red|blue|green|purple|pink|orange|yellow|white|warm|cool|cozy|cosy|turn (?:it )?(?:on|off))\b"), ("lights",)),
    "music": (frozenset({"music"}),
              re.compile(r"\b(music|songs?|play|playing|pause|resume|skip|next|previous|volume|louder|quieter|speakers?|playlist|album|artist|tunes?|listen|"
                         r"sing|nest|google home|mute|turn it (?:up|down)|louder|quiet)\b"), ("music",)),
    "apps": (frozenset({"apps", "app_close"}),
             re.compile(r"\b(open|launch|start|close|quit|exit|kill|apps?|programs?|windows?|running|discord|spotify|chrome|edge|steam|notepad|code|claude|vscode)\b"),
             ("apps",)),
    "system": (frozenset({"system_status", "system_details", "system_fix"}),
               re.compile(r"\b(computer|pc|laptop|system|slow|lag|laggy|cpu|ram|memory|disk|drives?|storage|battery|temperature|internet|wi-?fi|network|security|"
                          r"virus|defender|errors?|crash|crashed|freezes?|frozen|fix|restart|process(?:es)?|health|status|update|alerts?|problems?)\b"),
               ("system_status", "system_fix")),
    "google": (frozenset({"calendar_events", "calendar_add_event", "gmail_search", "gmail_read", "gmail_draft_reply", "discord_channels", "discord_read", "discord_send"}),
               re.compile(r"\b(mail|e-?mails?|gmail|inbox|unread|calendar|schedule|meetings?|events?|appointments?|agenda|today|tomorrow|reply|draft|"
                          r"discord|channels?|messages?|servers?|dm)\b"), ("calendar_events",)),
    "browser": (frozenset({"open_url"}),
                re.compile(r"\b(open|go to|visit|browse|navigate|pull up|take me|site|sites|website|webpage|web page|page|url|link|http|https|www|chrome|browser|google|"
                           r"youtube|wikipedia|github|reddit|amazon|search|look up|\.com|\.org|\.net|\.io)\b|\.(?:com|org|net|io|dev|edu|gov)\b"), ("open_url",)),
    "display": (frozenset({"hologram", "chart", "headlines"}),
                re.compile(r"\b(3-?d|holograms?|holo|models?|wireframes?|shapes?|rotat\w*|charts?|graphs?|plots?|pie|bars?|radar|visuali[sz]\w*|cube|sphere|torus|"
                           r"helix|globe|reactor|show|display|news|headlines?|ticker|happening)\b"), ("hologram",)),
    "cards": (frozenset({"timer", "widget"}),
              re.compile(r"\b(timers?|countdown|minutes?|mins?|seconds?|alarm|stopwatch|weather|forecast|usage|tokens?|widgets?|cards?|ticker|clock|show|hide|"
                         r"remove|cancel|close)\b"), ("timer", "widget")),
    "pictures": (frozenset({"picture"}),
                 re.compile(r"\b(pictures?|photos?|images?|pics?|photograph\w*|wall)\b"), ("picture",)),
    "files": (frozenset({"find_files"}),
              re.compile(r"\b(files?|documents?|docs?|pdfs?|spreadsheets?|presentations?|slides|folders?|downloads?|find|where|locate|search|screenshots?|excel|powerpoint|invoices?|receipts?)\b"),
              ("find_files",)),
    "reminders": (frozenset({"reminder"}),
                  re.compile(r"\b(remind\w*|alarm|wake me|forget|tonight|tomorrow|later|every|daily|weekly|at \d|in \d+ ?(?:min|hour|day)\w*)\b"), ()),
    "code": (frozenset({"run_python"}),
             re.compile(r"\b(python|code|script|calculate|calculation|compute|math|sum|average|mean|median|plot|csv|data|run|algorithm|sort|prime|factor|"
                        r"equation|convert|how many|percent|percentage|\d\s*[-+*/^x]\s*\d)\b|%"), ("run_python",)),
}
ALWAYS_OFF_WHEN_CONNECTED = frozenset()      # nothing: tools that aren't connected are already left out by agent.active_tools()


def enabled() -> bool:
    return os.getenv("JARVIS_TOOLS", "").strip().lower() != "all"


def _recent_text(message: str, history: list[dict] | None) -> str:
    lines = [str(message or "")]
    for turn in (history or [])[-4:]:
        lines.append(str(turn.get("content") or "")[:400])
    return "\n".join(lines).lower()


def groups_for(message: str, history: list[dict] | None = None) -> set[str]:
    """The groups this message (and the last few lines before it) could need."""
    text = _recent_text(message, history)
    return {name for name, (_, words, _) in GROUPS.items() if words.search(text)}


def filter_tools(tools: list[dict], groups: set[str]) -> list[dict]:
    """The tools to send: everything except the tools of groups that were not asked for."""
    dropped = set()
    for name, (members, _, _) in GROUPS.items():
        if name not in groups:
            dropped |= members
    return [t for t in tools if t["function"]["name"] not in dropped]


def filter_persona(persona: str, groups: set[str]) -> str:
    """The instruction text without the bullet lines for tools that are not being sent (each tool is one line starting '- name')."""
    starts: set[str] = set()
    for name, (_, _, lines) in GROUPS.items():
        if name not in groups:
            starts |= set(lines)
    if not starts:
        return persona
    kept = []
    for line in persona.split("\n"):
        m = re.match(r"- (\w+)", line)
        if m and m.group(1) in starts:
            continue
        kept.append(line)
    return "\n".join(kept)
