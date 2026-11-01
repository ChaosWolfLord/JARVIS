"""Tests for the encrypted Google token, the optional write permission, and the three actions that ask first
(save a Gmail draft, add a calendar event, send a Discord message). HTTP is faked; nothing touches a real account."""
import base64
import json
import sys
import tempfile
import unittest
from datetime import datetime
from email import message_from_bytes
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import agent, agent_tools, audit, discord_tools, google_auth, google_tools, secretbox  # noqa: E402

httpx = agent_tools.httpx


def client(routes):
    def handler(request):
        for key, value in routes.items():
            if key in request.url.path:
                return value(request) if callable(value) else httpx.Response(200, json=value)
        return httpx.Response(404, json={})
    return httpx.Client(transport=httpx.MockTransport(handler))


@unittest.skipUnless(secretbox.available(), "Windows data protection is needed")
class EncryptedToken(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "token.json"
        for patch in (mock.patch.object(google_auth, "TOKEN_FILE", self.file), mock.patch.dict(google_auth._cache, {"token": None, "expires": 0.0})):
            patch.start()
            self.addCleanup(patch.stop)

    def test_round_trip_and_nothing_readable_on_disk(self):
        google_auth.save_token({"refresh_token": "super-secret-refresh", "scope": "a b"})
        on_disk = self.file.read_text()
        self.assertNotIn("super-secret-refresh", on_disk)
        self.assertEqual(google_auth.load_token()["refresh_token"], "super-secret-refresh")
        self.assertTrue(google_auth.connected())

    def test_an_old_plain_text_token_is_read_once_and_re_saved_encrypted(self):
        self.file.write_text(json.dumps({"refresh_token": "old-plain-token", "scope": "x"}))
        self.assertEqual(google_auth.load_token()["refresh_token"], "old-plain-token")
        self.assertNotIn("old-plain-token", self.file.read_text())
        self.assertEqual(google_auth.load_token()["refresh_token"], "old-plain-token")        # still readable afterwards

    def test_a_token_this_account_cant_decrypt_counts_as_not_connected(self):
        self.file.write_text(json.dumps({"v": 2, "sealed": base64.b64encode(b"not from this account").decode()}))
        self.assertEqual(google_auth.load_token(), {})
        self.assertFalse(google_auth.connected())

    def test_missing_file_is_just_not_connected(self):
        self.assertFalse(google_auth.connected())
        self.assertFalse(google_auth.has_write())

    def test_write_permission_is_known_only_if_both_scopes_were_granted(self):
        google_auth.save_token({"refresh_token": "r", "scope": " ".join(google_auth.SCOPES)})
        self.assertFalse(google_auth.has_write())
        google_auth.save_token({"refresh_token": "r", "scope": " ".join(google_auth.SCOPES + google_auth.WRITE_SCOPES)})
        self.assertTrue(google_auth.has_write())
        google_auth.save_token({"refresh_token": "r", "scope": " ".join(google_auth.SCOPES + google_auth.WRITE_SCOPES[:1])})
        self.assertFalse(google_auth.has_write())

    def test_the_sign_in_link_asks_for_write_only_when_told_to(self):
        info = {"client_id": "c", "client_secret": "s", "auth_uri": google_auth.AUTH_URI, "token_uri": google_auth.TOKEN_URI}
        plain = google_auth.auth_url(info, "http://127.0.0.1:1", "st", "ch")
        write = google_auth.auth_url(info, "http://127.0.0.1:1", "st", "ch", write=True)
        self.assertNotIn("gmail.compose", plain)
        self.assertNotIn("calendar.events", plain)
        self.assertIn("gmail.compose", write)
        self.assertIn("calendar.events", write)
        self.assertNotIn("gmail.send", write)                    # JARVIS never asks to send mail
        self.assertNotIn("gmail.modify", write)


@unittest.skipUnless(secretbox.available(), "Windows data protection is needed")
class SignInAccount(unittest.TestCase):
    """The sign-in opens on the account JARVIS already uses, and refuses to save a different one."""

    CLIENT = {"installed": {"client_id": "cid", "client_secret": "sec"}}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "client.json").write_text(json.dumps(self.CLIENT))
        for patch in (mock.patch.object(google_auth, "TOKEN_FILE", root / "token.json"), mock.patch.object(google_auth, "CLIENT_FILE", root / "client.json"),
                      mock.patch.dict(google_auth._cache, {"token": None, "expires": 0.0})):
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_link_names_the_account_when_one_is_given(self):
        info = {"client_id": "c", "client_secret": "s", "auth_uri": google_auth.AUTH_URI, "token_uri": google_auth.TOKEN_URI}
        self.assertIn("login_hint=me%40gmail.com", google_auth.auth_url(info, "http://127.0.0.1:1", "st", "ch", login_hint="me@gmail.com"))
        self.assertNotIn("login_hint", google_auth.auth_url(info, "http://127.0.0.1:1", "st", "ch"))

    def sign_in(self, signed_in_as, hint):
        import threading
        import urllib.parse

        def browser(url):
            q = dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))
            threading.Thread(target=lambda: httpx.get(f"{q['redirect_uri']}/?code=abc&state={q['state']}", timeout=5), daemon=True).start()

        routes = {"/token": {"access_token": "A", "refresh_token": "R", "scope": " ".join(google_auth.SCOPES), "expires_in": 3600},
                  "/profile": {"emailAddress": signed_in_as}}
        google_auth.authorize(open_browser=browser, timeout=10, client=client(routes), login_hint=hint)

    def test_the_right_account_is_saved_with_its_address(self):
        self.sign_in("Me@Gmail.com", "me@gmail.com")
        self.assertEqual(google_auth.load_token()["email"], "Me@Gmail.com")
        self.assertEqual(google_auth.account_email(), "Me@Gmail.com")

    def test_a_different_account_is_refused_and_nothing_is_saved(self):
        with self.assertRaises(google_auth.GoogleAuthError) as cm:
            self.sign_in("school@example.edu", "me@gmail.com")
        self.assertIn("me@gmail.com", str(cm.exception))
        self.assertFalse(google_auth.connected())

    def test_an_older_sign_in_finds_its_address_from_google(self):
        google_auth.save_token({"refresh_token": "R", "scope": "x"})            # saved before addresses were remembered
        with mock.patch.object(google_auth, "access_token", return_value="A"):
            self.assertEqual(google_auth.account_email(client("") if False else client({"/profile": {"emailAddress": "old@gmail.com"}})), "old@gmail.com")


