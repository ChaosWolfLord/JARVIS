"""The phone screen: JARVIS's orb at the top, the conversation under it, what you type at the bottom, and the orb moving with your voice."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PHONE = ROOT / "web" / "phone"
HTML = (PHONE / "phone.html").read_text("utf-8")
CSS = (PHONE / "phone.css").read_text("utf-8")
JS = (PHONE / "phone.js").read_text("utf-8")
ORB = (PHONE / "orb.js").read_text("utf-8")
ACTIVITY = (ROOT / "android" / "app" / "src" / "main" / "java" / "dev" / "jarvis" / "phone" / "MainActivity.java").read_text("utf-8")


class Layout(unittest.TestCase):
    def test_the_orb_is_on_top_the_chat_under_it_and_the_composer_last(self):
        chat = HTML[HTML.index('<div id="chat"'):]
        order = [chat.index(marker) for marker in ('id="bar"', 'id="stage"', 'id="orb"', 'id="log"', 'id="composer"')]
        self.assertEqual(order, sorted(order))

    def test_tapping_the_orb_talks_or_stops(self):
        self.assertIn("$('orb').addEventListener('click'", JS)
        for needle in ("stopListening()", "controller?.abort()", "$('mic').click()"):
            self.assertIn(needle, JS)
        for label in ("Tap to talk", "Listening… tap to stop", "Thinking… tap to stop", "Speaking… tap to stop"):
            self.assertIn(label, JS)

    def test_the_orb_follows_what_is_happening(self):
        self.assertRegex(JS, r"function orbState\(\)")
        for state in ("listening", "thinking", "speaking", "offline", "idle"):
            self.assertIn(f"'{state}'", JS)
        for hook in ("function setBusy", "function micState", "function setState"):
            body = JS[JS.index(hook):JS.index(hook) + 400]
            self.assertIn("refreshOrb()", body, hook)

    def test_the_orb_is_a_sphere_of_dots_that_moves_with_the_voice(self):
        self.assertIn("window.PhoneOrb", ORB)
        for needle in ("DOTS", "BANDS", "hear(level)", "'listening'", "'thinking'", "'speaking'", "prefers-reduced-motion"):
            self.assertIn(needle, ORB)
        self.assertIn("type === 'rms'", JS)                                 # the level from the phone's recognizer reaches the orb
        self.assertIn("orb?.hear(", JS)

    def test_it_stays_a_circle_and_makes_room_when_the_keyboard_is_up(self):
        self.assertIn("--stage-h", CSS)
        self.assertRegex(CSS, r"#orb \{[^}]*width: calc\(var\(--stage-h\)[^}]*height: calc\(var\(--stage-h\)")
        self.assertIn("body.typing #chat", CSS)
        self.assertIn("classList.add('typing')", JS)

    def test_the_scripts_are_loaded_in_order_and_served(self):
        self.assertLess(HTML.index('src="orb.js"'), HTML.index('src="phone.js"'))
        self.assertIn("canvas", HTML[HTML.index('id="pair"'):HTML.index('id="chat"')])        # the pairing screen shows the same orb
        sys.path.insert(0, str(ROOT))
        from server import phone
        import tempfile
        app = phone.build_app(phone.Phones(Path(tempfile.mkdtemp()) / "p.json"), lambda *a, **k: iter(()), lambda e: None)
        self.assertIn("/orb.js", {r.path for r in app.routes})

    def test_the_android_app_reports_how_loud_you_are(self):
        body = ACTIVITY[ACTIVITY.index("public void onRmsChanged"):]
        body = body[:body.index("}\n") + 1]
        self.assertIn('emit("rms"', body)
        self.assertIn("lastRms", body)                                          # not on every sample: at most about 20 times a second
        self.assertTrue((ROOT / "android" / "release-notes" / "1.2.5.md").exists())
        self.assertRegex((ROOT / "android" / "app" / "build.gradle.kts").read_text("utf-8"), r'versionName = "1\.2\.5"')


if __name__ == "__main__":
    unittest.main()
