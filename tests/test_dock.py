"""The bottom bar (web/index.html, web/dock.css, web/dockmenus.js, web/orb.js): every button says what it is, nothing the app looks up by id has gone
missing, and the buttons that are rarely used live in the More menu instead of crowding the bar."""
import re
import sys
import unittest
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX = (WEB / "index.html").read_text("utf-8")
APP = (WEB / "app.js").read_text("utf-8")


class Page(HTMLParser):
    """Collects every element's attributes, and the text and children of the dock's buttons."""

    def __init__(self):
        super().__init__()
        self.ids, self.stack, self.buttons = [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.append(a["id"])
        self.stack.append((tag, a))
        if tag == "button":
            self.buttons.append({"attrs": a, "text": "", "tags": [], "path": [t for t, _ in self.stack[:-1]], "in": [x.get("id") for _, x in self.stack if x.get("id")]})

    def handle_endtag(self, tag):
        while self.stack and self.stack[-1][0] != tag:
            self.stack.pop()
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        for t, _ in reversed(self.stack):
            if t == "button" and self.buttons:
                self.buttons[-1]["text"] += data
                break


page = Page()
page.feed(INDEX)
bar_buttons = [b for b in page.buttons if "toolbar" in b["in"]]
labelled = [b for b in bar_buttons if "dock-btn" in b["attrs"].get("class", "").split()]


class Structure(unittest.TestCase):
    def test_no_id_is_used_twice(self):
        dupes = [i for i, n in Counter(page.ids).items() if n > 1]
        self.assertEqual(dupes, [])

    def test_everything_the_app_looks_up_by_id_is_still_there(self):
        for ident in ("btn-mic", "btn-memory", "btn-kb", "btn-touch", "btn-pen", "btn-fit", "btn-lights", "btn-full", "btn-status", "btn-widgets", "btn-panel",
                      "btn-note", "btn-undo", "btn-redo", "btn-clear", "swatches", "size", "orb", "orb-canvas", "orb-bubble", "status-menu", "widget-menu",
                      "btn-ink", "ink-menu", "btn-more", "more-menu", "orb-label"):
            self.assertIn(ident, page.ids, ident)
        tools = [b["attrs"].get("data-tool") for b in page.buttons if b["attrs"].get("data-tool")]
        self.assertEqual(sorted(tools), ["eraser", "pen"])

    def test_every_id_the_app_script_asks_for_exists(self):
        asked = set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", APP))
        missing = sorted(i for i in asked if i not in page.ids)
        self.assertEqual(missing, [], "app.js asks for elements that are not in index.html")


class Clarity(unittest.TestCase):
    def test_each_visible_button_says_what_it_is_under_its_icon(self):
        self.assertTrue(labelled)
        for b in labelled:
            label = " ".join(b["text"].split())
            self.assertTrue(label, f"{b['attrs'].get('id') or b['attrs'].get('data-tool')} has no label")
            self.assertTrue(b["attrs"].get("title"), f"{label} has no tooltip")

    def test_the_bar_is_not_crowded(self):
        self.assertLessEqual(len(labelled), 11, "the bar shows too many buttons: move rarely used ones into More")
        right = re.search(r'<div class="dock-side dock-right">(.*?)</div></div>', INDEX, re.S).group(1)
        self.assertLessEqual(len(re.findall(r"<button", right)), 4)

    def test_rarely_used_buttons_are_in_more_each_with_a_line_saying_what_they_do(self):
        more = re.search(r'<div id="more-menu".*?</div>\s*<button id="btn-mic"', INDEX, re.S).group(0)
        rows = re.findall(r'<button type="button" class="menu-row[^"]*" id="([^"]+)".*?<b>(.*?)</b><small>(.*?)</small>', more, re.S)
        self.assertEqual([r[0] for r in rows], ["btn-memory", "btn-kb", "btn-touch", "btn-pen", "btn-fit", "btn-lights", "btn-full"])
        for ident, name, line in rows:
            self.assertTrue(name.strip() and len(line.strip()) > 12, ident)

    def test_the_orb_is_the_voice_button_and_says_what_a_tap_does(self):
        self.assertIn("voice.toggle()", APP)
        self.assertIn('id="orb-label"', INDEX)
        for words in ("tap to talk", "Listening", "Thinking", "Speaking"):
            self.assertIn(words, APP)
        self.assertIn("voice.interrupt()", APP)                               # while it talks, a tap stops it


class Pieces(unittest.TestCase):
    def test_the_dock_stylesheet_and_menus_are_wired_in(self):
        self.assertIn('href="dock.css"', INDEX)
        self.assertIn("import { dockMenus } from './dockmenus.js'", APP)
        self.assertIn("btn-more", APP)
        menus = (WEB / "dockmenus.js").read_text("utf-8")
        for needle in ("Escape", "aria-expanded", "fitMenu"):
            self.assertIn(needle, menus)

    def test_the_orb_is_a_sphere_of_dots_that_follows_the_microphone(self):
        orb = (WEB / "orb.js").read_text("utf-8")
        for needle in ("DOTS", "getByteFrequencyData", "BANDS", "'thinking'", "'speaking'", "getUserMedia"):
            self.assertIn(needle, orb)
        self.assertNotIn("fillText", orb)                                          # the ring-and-name drawing is gone
        css = (WEB / "dock.css").read_text("utf-8")
        self.assertIn("#toolbar #orb::after", css)                                 # only the sphere is the button; the pen reaches the board around it

    def test_the_pen_colour_is_shown_on_the_colour_button(self):
        self.assertIn("showInkColour", APP)
        self.assertIn("var(--ink", (WEB / "dock.css").read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
