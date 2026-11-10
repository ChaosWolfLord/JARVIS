"""Opening a web page in Chrome: what is refused, what is opened and how, when the AI must ask first, and the spoken shortcut.
Nothing real is opened or looked up."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import agent, audit, browser, toolgate  # noqa: E402


def public(host, port=None):
    return [(2, 1, 6, "", ("93.184.216.34", 0))]


def pointing_at(ip):
    return lambda host, port=None: [(2, 1, 6, "", (ip, 0))]


def unreachable(host, port=None):
    raise OSError("no such host")


class Clean(unittest.TestCase):
    def test_web_addresses_are_opened_as_they_are_or_tidied(self):
        for raw, want in (("https://example.com/a?b=1#c", "https://example.com/a?b=1#c"), ("example.com", "https://example.com"), ("http://example.com", "http://example.com"),
                          ("www.google.com/search?q=cats", "https://www.google.com/search?q=cats"), ("  https://example.com/x  ", "https://example.com/x"),
                          ("https://example.com:8443/p", "https://example.com:8443/p"), ("EXAMPLE.com", "https://example.com"),
                          ("https://www.google.com/search?q=what's the weather", "https://www.google.com/search?q=what's%20the%20weather")):
            self.assertEqual(browser.clean(raw, public), want, raw)

    def test_only_http_and_https(self):
        for raw in ("javascript:alert(1)", "file:///C:/Windows/win.ini", "data:text/html,<h1>x</h1>", "ftp://example.com/f", "chrome://settings", "ms-settings:privacy",
                    "mailto:a@example.com", "vbscript:x", "about:blank", "view-source:https://example.com", "ssh://example.com", "ms-windows-store://home", "steam://run/1"):
            with self.assertRaises(browser.BrowserError, msg=raw):
                browser.clean(raw, public)

    def test_nothing_on_this_pc_or_the_home_network(self):
        for raw in ("http://localhost:8000/api/status", "https://localhost", "http://127.0.0.1/", "http://127.1/", "http://[::1]/", "http://0.0.0.0/", "http://192.168.86.1/",
                    "http://10.0.0.5/admin", "http://172.16.4.4", "http://169.254.169.254/latest/meta-data", "http://metadata.google.internal/", "http://router/",
                    "https://printer.local", "http://nas.lan", "http://[fe80::1]/", "http://[::ffff:127.0.0.1]/"):
            with self.assertRaises(browser.BrowserError, msg=raw):
                browser.clean(raw, pointing_at("93.184.216.34"))            # refused by the address alone, whatever a lookup would say

    def test_a_name_that_points_at_this_pc_is_refused_too(self):
        for ip in ("127.0.0.1", "192.168.86.120", "10.1.2.3", "169.254.0.5", "::1", "fd00::1", "fe80::1"):
            with self.assertRaises(browser.BrowserError, msg=ip):
                browser.clean("https://innocent-looking.example.com", pointing_at(ip))
        with self.assertRaises(browser.BrowserError):
            browser.clean("http://2130706433/", pointing_at("127.0.0.1"))                      # the same address written as one number
        with self.assertRaises(browser.BrowserError):
            browser.clean("https://example.com", lambda h, p=None: [(2, 1, 6, "", ("93.184.216.34", 0)), (2, 1, 6, "", ("192.168.1.1", 0))])   # one private answer is enough

    def test_tricks_in_the_address(self):
        for raw in ("http://user:pass@example.com/", "https://evil.com@example.com/", "http://example.com\\@evil.com/", "https://exa\nmple.com", "https://example.com/<script>",
                    "https://", "http://", "", "   ", "https://example.com:99999/", "http://:80/"):
            with self.assertRaises(browser.BrowserError, msg=repr(raw)):
                browser.clean(raw, public)
        with self.assertRaises(browser.BrowserError):
            browser.clean("https://example.com/" + "a" * 2100, public)

    def test_a_site_that_does_not_exist_says_so(self):
        with self.assertRaisesRegex(browser.BrowserError, "can't find a website"):
            browser.clean("https://no-such-site-here.example", unreachable)

    def test_international_names_are_made_safe_to_look_up(self):
        self.assertEqual(browser.clean("https://bücher.example/", public), "https://xn--bcher-kva.example/")


class Opening(unittest.TestCase):
    def setUp(self):
        browser._recent.clear()
        self.launched = []
        self.addCleanup(browser._recent.clear)

    def launch(self, args, **kw):
        self.launched.append((list(args), kw))

    def test_chrome_gets_the_address_and_nothing_else(self):
        with mock.patch.object(browser, "find_chrome", return_value=r"C:\Chrome\chrome.exe"):
            said = browser.open_url("https://example.com/x", resolve=public, launch=self.launch)
        self.assertEqual(said, "Opened example.com in Chrome.")
        self.assertEqual(self.launched[0][0], [r"C:\Chrome\chrome.exe", "https://example.com/x"])         # no flags, no profile, no script

    def test_without_chrome_the_default_browser_is_used_and_it_says_so(self):
        with mock.patch.object(browser, "find_chrome", return_value=None):
            said = browser.open_url("example.com", resolve=public, launch=self.launch)
        self.assertIn("default browser", said)
        self.assertIn("https://example.com", self.launched[0][0])

    def test_a_refused_address_starts_nothing(self):
        with mock.patch.object(browser, "find_chrome", return_value="chrome.exe"):
            with self.assertRaises(browser.BrowserError):
                browser.open_url("http://192.168.86.1/", resolve=public, launch=self.launch)
        self.assertEqual(self.launched, [])

    def test_a_browser_that_will_not_start_is_a_message(self):
        def boom(args, **kw):
            raise OSError("no")
        with mock.patch.object(browser, "find_chrome", return_value="chrome.exe"):
            with self.assertRaisesRegex(browser.BrowserError, "couldn't start"):
                browser.open_url("example.com", resolve=public, launch=boom)

    def test_at_most_six_pages_a_minute(self):
        with mock.patch.object(browser, "find_chrome", return_value="chrome.exe"):
            for _ in range(6):
                browser.open_url("example.com", resolve=public, launch=self.launch)
            with self.assertRaisesRegex(browser.BrowserError, "a lot of pages"):
                browser.open_url("example.com", resolve=public, launch=self.launch)
        self.assertEqual(len(self.launched), 6)

    def test_it_can_be_turned_off(self):
        with mock.patch.dict("os.environ", {"JARVIS_BROWSER": "0"}):
            self.assertFalse(browser.available())
            with self.assertRaisesRegex(browser.BrowserError, "turned off"):
                browser.open_url("example.com", resolve=public, launch=self.launch)
            self.assertNotIn("open_url", {t["function"]["name"] for t in agent.active_tools()})
        self.assertIn("open_url", {t["function"]["name"] for t in agent.active_tools()})

    def test_the_tool_reports_problems_as_text_the_ai_can_read(self):
        self.assertTrue(browser.tool({"url": "javascript:alert(1)"}).startswith("Error"))
        self.assertTrue(browser.tool({}).startswith("Error"))

    def test_chrome_is_found_by_the_given_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "chrome.exe"
            exe.write_bytes(b"x")
            with mock.patch.dict("os.environ", {"JARVIS_CHROME": str(exe)}):
                self.assertEqual(browser.find_chrome(), str(exe))


class Spoken(unittest.TestCase):
    def test_a_command_that_names_a_website(self):
        for text, want in (("open youtube.com", "youtube.com"), ("Jarvis, open github.com", "github.com"), ("go to news.ycombinator.com", "news.ycombinator.com"),
                           ("open example dot com", "example.com"), ("open the website wikipedia.org in chrome", "wikipedia.org"), ("visit https://example.com/path", "https://example.com/path"),
                           ("please open www.google.com on chrome", "www.google.com"), ("Open Reddit.com!", "Reddit.com"), ("take me to bbc.co.uk", "bbc.co.uk"),
                           ("pull up example.com/a/b?c=1", "example.com/a/b?c=1")):
            self.assertEqual(browser.spoken_address(text), want, text)

    def test_other_commands_are_left_alone(self):
        for text in ("open discord", "open notes.txt", "go to sleep", "open the pod bay doors", "open 192.168.1.1", "open weather", "start a timer", "what is example.com",
                     "open youtube and play something", "open readme.md", "go to the store", "open"):
            self.assertIsNone(browser.spoken_address(text), text)

    def test_the_shortcut_opens_it_without_the_ai(self):
        with mock.patch.object(browser, "open_url", return_value="Opened youtube.com in Chrome.") as opened:
            self.assertEqual(browser.handle_voice("open youtube.com"), {"handled": True, "ok": True, "text": "Opened youtube.com in Chrome."})
        opened.assert_called_once_with("youtube.com")
        self.assertEqual(browser.handle_voice("open discord"), {"handled": False, "text": ""})

    def test_a_refused_site_is_spoken_back_as_a_reason(self):
        out = browser.handle_voice("open example.com") if False else None
        with mock.patch.object(browser, "open_url", side_effect=browser.BrowserError("that is an address on this PC or your home network; I only open public websites.")):
            out = browser.handle_voice("open example.com")
        self.assertTrue(out["handled"] and not out["ok"])
        self.assertIn("public websites", out["text"])


class NamedByTheUser(unittest.TestCase):
    def test_the_main_part_of_the_address_must_be_something_they_wrote(self):
        for url, texts, want in (("https://www.youtube.com", ["open youtube"], True), ("https://en.wikipedia.org/wiki/Cat", ["open the wikipedia page for cats"], True),
                                 ("https://bbc.co.uk/news", ["go to the BBC"], True), ("https://x.com", ["open x.com"], True), ("https://www.google.com/search?q=cats", ["search google for cats"], True),
                                 ("https://news.badsite.com", ["open the news"], False), ("https://x.com", ["open the thing"], False), ("https://www.google.com/maps?q=pizza", ["find pizza near me"], False),
                                 ("https://evil.example", ["open youtube"], False), ("", ["open youtube"], False), ("https://github.com.evil.example", ["open github"], False)):
            self.assertEqual(agent.named_by_user(url, texts), want, f"{url} / {texts}")


class AskingFirst(unittest.TestCase):
    """The AI's open_url: a site you named opens at once; anything else shows the exact address and waits for Allow."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for patch in (mock.patch.object(audit, "LOG_FILE", Path(tmp.name) / "a.log"), mock.patch.object(agent.store, "MEMORY_FILE", Path(tmp.name) / "m.json")):
            patch.start()
            self.addCleanup(patch.stop)
        self.ran = []

    def scripted(self, rounds):
        answers = iter(rounds)

        def fake(msgs, cancel=None):
            text, calls = next(answers)
            r = agent._Round()
            r.text = text
            r.calls = {i: {"id": f"c{i}", "name": n, "args": __import__("json").dumps(a), "extra": {}} for i, (n, a) in enumerate(calls)}
            if text:
                yield {"type": "text", "delta": text}
            yield {"type": "_round", "target": agent.Target("openrouter", "t:free"), "round": r}
        return fake

    def turn(self, message, rounds, history=None, private=False, allow=True):
        target = agent.Target("openrouter", "t:free")

        def lookup(name, args):
            self.ran.append((name, args.get("url", "")))
            return "Opened it." if name == "open_url" else "RESULT"

        with mock.patch.object(agent, "_run_round", self.scripted(rounds)), mock.patch.object(agent, "CHAIN", [target]), mock.patch.object(agent, "usable", return_value=[target]), \
                mock.patch.object(agent, "_refresh_chain"), mock.patch.object(agent, "_openrouter_notice", return_value=None), mock.patch.object(agent, "_run_lookup", side_effect=lookup), \
                mock.patch.object(agent.runner, "wait", return_value=allow):
            return list(agent.chat_turn(message, history or [], None, private=private))

    def cards(self, events):
        return [e for e in events if e["type"] == "run_request"]

    def test_a_site_the_user_named_opens_without_a_click(self):
        events = self.turn("open youtube", [("", [("open_url", {"url": "https://www.youtube.com"})]), ("Done.", [])])
        self.assertEqual(self.ran, [("open_url", "https://www.youtube.com")])
        self.assertEqual(self.cards(events), [])

    def test_a_site_the_user_never_named_shows_the_address_and_waits(self):
        events = self.turn("find me a pizza place", [("", [("open_url", {"url": "https://www.google.com/maps?q=pizza"})]), ("Done.", [])])
        [card] = self.cards(events)
        self.assertIn("https://www.google.com/maps?q=pizza", card["code"])
        self.assertIn("did not name", card["title"])
        self.assertEqual(self.ran, [("open_url", "https://www.google.com/maps?q=pizza")])           # allowed this time

    def test_saying_no_means_it_is_never_opened(self):
        events = self.turn("find me a pizza place", [("", [("open_url", {"url": "https://www.google.com/maps?q=pizza"})]), ("Not opening it.", [])], allow=False)
        self.assertEqual(self.ran, [])
        self.assertTrue(any(e.get("declined") for e in events if e["type"] == "run_result"))

    def test_after_reading_a_web_page_even_a_named_site_asks(self):
        # the page could be telling the AI where to go
        events = self.turn("open the wikipedia page about cats", [("", [("web_search", {"query": "cats"})]), ("", [("open_url", {"url": "https://en.wikipedia.org/wiki/Cat"})]), ("Done.", [])])
        [card] = self.cards(events)
        self.assertIn("web page", card["title"])
        self.assertEqual([n for n, _ in self.ran], ["web_search", "open_url"])

    def test_after_reading_private_data_it_asks_and_says_why(self):
        events = self.turn("open youtube", [("", [("gmail_search", {"query": "x"})]), ("", [("open_url", {"url": "https://www.youtube.com/?q=secret"})]), ("Done.", [])])
        [card] = self.cards(events)
        self.assertIn("private data", card["title"])
        self.assertIn("https://www.youtube.com/?q=secret", card["code"])

    def test_an_earlier_private_turn_counts(self):
        events = self.turn("open youtube", [("", [("open_url", {"url": "https://www.youtube.com"})]), ("ok", [])], private=True, allow=False)
        self.assertEqual(self.ran, [])
        self.assertTrue(self.cards(events))

    def test_a_site_named_earlier_in_the_conversation_counts_but_only_if_the_user_wrote_it(self):
        mine = [{"role": "user", "content": "I keep reading github all day"}, {"role": "assistant", "content": "Sure."}]
        events = self.turn("open it", [("", [("open_url", {"url": "https://github.com"})]), ("ok", [])], history=mine)
        self.assertEqual(self.cards(events), [])
        theirs = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "You could try github."}]
        events = self.turn("open it", [("", [("open_url", {"url": "https://github.com"})]), ("ok", [])], history=theirs)
        self.assertEqual(len(self.cards(events)), 1)

    def test_every_opening_is_written_to_the_activity_log(self):
        self.turn("open youtube", [("", [("open_url", {"url": "https://www.youtube.com"})]), ("Done.", [])])
        [entry] = audit.recent()
        self.assertEqual((entry["kind"], entry["what"]), ("open_url", "https://www.youtube.com"))


class Offered(unittest.TestCase):
    def test_the_tool_is_sent_only_when_a_message_could_need_it(self):
        def names(message):
            return {t["function"]["name"] for t in toolgate.filter_tools(agent.active_tools(), toolgate.groups_for(message, []))}
        for message in ("open youtube.com", "go to the wikipedia page for cats", "can you open github", "search google for pizza"):
            self.assertIn("open_url", names(message), message)
        self.assertNotIn("open_url", names("what is two plus two?"))

    def test_the_ai_is_told_the_rules(self):
        text = agent.PERSONA
        self.assertIn("- open_url opens a web page", text)
        self.assertIn("Allow", text)

    def test_the_step_and_the_log_say_what_is_happening(self):
        self.assertEqual(agent._step_text("open_url", {"url": "https://example.com"}), "Opening a web page: https://example.com")
        self.assertEqual(audit.describe("open_url", {"url": "https://example.com"}), "https://example.com")


if __name__ == "__main__":
    unittest.main()