class Events(unittest.TestCase):
    def test_a_timed_event_defaults_to_an_hour(self):
        p = google_tools.prepare_event({"title": "Dentist", "start": "2026-10-30T14:00", "location": "Main St"})
        self.assertEqual(p["payload"]["summary"], "Dentist")
        start, end = (datetime.fromisoformat(p["payload"][k]["dateTime"]) for k in ("start", "end"))
        self.assertEqual((end - start).total_seconds(), 3600)
        self.assertIsNotNone(start.tzinfo)                       # carries an offset so Google knows the zone
        self.assertIn("Title: Dentist", p["preview"])
        self.assertIn("Where: Main St", p["preview"])
        self.assertIn("14:00", p["summary"])

    def test_an_all_day_event_uses_dates(self):
        p = google_tools.prepare_event({"title": "Trip", "start": "2026-11-02", "end": "2026-11-05"})
        self.assertEqual(p["payload"]["start"], {"date": "2026-11-02"})
        self.assertEqual(p["payload"]["end"], {"date": "2026-11-05"})
        self.assertIn("all day", p["preview"])
        self.assertEqual(google_tools.prepare_event({"title": "x", "start": "2026-11-02"})["payload"]["end"], {"date": "2026-11-03"})

    def test_bad_events_are_refused_before_anything_is_shown(self):
        for args in ({"title": "", "start": "2026-10-30T14:00"}, {"title": "x"}, {"title": "x", "start": "next tuesday"},
                     {"title": "x", "start": "2026-10-30T14:00", "end": "2026-10-30T13:00"},
                     {"title": "x", "start": "2026-10-30", "end": "2026-10-30T10:00"},
                     {"title": "x", "start": "2026-10-01", "end": "2026-12-01"}):
            with self.assertRaises(ValueError, msg=str(args)):
                google_tools.prepare_event(args)

    def test_insert_posts_the_prepared_event_and_a_refusal_explains_the_fix(self):
        prepared = google_tools.prepare_event({"title": "Dentist", "start": "2026-10-30T14:00"})
        seen = {}

        def handler(request):
            seen.update(json.loads(request.content), path=request.url.path)
            return httpx.Response(200, json={"id": "e1"})

        with mock.patch.object(google_auth, "access_token", return_value="tok"):
            msg = google_tools.insert_event(prepared, client({"/events": handler}))
            self.assertEqual(seen["summary"], "Dentist")
            self.assertTrue(seen["path"].endswith("/calendars/primary/events"))
            self.assertIn("Dentist", msg)
            with self.assertRaises(google_auth.GoogleAuthError) as cm:
                google_tools.insert_event(prepared, client({"/events": lambda r: httpx.Response(403, json={})}))
        self.assertIn("connect.bat google write", str(cm.exception))


