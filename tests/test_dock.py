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

    def test_the_bar_is_not_crowded_and_each_side_has_its_own_job(self):
        self.assertLessEqual(len(labelled), 11, "the bar shows too many buttons: move rarely used ones into More")
        left = INDEX[INDEX.index('<div class="dock-side dock-left">'):INDEX.index('<button id="orb"')]
        start = INDEX.index('<div class="dock-side dock-right">')
        right = INDEX[start:INDEX.index("</nav>", start)]
        ids = lambda html: re.findall(r'<button[^>]*?(?:id="([\w-]+)"|data-tool="(\w+)")', html)
        names = lambda html: [a or b for a, b in ids(html)]
        self.assertEqual(names(left), ["btn-status", "btn-panel", "btn-note", "btn-widgets", "btn-more"])      # status, chat, note, cards, more
        self.assertEqual(names(right), ["pen", "eraser", "btn-ink", "btn-undo", "btn-redo", "btn-clear"])      # only drawing on the right

    def test_rarely_used_buttons_are_in_more_each_with_a_line_saying_what_they_do(self):
        more = re.search(r'<div id="more-menu".*?</div>\s*<button id="btn-mic"', INDEX, re.S).group(0)
        rows = re.findall(r'<button type="button" class="menu-row[^"]*" id="([^"]+)".*?<b>(.*?)</b><small>(.*?)</small>', more, re.S)
        self.assertEqual([r[0] for r in rows], ["btn-boards", "btn-memory", "btn-kb", "btn-touch", "btn-pen", "btn-fit", "btn-lights", "btn-full"])
        for ident, name, line in rows:
            self.assertTrue(name.strip() and len(line.strip()) > 12, ident)

    def test_the_orb_is_the_voice_button_and_says_what_a_tap_does(self):
        self.assertIn("voice.toggle()", APP)
        self.assertIn('id="orb-label"', INDEX)
        for words in ("tap to talk", "Listening", "Thinking", "Speaking"):
            self.assertIn(words, APP)
        self.assertIn("voice.interrupt()", APP)                               # while it talks, a tap stops it


class OrbAndButtons(unittest.TestCase):
    CSS = (WEB / "dock.css").read_text("utf-8")

    def test_the_orb_is_a_cell_of_the_bar_that_cannot_paint_over_its_neighbours(self):
        self.assertIn("grid-column: 2", self.CSS)                                     # the middle column, not a floating element
        self.assertIn("overflow-x: clip", self.CSS)                                   # anything wider than the column is cut off
        self.assertRegex(self.CSS, r"\.dock-side[^{]*\{[^}]*z-index: 3")             # the buttons are drawn above it
        self.assertIn("minmax(max-content, 1fr)", self.CSS)                           # the sides always get the room their buttons need
        for size in ("compact", "tight", "micro"):
            self.assertIn(f'data-size="{size}"', self.CSS)
        self.assertIn("micro", (WEB / "dockmenus.js").read_text("utf-8"))

    def test_the_dots_stay_inside_the_orb_column(self):
        orb = (WEB / "orb.js").read_text("utf-8")
        self.assertIn("S * 0.25 * swell", orb)                                        # about 0.41 of the canvas from the middle at the loudest
        for col, size in ((230, 264), (150, 180), (124, 150), (100, 118)):
            self.assertLessEqual(0.42 * size, col / 2 + 1, f"column {col} px is narrower than the loudest orb of {size} px")
        for col, size in ((300, 330), (210, 250), (160, 190)):
            self.assertLessEqual(0.42 * size, col / 2 + 1, f"touch: column {col} px is narrower than the loudest orb of {size} px")


