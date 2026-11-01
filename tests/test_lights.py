"""Tests for the Govee lights: spoken commands, choosing lights, the local (UDP) protocol, the cloud calls, and the AI tool.
Nothing here touches a real light or the real network."""
import atexit
import json
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import agent, agent_tools, audit, lights  # noqa: E402

httpx = agent_tools.httpx


class FakeLan:
    def __init__(self, found=(), statuses=None):
        self.found, self.status_data, self.sent, self.scans = list(found), statuses or {}, [], []

    def scan(self, extra_ips=(), timeout=3.0):
        self.scans.append(list(extra_ips))
        return self.found

    def send(self, ip, cmd, data):
        self.sent.append((ip, cmd, data))

    def statuses(self, ips, timeout=2.0):
        return {ip: self.status_data[ip] for ip in ips if ip in self.status_data}


def registry(lan=None, cloud=None, known=()):
    folder = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    reg = lights.Lights(lan=lan or FakeLan(), cloud=cloud, path=Path(folder) / "lights.json")
    for i, (name, ip) in enumerate(known):
        reg.lights[f"id{i}"] = lights.Light(id=f"id{i}", sku="H6001", name=name, ip=ip, state={"on": True, "brightness": 60})
    return reg


class Parsing(unittest.TestCase):
    def check(self, text, **expected):
        self.assertEqual(lights.parse_command(text), expected, text)

    def test_power(self):
        self.check("Jarvis, turn the lights off", power=False)
        self.check("lights on", power=True)
        self.check("turn off all the lights", power=False)

    def test_which_lights(self):
        self.check("turn the desk lights blue", color="blue", target="desk")
        self.check("turn on the bedroom lamp", power=True, target="bedroom")
        self.check("set the living room lights to warm", kelvin=2700, target="living room")

    def test_brightness(self):
        self.check("set the lights to 40 percent", brightness=40)
        self.check("turn the kitchen lights to 30%", brightness=30, target="kitchen")
        self.check("lights to forty five percent", brightness=45)
        self.check("dim the lights", delta=-25)
        self.check("brighten the lights", delta=25)
        self.check("lights to half", brightness=50)
        self.check("lights to full brightness", brightness=100)

    def test_colours_and_whites(self):
        self.check("set the lights to #ff8800", color="#ff8800")
        self.check("make the lights cool", kelvin=6500)
        self.check("set the lights to white", kelvin=4500)

    def test_scenes(self):
        self.check("relax mode", brightness=30, kelvin=2200, scene="relax")
        self.check("movie lighting", brightness=10, kelvin=2700, scene="movie")

    def test_questions_and_other_talk_are_left_to_the_ai(self):
        for text in ("what lights are on", "is the light on", "How bright are the lights", "play some music", "what's the weather", "lock the door",
                     "make it brighter", "turn the heating on"):
            self.assertIsNone(lights.parse_command(text), text)

    def test_a_light_word_with_nothing_to_do_is_ignored(self):
        self.assertIsNone(lights.parse_command("I need a light snack"))


class Choosing(unittest.TestCase):
    def test_all_by_default_and_by_name(self):
        reg = registry(known=[("Desk lamp", "10.0.0.2"), ("Bed strip", "10.0.0.3")])
        self.assertEqual(len(reg.pick("")), 2)
        self.assertEqual(len(reg.pick("all the lights")), 2)
        self.assertEqual([l.name for l in reg.pick("desk")], ["Desk lamp"])
        self.assertEqual([l.name for l in reg.pick("the bed strip")], ["Bed strip"])

    def test_an_unknown_name_lists_what_is_known(self):
        reg = registry(known=[("Desk lamp", "10.0.0.2")])
        with self.assertRaisesRegex(lights.LightError, "Desk lamp"):
            reg.pick("garage")

    def test_no_lights_explains_how_to_set_up(self):
        with self.assertRaisesRegex(lights.LightError, "LAN Control"):
            registry().pick("")

    def test_renaming(self):
        reg = registry(known=[("", "10.0.0.2")])
        self.assertEqual(reg.rename("id0", "  Desk   lamp ").name, "Desk lamp")
        self.assertEqual(lights.Lights(path=reg.path).lights["id0"].name, "Desk lamp")        # remembered on disk
        with self.assertRaises(lights.LightError):
            reg.rename("nope", "x")
        with self.assertRaises(lights.LightError):
            reg.rename("id0", "  ")


