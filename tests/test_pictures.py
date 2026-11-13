"""Pictures on the wall and "Share to JARVIS": what counts as a picture, where it may come from, what the phone may send, and that the wall only
ever shows what this PC checked and kept. No test touches the internet: downloads and searches use a pretend server."""
import json
import re
import socket
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import httpx
except ImportError:
    import httpx2 as httpx

from server import audit, phone, pictures  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 60
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 40

_log_patch = mock.patch.object(audit, "LOG_FILE", Path(tempfile.mkdtemp()) / "activity.log")


def setUpModule():
    _log_patch.start()


def tearDownModule():
    _log_patch.stop()


def public(host, port, proto=None):                      # a pretend DNS answer: every name is a public address (an address written as numbers is itself)
    import ipaddress
    try:
        ipaddress.ip_address(host)
        return [(2, 1, 6, "", (host, port))]
    except ValueError:
        return [(2, 1, 6, "", ("93.184.216.34", port))]


def private(host, port, proto=None):
    return [(2, 1, 6, "", ("192.168.1.5", port))]


class Recognising(unittest.TestCase):
    def test_only_real_pictures_are_accepted_whatever_they_are_called(self):
        self.assertEqual(pictures.sniff(JPEG), ("image/jpeg", "jpg"))
        self.assertEqual(pictures.sniff(PNG), ("image/png", "png"))
        self.assertEqual(pictures.sniff(WEBP), ("image/webp", "webp"))
        self.assertEqual(pictures.sniff(b"GIF89a" + b"\x00" * 20), ("image/gif", "gif"))
        for bad in (b"", b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", b"<!doctype html><script>", b"MZ\x90\x00", b"%PDF-1.7"):
            self.assertIsNone(pictures.sniff(bad), bad[:20])

    def test_a_picture_is_kept_under_a_name_made_from_its_contents(self):
        folder = Path(tempfile.mkdtemp())
        pid = pictures.save(JPEG, folder)
        self.assertRegex(pid, r"^[0-9a-f]{24}$")
        self.assertEqual(pictures.save(JPEG, folder), pid)               # the same picture is not stored twice
        path, mime = pictures.find(pid, folder)
        self.assertEqual((path.read_bytes(), mime), (JPEG, "image/jpeg"))

    def test_nothing_else_can_be_asked_for(self):
        folder = Path(tempfile.mkdtemp())
        (folder / "secret.txt").write_text("x")
        for bad in ("secret", "../secret", "..\\..\\.env", "a" * 24, "0" * 23, "0" * 25, "", "%2e%2e", "ABCDEF" * 4):
            self.assertIsNone(pictures.find(bad, folder), bad)

    def test_not_a_picture_or_too_big_is_refused(self):
        folder = Path(tempfile.mkdtemp())
        with self.assertRaises(pictures.PictureError):
            pictures.save(b"hello", folder)
        with self.assertRaises(pictures.PictureError):
            pictures.save(b"", folder)
        with mock.patch.object(pictures, "MAX_BYTES", 100):
            with self.assertRaises(pictures.PictureError):
                pictures.save(JPEG + b"\x00" * 100, folder)
        self.assertEqual(list(folder.iterdir()), [])

    def test_only_the_newest_are_kept(self):
        folder = Path(tempfile.mkdtemp())
        with mock.patch.object(pictures, "KEEP", 3):
            ids = []
            for n in range(6):
                ids.append(pictures.save(JPEG + bytes([n]), folder))
                time.sleep(0.02)
            kept = [i for i in ids if pictures.find(i, folder)]
        self.assertEqual(kept, ids[-3:])


class Downloading(unittest.TestCase):
    def client(self, handler):
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    def test_a_public_picture_downloads(self):
        got = pictures.download("https://example.com/a.jpg", self.client(lambda r: httpx.Response(200, content=JPEG)), public)
        self.assertEqual(got, JPEG)

    def test_this_pc_and_the_home_network_are_never_fetched(self):
        c = self.client(lambda r: httpx.Response(200, content=JPEG))
        for url in ("http://localhost:8000/api/status", "http://127.0.0.1/a.jpg", "file:///c:/x.jpg", "ftp://example.com/a.jpg"):
            with self.assertRaises(pictures.PictureError, msg=url):
                pictures.download(url, c, public)
        with self.assertRaises(pictures.PictureError):                    # a name that points at the router
            pictures.download("https://sneaky.example/a.jpg", c, private)

    def test_a_redirect_to_the_home_network_is_refused(self):
        def handler(request):
            if request.url.host == "example.com":
                return httpx.Response(302, headers={"location": "http://192.168.1.1/admin.jpg"})
            return httpx.Response(200, content=JPEG)

        def resolve(host, port, proto=None):
            return [(2, 1, 6, "", ("192.168.1.1" if host.startswith("192.") else "93.184.216.34", port))]
        with self.assertRaises(pictures.PictureError):
            pictures.download("https://example.com/a.jpg", self.client(handler), resolve)

    def test_too_big_and_errors_are_refused(self):
        with mock.patch.object(pictures, "MAX_BYTES", 50):
            with self.assertRaises(pictures.PictureError):
                pictures.download("https://example.com/a.jpg", self.client(lambda r: httpx.Response(200, content=JPEG)), public)
        with self.assertRaises(pictures.PictureError):
            pictures.download("https://example.com/a.jpg", self.client(lambda r: httpx.Response(404)), public)


def _hit(title, thumb="https://api.openverse.org/v1/images/x/thumb/", width=1024, height=683, mature=False, creator="Jane", licence="by", version="2.0", url="https://live.staticflickr.com/a.jpg"):
    return {"title": title, "thumbnail": thumb, "width": width, "height": height, "mature": mature, "creator": creator, "license": licence, "license_version": version, "url": url}


SEARCH = {"results": [
    _hit("Red panda", creator="<b>Jane</b>", licence="by-sa", version="4.0"),
    _hit("Red panda 2", thumb="https://api.openverse.org/v1/images/y/thumb/", creator=""),
    _hit("Tiny", width=100, height=80),
    _hit("Adult", mature=True),
    _hit("Elsewhere", thumb="https://evil.example/e.jpg"),
    {"title": "no thumbnail"},
    "garbage",
]}


class Searching(unittest.TestCase):
    def client(self):
        def handler(request):
            if request.url.host == "api.openverse.org" and request.url.path == "/v1/images/":
                self.asked = dict(request.url.params)
                return httpx.Response(200, json=SEARCH)
            return httpx.Response(200, content=JPEG)
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    def test_results_are_ranked_and_only_good_safe_ones_are_used(self):
        found = pictures.search("red panda", self.client())
        self.assertEqual([f["title"] for f in found], ["Red panda", "Red panda 2"])
        self.assertEqual(found[0]["credit"], "Jane · BY-SA 4.0 · Openverse")
        self.assertEqual(found[1]["credit"], "BY 2.0 · Openverse")
        self.assertNotIn("<", found[0]["credit"])
        self.assertEqual(self.asked["mature"], "false")                     # nothing adult is ever asked for

    def test_a_spoken_request_ends_with_an_event_for_the_wall(self):
        folder = Path(tempfile.mkdtemp())
        with mock.patch.object(pictures, "DIR", folder), mock.patch.object(pictures.agent_tools, "check_url", return_value=None):
            ev = pictures.show("red panda", client=self.client())
        self.assertEqual((ev["type"], ev["title"], ev["credit"]), ("picture", "Red panda", "Jane · BY-SA 4.0 · Openverse"))
        self.assertRegex(ev["src"], r"^/api/picture/[0-9a-f]{24}$")
        self.assertTrue(pictures.find(ev["id"], folder))

    def test_nothing_found_is_a_clear_message(self):
        with self.assertRaises(pictures.PictureError):
            pictures.show("", client=self.client())

    def test_the_ai_tool_returns_text_and_an_event_or_an_error(self):
        with mock.patch.object(pictures, "show", return_value=pictures.event("a" * 24, "Cat", "x")):
            text, ev = pictures.tool({"query": "cat"})
        self.assertIn("on the wall", text)
        self.assertEqual(ev["type"], "picture")
        with mock.patch.object(pictures, "show", side_effect=pictures.PictureError("nope")):
            text, ev = pictures.tool({"query": "cat"})
        self.assertTrue(text.startswith("Error"))
        self.assertIsNone(ev)


class Words(unittest.TestCase):
    def test_what_to_look_for(self):
        for said, want in (("show me a picture of a red panda", "a red panda"), ("Jarvis, show me a photo of the eiffel tower", "the eiffel tower"),
                           ("pull up an image of mount fuji on the wall", "mount fuji"), ("put a picture of a dog on the wall", "a dog"),
                           ("display a photo for northern lights", "northern lights"), ("can you show me some pictures of saturn", "saturn")):
            self.assertEqual(pictures.from_words(said), want, said)

    def test_everything_else_is_left_alone(self):
        for said in ("show me a hologram of a cat", "show off", "play some music", "what is a picture", "open youtube", "take a picture", "turn the lights on", ""):
            self.assertIsNone(pictures.from_words(said), said)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def post(url, body, token=None, kind="application/json"):
    headers = {"Content-Type": kind, **({"Authorization": f"Bearer {token}"} if token else {})}
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method="POST"), timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, ConnectionError, OSError):          # refused and hung up on before the body was read
        return 0, ""