class StatusPanel(unittest.TestCase):
    STATUS = (WEB / "status.js").read_text("utf-8")
    CSS = (WEB / "statuspanel.css").read_text("utf-8")

    def test_it_is_a_panel_flush_with_the_left_edge_like_the_chat_and_its_button_is_on_the_left_of_the_bar(self):
        app = INDEX.index('<div id="app">')
        panel, main, chat = INDEX.index('<aside id="status-menu"'), INDEX.index('<main id="stage">'), INDEX.index('<aside id="panel">')
        self.assertTrue(app < panel < main < chat)                                    # a sibling of the board and the chat, on the left of the board
        self.assertIn("position: static", self.CSS)                                   # in the layout, not floating over the board
        self.assertIn("border-right", self.CSS)
        self.assertIn("border-radius: 0", self.CSS)
        left = INDEX[INDEX.index('<div class="dock-side dock-left">'):INDEX.index('<button id="orb"')]
        self.assertIn('id="btn-status"', left)
        self.assertNotIn('id="btn-status"', INDEX[INDEX.index('<div class="dock-side dock-right">'):])

    def test_it_closes_in_the_modern_look_too(self):
        # the modern rule that sets display is more specific than a plain [hidden] rule, so it needs its own: without it the panel never closed
        self.assertIn("html.modern #status-menu.status-drawer[hidden]", self.CSS)
        for needle in ("#status-close", "toggle(false)"):
            self.assertIn(needle, self.STATUS)

    def test_it_can_stay_open_next_to_the_chat(self):
        self.assertNotIn("document.addEventListener('click'", self.STATUS)             # clicking elsewhere (the chat, the board) does not close it
        self.assertIn("setPanel", APP)
        self.assertIn("key === 's'", APP)                                            # S opens and closes it

    def test_it_answers_is_everything_ok_before_anything_else(self):
        for needle in ("Everything is working", "thing to look at", "JARVIS isn’t running", "Needs attention", "Working", "Not in use"):
            self.assertIn(needle, self.STATUS)
        for ident in ("sd-summary", "sd-headline", "sd-sub", "status-close", "status-rows"):
            self.assertIn(ident, page.ids)

    def test_a_problem_says_what_to_do_about_it(self):
        for hint in ("Add ${i.key_env", "Start it with JARVIS.bat", "Open JARVIS in Chrome or Edge", "Start run_tracker.bat"):
            self.assertIn(hint, self.STATUS)

    def test_the_quick_actions_and_sections_are_named_with_a_line_saying_what_is_inside(self):
        drawer = INDEX[INDEX.index('<aside id="status-menu"'):INDEX.index('</aside>', INDEX.index('<aside id="status-menu"'))]
        actions = re.findall(r'data-do="(\w+)"', drawer)
        self.assertEqual(actions, ["lock", "pair", "picture"])
        sections = re.findall(r'<details class="sd-sec" id="(sec-\w+)">.*?<b>(.*?)</b><small>(.*?)</small>', INDEX, re.S)
        self.assertEqual([s[0] for s in sections], ["sec-phone", "sec-routines", "sec-nudges", "sec-vision", "sec-files", "sec-privacy", "sec-voice", "sec-display", "sec-board", "sec-tools"])
        for _, name, line in sections:
            self.assertTrue(name and len(line) > 10)

    def test_everything_that_lived_in_the_old_menu_is_still_there(self):
        for ident in ("privacy-lock", "privacy-setcode", "privacy-form", "phone-show", "phone-forget", "phone-info", "voice-pick", "voice-rate", "voice-pitch", "voice-test",
                      "opt-look", "ambient-minutes", "opt-sounds", "opt-boot", "boot-replay", "export-png", "export-json", "show-backups", "show-activity", "status-backups",
                      "mcp-rows", "mcp-reload"):
            self.assertIn(ident, page.ids, ident)


class Pieces(unittest.TestCase):
    def test_the_dock_stylesheet_and_menus_are_wired_in(self):
        self.assertIn('href="dock.css"', INDEX)
        self.assertIn("from './dockmenus.js'", APP)
        self.assertIn("watchDockSize", APP)
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