class Drafts(unittest.TestCase):
    META = {"threadId": "t1", "payload": {"headers": [
        {"name": "From", "value": "Sam <sam@example.com>"}, {"name": "Subject", "value": "Dinner Friday?"},
        {"name": "Message-ID", "value": "<abc@mail.example.com>"}, {"name": "References", "value": "<first@mail.example.com>"}]}}

    def setUp(self):
        patch = mock.patch.object(google_auth, "access_token", return_value="tok")
        patch.start()
        self.addCleanup(patch.stop)

    def decode(self, prepared):
        return message_from_bytes(base64.urlsafe_b64decode(prepared["raw"]))

    def test_the_reply_goes_to_the_sender_with_the_right_headers(self):
        p = google_tools.prepare_reply("abc123", "Sounds great, 7pm works.", client({"/messages/abc123": self.META}))
        m = self.decode(p)
        self.assertEqual(m["To"], "Sam <sam@example.com>")
        self.assertEqual(m["Subject"], "Re: Dinner Friday?")
        self.assertEqual(m["In-Reply-To"], "<abc@mail.example.com>")
        self.assertEqual(m["References"], "<first@mail.example.com> <abc@mail.example.com>")
        self.assertIn("Sounds great", m.get_payload())
        self.assertEqual(p["thread_id"], "t1")
        self.assertIn("To: Sam", p["preview"])

    def test_reply_to_wins_and_re_is_not_doubled(self):
        meta = json.loads(json.dumps(self.META))
        meta["payload"]["headers"] += [{"name": "Reply-To", "value": "team@example.com"}]
        meta["payload"]["headers"][1]["value"] = "RE: Dinner Friday?"
        m = self.decode(google_tools.prepare_reply("abc123", "ok", client({"/messages/abc123": meta})))
        self.assertEqual(m["To"], "team@example.com")
        self.assertEqual(m["Subject"], "RE: Dinner Friday?")

    def test_a_header_injection_attempt_is_refused(self):
        meta = json.loads(json.dumps(self.META))
        meta["payload"]["headers"][1]["value"] = "Hi\r\nBcc: attacker@evil.example"
        with self.assertRaises(ValueError):
            google_tools.prepare_reply("abc123", "x", client({"/messages/abc123": meta}))

    def test_nonsense_is_refused(self):
        for args in (("not-an-id", "text"), ("abc123", "   "), ("../../x", "text")):
            with self.assertRaises(ValueError):
                google_tools.prepare_reply(*args, client=client({"/messages": self.META}))

    def test_saving_posts_a_draft_never_a_send(self):
        p = google_tools.prepare_reply("abc123", "ok", client({"/messages/abc123": self.META}))
        paths = []

        def handler(request):
            paths.append(request.url.path)
            body = json.loads(request.content)
            self.assertEqual(body["message"]["threadId"], "t1")
            return httpx.Response(200, json={"id": "d1"})

        msg = google_tools.save_draft(p, client({"/drafts": handler}))
        self.assertTrue(paths[0].endswith("/drafts"))
        self.assertFalse(any("send" in x for x in paths))
        self.assertIn("NOT been sent", msg)


class DiscordSend(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "bot-token"})
        patch.start()
        self.addCleanup(patch.stop)
        self.routes = {"/users/@me/guilds": [{"id": "1", "name": "My Server"}],
                       "/guilds/1/channels": [{"id": "111111111111111111", "name": "general", "type": 0}]}

    def test_prepare_names_the_channel_and_changes_nothing(self):
        sent = []
        p = discord_tools.prepare_send("#general", "Meeting at 5", client({**self.routes, "/messages": lambda r: sent.append(1)}))
        self.assertIn("My Server / #general", p["preview"])
        self.assertIn("Meeting at 5", p["preview"])
        self.assertEqual(sent, [])

    def test_the_message_cannot_ping_everyone(self):
        seen = {}

        def handler(request):
            seen.update(json.loads(request.content), auth=request.headers["authorization"])
            return httpx.Response(200, json={"id": "m"})

        p = discord_tools.prepare_send("#general", "@everyone hello", client(self.routes))
        discord_tools.send_message(p, client({"/channels/111111111111111111/messages": handler}))
        self.assertEqual(seen["allowed_mentions"], {"parse": []})
        self.assertEqual(seen["auth"], "Bot bot-token")

    def test_empty_unknown_and_refused_are_explained(self):
        with self.assertRaises(discord_tools.DiscordError):
            discord_tools.prepare_send("#general", "  ", client(self.routes))
        with self.assertRaises(discord_tools.DiscordError):
            discord_tools.prepare_send("#nope", "hi", client(self.routes))
        p = discord_tools.prepare_send("#general", "hi", client(self.routes))
        with self.assertRaises(discord_tools.DiscordError) as cm:
            discord_tools.send_message(p, client({"/messages": lambda r: httpx.Response(403, json={})}))
        self.assertIn("Send Messages", str(cm.exception))