class Commands(unittest.TestCase):
    def setUp(self):
        self.lan = FakeLan()
        self.reg = registry(self.lan, known=[("Desk", "10.0.0.2")])

    def test_power_brightness_colour_go_to_the_light(self):
        self.reg.command(power=False)
        self.reg.command(brightness=40)                # it was just switched off, so changing it switches it back on first
        self.reg.command(color="blue")
        self.reg.command(kelvin=2700)
        self.assertEqual(self.lan.sent, [
            ("10.0.0.2", "turn", {"value": 0}), ("10.0.0.2", "turn", {"value": 1}), ("10.0.0.2", "brightness", {"value": 40}),
            ("10.0.0.2", "colorwc", {"color": {"r": 0, "g": 60, "b": 255}, "colorTemInKelvin": 0}),
            ("10.0.0.2", "colorwc", {"color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": 2700})])

    def test_changing_the_look_of_a_light_that_is_off_turns_it_on(self):
        self.reg.lights["id0"].state["on"] = False
        self.reg.command(color="red")
        self.assertEqual(self.lan.sent[0][1:], ("turn", {"value": 1}))

    def test_dimmer_and_brighter_are_relative_and_clamped(self):
        self.reg.command(delta=-25)
        self.assertEqual(self.lan.sent[-1][2], {"value": 35})
        self.reg.lights["id0"].state["brightness"] = 95
        self.reg.command(delta=25)
        self.assertEqual(self.lan.sent[-1][2], {"value": 100})

    def test_values_are_kept_in_range(self):
        self.reg.command(brightness=500, kelvin=100)
        self.assertEqual(self.lan.sent[0][2], {"value": 100})
        self.assertEqual(self.lan.sent[1][2]["colorTemInKelvin"], 2000)

    def test_bad_colour_and_empty_command_are_explained_and_send_nothing(self):
        with self.assertRaisesRegex(lights.LightError, "colour"):
            self.reg.command(color="plaid")
        with self.assertRaisesRegex(lights.LightError, "nothing to change"):
            self.reg.command()
        self.assertEqual(self.lan.sent, [])

    def test_only_the_named_light_changes(self):
        other = registry(self.lan, known=[("Desk", "10.0.0.2"), ("Bed", "10.0.0.3")])
        other.command(target="bed", power=False)
        self.assertEqual({s[0] for s in self.lan.sent}, {"10.0.0.3"})

    def test_a_light_that_cant_be_reached_is_reported_but_others_still_change(self):
        class Flaky(FakeLan):
            def send(self, ip, cmd, data):
                if ip == "10.0.0.3":
                    raise lights.LightError("couldn't reach the light at 10.0.0.3.")
                super().send(ip, cmd, data)
        reg = registry(Flaky(), known=[("Desk", "10.0.0.2"), ("Bed", "10.0.0.3")])
        text = reg.command(power=True)
        self.assertIn("Desk", text)
        self.assertIn("Bed:", text)
        self.assertIn("couldn't reach", text)

    def test_the_local_network_is_tried_first_and_the_cloud_is_the_fallback(self):
        class Down(FakeLan):
            def send(self, ip, cmd, data):
                raise lights.LightError("down")
        cloud = mock.Mock()
        reg = registry(Down(), cloud=cloud, known=[("Desk", "10.0.0.2")])
        reg.lights["id0"].cloud = True
        reg.command(power=True, brightness=20)
        cloud.control.assert_any_call("H6001", "id0", "devices.capabilities.on_off", "powerSwitch", 1)
        cloud.control.assert_any_call("H6001", "id0", "devices.capabilities.range", "brightness", 20)

    def test_a_cloud_only_light_uses_the_cloud(self):
        cloud = mock.Mock()
        reg = registry(cloud=cloud)
        reg.lights["c"] = lights.Light(id="c", sku="H6199", name="Strip", cloud=True)
        reg.command(color="#102030")
        cloud.control.assert_called_once_with("H6199", "c", "devices.capabilities.color_setting", "colorRgb", 0x102030)