class SharedFromThePhone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        cls.pictures_dir = mock.patch.object(pictures, "DIR", cls.dir / "pictures")
        cls.pictures_dir.start()
        cls.broadcasts, cls.locked = [], False
        cls.port = free_port()
        cls.service = phone.PhoneService(phone.Phones(cls.dir / "phones.json"))
        cls.service.start(lambda *a: iter(()), cls.broadcasts.append, lambda: cls.locked, port=cls.port, tls=False, host="127.0.0.1")
        for _ in range(100):
            if cls.service.server.started:
                break
            time.sleep(0.1)
        cls.base = f"http://127.0.0.1:{cls.port}"
        code = cls.service.phones.new_code()["code"]
        cls.token = json.loads(post(f"{cls.base}/pair", {"code": code, "name": "Test"})[1])["token"]

    @classmethod
    def tearDownClass(cls):
        cls.service.stop()
        cls.pictures_dir.stop()

    def setUp(self):
        self.broadcasts.clear()
        type(self).locked = False

    def test_a_shared_photo_goes_to_the_wall(self):
        status, body = post(f"{self.base}/picture?title=Holiday", JPEG, self.token, "image/jpeg")
        self.assertEqual(status, 200, body)
        event = self.broadcasts[-1]
        self.assertEqual(event["type"], "phone_event")
        self.assertEqual((event["event"]["type"], event["event"]["title"]), ("picture", "Holiday"))
        self.assertTrue(pictures.find(json.loads(body)["id"]))

    def test_only_a_real_paired_phone_can_send_pictures(self):
        self.assertIn(post(f"{self.base}/picture", JPEG, None, "image/jpeg")[0], (0, 401))
        self.assertIn(post(f"{self.base}/picture", JPEG, "made-up", "image/jpeg")[0], (0, 401))
        self.assertEqual(post(f"{self.base}/share", {"what": "note", "text": "hi"})[0], 401)
        self.assertEqual(self.broadcasts, [])

    def test_something_that_is_not_a_picture_is_refused(self):
        for bad in (b"<svg onload=alert(1)>", b"MZ\x90\x00 program", b"hello"):
            self.assertEqual(post(f"{self.base}/picture", bad, self.token, "image/jpeg")[0], 400, bad)
        self.assertEqual(self.broadcasts, [])

    def test_a_huge_upload_is_refused(self):
        with mock.patch.object(pictures, "MAX_BYTES", 1000):
            self.assertEqual(post(f"{self.base}/picture", JPEG + b"\x00" * 5000, self.token, "image/jpeg")[0], 413)

    def test_the_privacy_screen_stops_sharing_too(self):
        type(self).locked = True
        self.assertEqual(post(f"{self.base}/picture", JPEG, self.token, "image/jpeg")[0], 423)
        self.assertEqual(post(f"{self.base}/share", {"what": "note", "text": "hi"}, self.token)[0], 423)

    def test_shared_text_becomes_a_note_and_nothing_more(self):
        status, _ = post(f"{self.base}/share", {"what": "note", "text": "  buy   milk \n and eggs "}, self.token)
        self.assertEqual(status, 200)
        self.assertEqual(self.broadcasts[-1]["event"], {"type": "add_note", "text": "buy milk and eggs", "color": "cyan"})
        self.assertEqual(post(f"{self.base}/share", {"what": "delete-everything", "text": "x"}, self.token)[0], 422)

    def test_a_shared_link_opens_on_the_pc_only_through_the_browser_guard(self):
        with mock.patch.object(phone.browser_mod, "open_url", return_value="Opened example.com in Chrome.") as opened:
            status, body = post(f"{self.base}/share", {"what": "open", "text": "https://example.com/a?b=1 extra words"}, self.token)
        self.assertEqual(status, 200, body)
        opened.assert_called_once_with("https://example.com/a?b=1")
        with mock.patch.object(phone.browser_mod, "open_url", side_effect=phone.browser_mod.BrowserError("local addresses are not allowed")):
            status, body = post(f"{self.base}/share", {"what": "open", "text": "http://192.168.1.1/"}, self.token)
        self.assertEqual(status, 400)

    def test_the_phone_is_told_a_picture_is_on_the_wall(self):
        self.assertIn("picture", phone.WALL_EVENTS)
        self.assertIn("wall", phone.wall_line({"type": "picture", "title": "Cat"}))