class AskFirst(unittest.TestCase):
    """The agent shows exactly what will happen and does nothing unless the user allows it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.object(audit, "LOG_FILE", Path(tmp.name) / "a.log")
        patch.start()
        self.addCleanup(patch.stop)

    def run_action(self, name, args, allow, **patches):
        results = []
        with mock.patch.object(agent.runner, "wait", return_value=allow):
            events = list(agent._run_action(name, args))
        return events

    def test_an_event_is_added_only_after_allow(self):
        with mock.patch.object(google_tools, "insert_event", return_value="Event added.") as insert:
            events = self.run_action("calendar_add_event", {"title": "Dentist", "start": "2026-10-30T14:00"}, allow=True)
        card = events[0]
        self.assertEqual((card["type"], card["kind"]), ("run_request", "tool"))
        self.assertIn("add this event", card["title"])
        self.assertIn("Dentist", card["code"])
        insert.assert_called_once()
        self.assertEqual(events[-1], "Event added.")

    def test_declining_does_nothing(self):
        with mock.patch.object(google_tools, "insert_event") as insert:
            events = self.run_action("calendar_add_event", {"title": "Dentist", "start": "2026-10-30T14:00"}, allow=False)
        insert.assert_not_called()
        self.assertIn("did not allow", events[-1])
        self.assertTrue(any(e.get("declined") for e in events if isinstance(e, dict)))

    def test_a_bad_request_never_reaches_the_user_or_google(self):
        with mock.patch.object(agent.runner, "request") as asked:
            events = list(agent._run_action("calendar_add_event", {"title": "", "start": "2026-10-30T14:00"}))
        asked.assert_not_called()
        self.assertTrue(events[-1].startswith("Error"))

    def test_the_draft_card_says_it_will_not_be_sent(self):
        prepared = {"raw": "x", "thread_id": None, "preview": "To: a@b.c\nSubject: Re: hi\n\nok", "summary": "to a@b.c"}
        with mock.patch.object(google_tools, "prepare_reply", return_value=prepared), mock.patch.object(google_tools, "save_draft", return_value="Saved.") as save:
            events = self.run_action("gmail_draft_reply", {"id": "abc123", "body": "ok"}, allow=True)
        self.assertIn("NOT be sent", events[0]["title"])
        save.assert_called_once()

    def test_discord_card_shows_the_channel_and_text(self):
        prepared = {"channel_id": "1", "text": "hi", "preview": "To: S / #general\n\nhi", "summary": "#general"}
        with mock.patch.object(discord_tools, "prepare_send", return_value=prepared), mock.patch.object(discord_tools, "send_message", return_value="Message sent to #general.") as send:
            events = self.run_action("discord_send", {"channel": "#general", "text": "hi"}, allow=True)
        self.assertIn("#general", events[0]["code"])
        send.assert_called_once()

    def test_a_failure_after_allow_is_reported(self):
        prepared = {"channel_id": "1", "text": "hi", "preview": "p", "summary": "#general"}
        with mock.patch.object(discord_tools, "prepare_send", return_value=prepared), \
                mock.patch.object(discord_tools, "send_message", side_effect=discord_tools.DiscordError("refused")):
            events = self.run_action("discord_send", {"channel": "#general", "text": "hi"}, allow=True)
        self.assertEqual(events[-1], "Error: refused")

    def test_the_actions_are_offered_only_when_they_can_work(self):
        names = lambda: {t["function"]["name"] for t in agent.active_tools()}   # noqa: E731
        off = {k: (lambda: False) for k in ("gmail_draft_reply", "calendar_add_event", "discord_send")}
        with mock.patch.dict(agent.CONNECTORS, off):
            self.assertFalse(names() & set(off))
        on = {"gmail_draft_reply": lambda: True, "calendar_add_event": lambda: True}
        with mock.patch.dict(agent.CONNECTORS, {**off, **on}):
            self.assertEqual(names() & set(off), set(on))

    def test_actions_are_logged_as_private_and_in_the_loop_they_continue_the_turn(self):
        audit.tool("discord_send", {"channel": "#general", "text": "SECRET TEXT"}, "Message sent.", False)
        entry = audit.recent()[0]
        self.assertEqual(entry["what"], "#general")
        self.assertNotIn("SECRET", json.dumps(entry))
        self.assertTrue(entry["private"])
        self.assertTrue(agent._gives_result_back("calendar_add_event"))


if __name__ == "__main__":
    unittest.main()