class Discovery(unittest.TestCase):
    def test_found_lights_are_remembered_and_tried_directly_next_time(self):
        lan = FakeLan(found=[{"ip": "10.0.0.7", "device": "AA:BB", "sku": "H6159"}])
        reg = registry(lan)
        reg.discover()
        self.assertEqual(reg.lights["AA:BB"].ip, "10.0.0.7")
        again = lights.Lights(lan=FakeLan(), path=reg.path)
        self.assertEqual(again.lights["AA:BB"].sku, "H6159")                 # known before any scan
        again.discover()
        self.assertIn("10.0.0.7", again.lan.scans[0])                        # asked directly, which works where multicast doesn't

    def test_manual_addresses_from_env_are_asked_directly(self):
        lan = FakeLan()
        with mock.patch.dict("os.environ", {"GOVEE_IPS": "192.168.1.9, 192.168.1.10"}):
            registry(lan).discover()
        self.assertEqual(lan.scans[0], ["192.168.1.9", "192.168.1.10"])

    def test_cloud_adds_names_and_only_lights(self):
        cloud = mock.Mock()
        cloud.devices.return_value = [{"sku": "H6199", "device": "CC:DD", "deviceName": "TV strip", "type": "devices.types.light"}]
        reg = registry(cloud=cloud)
        reg.discover()
        self.assertEqual((reg.lights["CC:DD"].name, reg.lights["CC:DD"].cloud), ("TV strip", True))

    def test_a_cloud_error_is_kept_not_raised(self):
        cloud = mock.Mock()
        cloud.devices.side_effect = lights.LightError("Govee didn't accept the API key.")
        reg = registry(cloud=cloud)
        reg.discover()
        self.assertIn("API key", reg.error)

    def test_states_are_read_from_the_light(self):
        lan = FakeLan(statuses={"10.0.0.2": {"onOff": 1, "brightness": 72, "color": {"r": 1, "g": 2, "b": 3}, "colorTemInKelvin": 0}})
        reg = registry(lan, known=[("Desk", "10.0.0.2"), ("Gone", "10.0.0.9")])
        reg.refresh_states()
        self.assertEqual(reg.lights["id0"].state["brightness"], 72)
        self.assertFalse(reg.lights["id1"].state["reachable"])


class CloudCalls(unittest.TestCase):
    def cloud(self, handler):
        return lights.Cloud("KEY", client=httpx.Client(transport=httpx.MockTransport(handler)))

    def test_lists_only_lights_and_sends_the_key(self):
        seen = {}

        def handler(request):
            seen["key"] = request.headers.get("govee-api-key")
            return httpx.Response(200, json={"code": 200, "data": [{"sku": "A", "device": "1", "type": "devices.types.light"},
                                                                    {"sku": "B", "device": "2", "type": "devices.types.heater"}]})
        self.assertEqual([d["device"] for d in self.cloud(handler).devices()], ["1"])
        self.assertEqual(seen["key"], "KEY")

    def test_errors_are_explained(self):
        for status, words in ((401, "API key"), (429, "rate-limiting")):
            with self.assertRaisesRegex(lights.LightError, words):
                self.cloud(lambda r, s=status: httpx.Response(s, json={})).devices()

    def test_state_is_translated(self):
        body = {"code": 200, "payload": {"capabilities": [
            {"instance": "powerSwitch", "state": {"value": 1}}, {"instance": "brightness", "state": {"value": 55}},
            {"instance": "colorRgb", "state": {"value": 0x0A141E}}]}}
        state = self.cloud(lambda r: httpx.Response(200, json=body)).state("A", "1")
        self.assertEqual(state, {"on": True, "brightness": 55, "color": {"r": 10, "g": 20, "b": 30}})


class LocalProtocol(unittest.TestCase):
    """A fake light listening on the loopback address, driven by the real UDP code."""

    def test_status_and_control_round_trip(self):
        try:
            light = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            light.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            light.bind(("127.0.0.1", lights.CONTROL_PORT))
        except OSError:
            self.skipTest("UDP port 4003 is in use on this PC")
        self.addCleanup(light.close)
        light.settimeout(3)
        got = []

        def serve():
            for _ in range(2):
                try:
                    data, addr = light.recvfrom(4096)
                except OSError:
                    return
                msg = json.loads(data)["msg"]
                got.append(msg)
                if msg["cmd"] == "devStatus":
                    reply = {"msg": {"cmd": "devStatus", "data": {"onOff": 1, "brightness": 33, "color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": 3000}}}
                    light.sendto(json.dumps(reply).encode(), ("127.0.0.1", lights.LISTEN_PORT))
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        lan = lights.Lan(addresses=lambda: [])
        try:
            status = lan.status("127.0.0.1", timeout=2.5)
        except OSError:
            self.skipTest("UDP port 4002 is in use on this PC")
        self.assertEqual((status["onOff"], status["brightness"]), (1, 33))
        lan.send("127.0.0.1", "turn", {"value": 1})
        thread.join(3)
        self.assertEqual([m["cmd"] for m in got], ["devStatus", "turn"])

    def test_local_addresses_skip_loopback_and_link_local(self):
        for ip in lights.local_addresses():
            self.assertFalse(ip.startswith(("127.", "169.254.")))