class Wall(unittest.TestCase):
    """The wall's page only accepts the PC's own picture addresses, and the app's pieces fit together."""

    def test_the_card_refuses_any_other_address(self):
        js = (ROOT / "web" / "picture.js").read_text("utf-8")
        self.assertIn(r"/^\/api\/picture\/[0-9a-f]{24}$/", js)
        self.assertNotIn("innerHTML", js)

    def test_the_card_is_wired_into_the_page(self):
        app = (ROOT / "web" / "app.js").read_text("utf-8")
        chat = (ROOT / "web" / "chat.js").read_text("utf-8")
        html = (ROOT / "web" / "index.html").read_text("utf-8")
        self.assertIn('id="picture"', html)
        self.assertIn("chat.onPicture", app)
        self.assertIn("pictureUI.handleVoice", app)
        self.assertEqual(chat.count("onPicture"), 2)

    def test_the_ai_can_show_pictures_and_not_after_private_data(self):
        agent = (ROOT / "server" / "agent.py").read_text("utf-8")
        self.assertIn('"picture"', agent)
        self.assertRegex(agent, r'elif call\["name"\] == "picture" and private_touched')
        self.assertIn("pictures.tool(args)", agent)

    def test_the_picture_route_serves_only_checked_files(self):
        main = (ROOT / "server" / "main.py").read_text("utf-8")
        self.assertIn('@app.get("/api/picture/{pid}")', main)
        self.assertIn("pictures_mod.find(pid)", main)
        self.assertIn("nosniff", main[main.index("def get_picture"):main.index("def voice_picture")])

    def test_the_whole_photo_fits_the_card(self):
        """A tall photo used to grow the card's auto-sized row and show only its top: the image must fill a fixed frame and scale to fit it."""
        css = (Path(__file__).resolve().parent.parent / "web" / "style.css").read_text(encoding="utf-8")
        frame = re.search(r"^#picture-frame \{([^}]*)\}", css, re.M).group(1)
        image = re.search(r"^#picture-img \{([^}]*)\}", css, re.M).group(1)
        self.assertIn("minmax(0, 1fr)", frame)                    # the row cannot grow past the frame
        for need in ("width: 100%", "height: 100%", "object-fit: contain"):
            self.assertIn(need, image)
        self.assertNotIn("max-height", image)


if __name__ == "__main__":
    unittest.main()
