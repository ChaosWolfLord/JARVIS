"""The speech bubble: a small pill that pops out of the top of the screen, starts as "Thinking... Stop", and shows whatever JARVIS says in full."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "web" / "index.html").read_text("utf-8")
CSS = (ROOT / "web" / "style.css").read_text("utf-8")
APP = (ROOT / "web" / "app.js").read_text("utf-8")


class TopBubble(unittest.TestCase):
    def test_it_lives_over_the_board_not_in_the_bottom_bar(self):
        toolbar = HTML[HTML.index('<nav id="toolbar"'):HTML.index("</nav>", HTML.index('<nav id="toolbar"'))]
        self.assertNotIn("orb-bubble", toolbar)
        self.assertEqual(HTML.count('id="orb-bubble"'), 1)
        self.assertIn('role="status"', re.search(r'<div id="orb-bubble"[^>]*>', HTML).group(0))

    def test_it_sits_at_the_top_and_pops_out(self):
        block = CSS[CSS.index("#orb-bubble {"):CSS.index("#orb-bubble.open")]
        self.assertIn("top: 12px", block)
        self.assertNotIn("bottom: 100%", block)
        self.assertIn("translate(-50%, -130%)", block)                  # it starts above the edge
        self.assertIn("cubic-bezier(0.2, 1.3", block)                   # and springs out
        self.assertIn("#orb-bubble.open { opacity: 1; transform: translate(-50%, 0)", CSS)
        self.assertIn("prefers-reduced-motion", CSS)

    def test_the_stop_button_is_inside_the_pill_and_text_scrolls_inside_it(self):
        self.assertIn(".bubble-body", CSS)
        self.assertIn("overflow-y: auto", CSS[CSS.index("#orb-bubble .bubble-body"):][:200])
        self.assertIn("class=\"bubble-stop\"", APP)
        self.assertIn("showBubble(`<p class=\"step\">“${plain(text.slice(0, 160))}”</p><p class=\"step\">Thinking…</p>`, 0, true)", APP)

    def test_an_answer_is_shown_whole(self):
        final = APP[APP.index("chat.onFinal = ({ text, failed, error })"):][:700]
        self.assertNotIn("slice(0, 700)", final)
        self.assertNotIn("…`", final)
        self.assertIn("plain(shown)", final)

    def test_it_goes_away_when_the_chat_opens_or_the_screen_locks(self):
        self.assertIn("hideBubble(true)", APP[APP.index("onLocked:"):][:200])
        self.assertIn("b.classList.remove('open'); b.hidden = true", APP[APP.index("function setPanel"):][:400])

    def test_what_it_says_is_always_escaped(self):
        for line in APP.splitlines():
            if "showBubble(`" in line and "${" in line:
                for part in re.findall(r"\$\{([^}]*)\}", line):
                    self.assertTrue(part.startswith(("plain(", "body")) or part in ("stop ? stopButton : ''",), f"unescaped: {part} in {line.strip()[:80]}")


if __name__ == "__main__":
    unittest.main()