class AiToolAndVoice(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.object(audit, "LOG_FILE", Path(tmp.name) / "a.log")
        patch.start()
        self.addCleanup(patch.stop)
        self.lan = FakeLan()
        self.reg = registry(self.lan, known=[("Desk", "10.0.0.2")])

    def test_tool_sets_lists_and_explains(self):
        self.assertIn("Desk", lights.tool({"power": False, "target": "desk"}, self.reg))
        self.assertEqual(self.lan.sent[-1][1:], ("turn", {"value": 0}))
        lights.tool({"scene": "movie"}, self.reg)
        self.assertEqual(self.lan.sent[-1][2]["colorTemInKelvin"], 2700)
        self.assertIn("Desk", lights.tool({"action": "list"}, self.reg))
        self.assertTrue(lights.tool({"color": "plaid"}, self.reg).startswith("Error"))
        self.assertTrue(lights.tool({"brightness": "lots"}, self.reg).startswith("Error"))

    def test_voice_handles_light_commands_only(self):
        out = lights.handle_voice("turn the lights off", self.reg)
        self.assertEqual((out["handled"], out["ok"]), (True, True))
        self.assertEqual(self.lan.sent[-1][1:], ("turn", {"value": 0}))
        self.assertFalse(lights.handle_voice("tell me a joke", self.reg)["handled"])

    def test_voice_errors_say_what_went_wrong_in_any_mood(self):
        for snark in ("0", "1", "2", "3"):
            with mock.patch.dict("os.environ", {"JARVIS_SNARK": snark}):
                out = lights.handle_voice("turn the garage lights on", self.reg)
            self.assertTrue(out["handled"] and not out["ok"])
            self.assertIn("garage", out["text"])

    def test_the_tool_is_offered_only_when_lights_exist_and_never_asks_or_reaches_other_devices(self):
        names = lambda: {t["function"]["name"] for t in agent.active_tools()}   # noqa: E731
        with mock.patch.dict(agent.CONNECTORS, {"lights": lambda: False}):
            self.assertNotIn("lights", names())
        with mock.patch.dict(agent.CONNECTORS, {"lights": lambda: True}):
            self.assertIn("lights", names())
        self.assertIn("lights", agent.FOLLOW_UP_TOOLS)
        self.assertNotIn("lights", agent.ACTION_TOOLS)
        params = next(t for t in agent.TOOLS if t["function"]["name"] == "lights")["function"]["parameters"]["properties"]
        self.assertEqual(set(params), {"action", "target", "power", "brightness", "color", "kelvin", "scene"})   # nothing but light settings
        self.assertEqual(agent._step_text("lights", {}), "Changing the lights")
        self.assertEqual(audit.describe("lights", {"target": "desk", "power": False}), "desk False")

    def test_main_routes(self):
        from server import main
        with mock.patch.object(lights, "lights", self.reg), mock.patch.object(main.lights_mod, "lights", self.reg):
            view = main.get_lights()
            self.assertEqual(view["lights"][0]["name"], "Desk")
            out = main.command_lights(main.LightCommand(target="desk", brightness=10))
            self.assertTrue(out["ok"])
            self.assertEqual(self.lan.sent[-1][2], {"value": 10})
            with self.assertRaises(main.HTTPException):
                main.command_lights(main.LightCommand(target="garage", power=True))
            self.assertTrue(main.voice_lights(main.SpokenLight(text="lights off"))["handled"])
            self.assertFalse(main.voice_lights(main.SpokenLight(text="what time is it"))["handled"])
            self.assertEqual(main.rename_light(main.LightName(id="id0", name="Lamp"))["lights"][0]["name"], "Lamp")


if __name__ == "__main__":
    unittest.main()
