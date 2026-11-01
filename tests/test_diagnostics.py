import json
import unittest
from unittest import mock

from server import agent, diagnostics


def base(**over):
    latest = {"cpu": 10.0, "mem": {"pct": 40.0, "used_gb": 8, "total_gb": 16}, "uptime_h": 5,
              "disks": [{"drive": "C:", "free_gb": 300, "total_gb": 900, "free_pct": 33, "system": True}],
              "net": {"internet": True, "ms": 30, "dns": True, "wifi": {"ssid": "home", "signal": 80}}, "net_failures": 0,
              "slow": {"disk_health": [{"name": "SSD", "health": "Healthy", "status": "OK"}], "defender": {"realtime": True, "sig_age_days": 0},
                       "firewall": [{"name": "Public", "enabled": True}], "errors_24h": {"count": 0, "top": []}},
              "jarvis": {"wake_configured": False}}
    latest.update(over)
    return latest


def points(key, value, count, now=1000.0, gap=10.0):
    return [{"t": now - i * gap, "cpu": 5.0, "mem": 40.0, key: value} for i in range(count)]


class Rules(unittest.TestCase):
    def test_healthy_pc_has_no_alerts(self):
        self.assertEqual(diagnostics.evaluate(base(), [], 1000.0), {})

    def test_low_disk_by_percent_and_by_gigabytes(self):
        low = base(disks=[{"drive": "C:", "free_gb": 40, "total_gb": 900, "free_pct": 4, "system": True}])
        self.assertIn("disk-low-C:", diagnostics.evaluate(low, [], 1000.0))
        tiny = base(disks=[{"drive": "D:", "free_gb": 5, "total_gb": 60, "free_pct": 50, "system": False}])
        self.assertIn("disk-low-D:", diagnostics.evaluate(tiny, [], 1000.0))

    def test_memory_needs_to_stay_high_for_three_minutes(self):
        self.assertNotIn("memory-high", diagnostics.evaluate(base(), points("mem", 97, 4), 1000.0))     # a brief spike
        sustained = points("mem", 97, 20)
        self.assertIn("memory-high", diagnostics.evaluate(base(), sustained, 1000.0))
        dipped = sustained[:5] + [{"t": 1000.0 - 60, "cpu": 5, "mem": 50}] + sustained[5:]
        self.assertNotIn("memory-high", diagnostics.evaluate(base(), dipped, 1000.0))

    def test_cpu_needs_five_minutes(self):
        self.assertNotIn("cpu-high", diagnostics.evaluate(base(), points("cpu", 99, 10), 1000.0))
        self.assertIn("cpu-high", diagnostics.evaluate(base(), points("cpu", 99, 31), 1000.0))

    def test_internet_down_needs_two_failures(self):
        down = base(net={"internet": False, "ms": None, "dns": False, "wifi": None})
        self.assertNotIn("internet-down", diagnostics.evaluate({**down, "net_failures": 1}, [], 0))
        out = diagnostics.evaluate({**down, "net_failures": 2}, [], 0)
        self.assertEqual(out["internet-down"]["level"], "critical")

    def test_dns_and_weak_wifi(self):
        self.assertIn("dns-broken", diagnostics.evaluate(base(net={"internet": True, "ms": 9, "dns": False, "wifi": None}), [], 0))
        self.assertIn("wifi-weak", diagnostics.evaluate(base(net={"internet": True, "ms": 9, "dns": True, "wifi": {"ssid": "x", "signal": 10}}), [], 0))

    def test_security_and_drive_health(self):
        slow = {"disk_health": [{"name": "Disk1", "health": "Warning"}], "defender": {"realtime": False}, "firewall": [{"name": "Public", "enabled": False}]}
        out = diagnostics.evaluate(base(slow=slow), [], 0)
        self.assertEqual({"disk-health-Disk1", "defender-off", "firewall-off"}, set(out))

    def test_jarvis_problems(self):
        j = {"wake_configured": True, "wake_running": False, "wake_error": "no microphone", "tracker_expected": True, "tracker_connected": False,
             "mcp_errors": [{"name": "files", "error": "boom"}], "log_errors": 12}
        out = diagnostics.evaluate(base(jarvis=j), [], 0)
        self.assertEqual({"wake-down", "tracker-down", "mcp-files", "jarvis-errors"}, set(out))
        self.assertIn("no microphone", out["wake-down"]["text"])

    def test_wake_word_not_configured_is_not_a_problem(self):
        self.assertEqual(diagnostics.evaluate(base(jarvis={"wake_configured": False, "wake_running": False}), [], 0), {})

    def test_thresholds_come_from_env(self):
        d = base(disks=[{"drive": "C:", "free_gb": 100, "total_gb": 900, "free_pct": 11, "system": True}])
        self.assertEqual(diagnostics.evaluate(d, [], 0), {})
        with mock.patch.dict("os.environ", {"JARVIS_ALERT_DISK_FREE_PCT": "20"}):
            self.assertIn("disk-low-C:", diagnostics.evaluate(d, [], 0))

    def test_every_alert_can_be_spoken(self):
        slow = {"disk_health": [{"name": "D", "health": "Unhealthy"}], "defender": {"realtime": False}, "firewall": [{"name": "Public", "enabled": False}]}
        for a in diagnostics.evaluate(base(slow=slow, net_failures=3, net={"internet": False}), [], 0).values():
            self.assertTrue(a["speak"] and a["title"] and a["id"] and a["level"] in ("warn", "critical"))


class Meters(unittest.TestCase):
    def test_cpu_percent_from_counters(self):
        reads = iter([(0, 0, 0), (50, 100, 0), (50, 100, 0)])        # idle is counted inside kernel time
        meter = diagnostics.CpuMeter(read=lambda: next(reads))
        self.assertEqual(meter.percent(), 50.0)
        self.assertEqual(meter.percent(), 0.0)                       # no time passed: no division by zero

    def test_real_readings_are_sane(self):
        m = diagnostics.memory()
        self.assertTrue(0 <= m["pct"] <= 100 and m["total_gb"] > 0)
        for d in diagnostics.disks():
            self.assertTrue(d["total_gb"] > 0 and 0 <= d["free_pct"] <= 100)

    def test_network_falls_back_and_reports_failure(self):
        def refuse(*a, **k):
            raise OSError("no route")
        out = diagnostics.network(connect=refuse, resolve=refuse, wifi=lambda: None)
        self.assertEqual((out["internet"], out["dns"], out["ms"]), (False, False, None))
        ok = mock.Mock()
        out = diagnostics.network(connect=lambda *a, **k: ok, resolve=lambda *a: [], wifi=lambda: {"ssid": "x", "signal": 70})
        self.assertTrue(out["internet"] and out["dns"])

    def test_wifi_parsing(self):
        text = "    Name : Wi-Fi\n    SSID                   : shah\n    BSSID : aa\n    Signal                 : 86%\n"
        self.assertEqual(diagnostics.wifi_info(run=lambda: text), {"ssid": "shah", "signal": 86})
        self.assertIsNone(diagnostics.wifi_info(run=lambda: "There is no wireless interface on the system."))

    def test_powershell_json_survives_junk(self):
        self.assertEqual(diagnostics.powershell_json("x", run=lambda s: "warning\n{\"a\": 1}\n"), {"a": 1})
        self.assertIsNone(diagnostics.powershell_json("x", run=lambda s: "not json"))
        self.assertIsNone(diagnostics.powershell_json("x", run=lambda s: ""))


class FakeCpu:
    def __init__(self):
        self.value = 10.0

    def percent(self):
        return self.value


class MonitorTests(unittest.TestCase):
    def make(self, **kw):
        self.events = []
        self.state = {"net": {"internet": True, "ms": 5, "dns": True, "wifi": None}, "free": 300, "jarvis": {}}
        return diagnostics.Monitor(
            jarvis_probe=lambda: self.state["jarvis"], notify=self.events.append, cpu_meter=FakeCpu(),
            fast=lambda: {"pct": 40.0, "used_gb": 6, "total_gb": 16}, slow=lambda: {},
            nets=lambda: self.state["net"],
            disk_fn=lambda: [{"drive": "C:", "free_gb": self.state["free"], "total_gb": 900, "free_pct": self.state["free"] / 9, "system": True}], **kw)

    def test_new_alert_is_announced_once_and_resolution_too(self):
        m = self.make()
        m.step(0)
        self.assertEqual(self.events, [])
        self.state["free"] = 20
        m.step(100)                                  # disks are re-read every minute, the rules every 30 s
        m.step(140)
        new = [e for e in self.events if e["state"] == "new"]
        self.assertEqual([e["id"] for e in new], ["disk-low-C:"])
        m.step(200)
        self.assertEqual(len([e for e in self.events if e["state"] == "new"]), 1)      # no repeat while it persists
        self.state["free"] = 400
        m.step(260)
        m.step(300)
        gone = [e for e in self.events if e["state"] == "resolved"]
        self.assertEqual([e["id"] for e in gone], ["disk-low-C:"])
        self.assertEqual(m.active_alerts(), [])

    def test_one_failed_internet_check_is_ignored_two_alert(self):
        m = self.make()
        m.step(0)
        self.state["net"] = {"internet": False, "ms": None, "dns": False, "wifi": None}
        m.step(40)
        self.assertEqual(m.active_alerts(), [])
        m.step(80)
        self.assertEqual([a["id"] for a in m.active_alerts()], ["internet-down"])
        self.state["net"] = {"internet": True, "ms": 5, "dns": True, "wifi": None}
        m.step(120)
        self.assertEqual(m.active_alerts(), [])

    def test_alerts_can_be_switched_off(self):
        m = self.make()
        self.state["free"] = 5
        with mock.patch.dict("os.environ", {"JARVIS_ALERTS": "0"}):
            m.step(0)
            m.step(100)
        self.assertEqual(self.events, [])

    def test_snapshot_is_json_and_history_is_trimmed(self):
        m = self.make()
        for i in range(0, 200, 5):
            m.step(float(i))
        snap = m.snapshot()
        json.dumps(snap)
        self.assertTrue(0 < len(snap["history"]) <= 360)
        self.assertEqual(snap["mem"]["pct"], 40.0)

    def test_a_failing_probe_does_not_stop_the_monitor_thread(self):
        m = self.make()
        def broken():
            m.stop_flag.set()                          # so the loop ends after this one pass
            raise RuntimeError("x")
        m.jarvis_probe = broken
        with self.assertLogs("jarvis", "ERROR"):
            m._run()


class Text(unittest.TestCase):
    def snap(self, **over):
        return {"cpu": 12.0, "mem": {"pct": 50, "used_gb": 8, "total_gb": 16}, "disks": [{"drive": "C:", "free_gb": 200, "free_pct": 30, "total_gb": 600, "system": True}],
                "net": {"internet": True, "ms": 20}, "alerts": [], "uptime_h": 30, "jarvis": {"wake_configured": True, "wake_running": True, "free_requests": 40}, **over}

    def test_summary_healthy_and_with_alerts(self):
        text = diagnostics.summary(self.snap())
        self.assertIn("healthy", text)
        self.assertIn("40 free requests", text)
        bad = diagnostics.summary(self.snap(alerts=[{"title": "No internet"}, {"title": "Drive C: is almost full"}]))
        self.assertIn("2 problems", bad)
        self.assertIn("No internet", bad)

    def test_summary_before_first_measurement(self):
        self.assertIn("first measurements", diagnostics.summary({}))

    def test_details_areas(self):
        s = self.snap(slow={"defender": {"realtime": False, "sig_age_days": 3}, "firewall": [{"name": "Public", "enabled": True}],
                            "errors_24h": {"count": 2, "top": [{"provider": "X", "count": 2}]}})
        self.assertIn("OFF", diagnostics.details("security", s))
        self.assertIn("2 serious errors", diagnostics.details("errors", s))
        self.assertIn("200 GB free", diagnostics.details("disks", s))
        self.assertIn("Areas:", diagnostics.details("nonsense", s))
        procs = {"by_memory": [{"name": "app", "id": 77, "mb": 900}], "by_cpu": [{"name": "app", "id": 77, "cpu": 12.5}]}
        text = diagnostics.details("processes", s, run=lambda script: json.dumps(procs))
        self.assertIn("app (id 77) 900 MB", text)


class AgentTools(unittest.TestCase):
    def test_tools_are_offered_and_read_only(self):
        names = {t["function"]["name"] for t in agent.active_tools()}
        self.assertTrue({"system_status", "system_details"} <= names)
        self.assertTrue({"system_status", "system_details"} <= agent.FOLLOW_UP_TOOLS)
        self.assertFalse({"system_status", "system_details"} & agent.ACTION_TOOLS)

    def test_tools_read_the_running_monitor(self):
        monitor = mock.Mock(snapshot=lambda: Text().snap())
        with mock.patch.object(diagnostics, "current", monitor):
            self.assertIn("healthy", agent._run_lookup("system_status", {}))
            self.assertIn("200 GB free", agent._run_lookup("system_details", {"area": "disks"}))
        self.assertTrue(agent._step_text("system_details", {"area": "disks"}).startswith("Looking closer"))

    def test_tools_work_before_the_monitor_exists(self):
        with mock.patch.object(diagnostics, "current", None):
            self.assertIn("first measurements", agent._run_lookup("system_status", {}))


class Routes(unittest.TestCase):
    def test_server_wires_the_monitor_in(self):
        from server import main
        self.assertIs(diagnostics.current, main.monitor)
        health = main.jarvis_health()
        self.assertTrue({"wake_configured", "wake_running", "tracker_expected", "mcp_errors", "log_errors", "free_requests"} <= set(health))
        json.dumps(health)
        self.assertIn("text", main.system_summary())
        self.assertIn("Areas:", main.system_area("nothing")["text"])
        self.assertEqual(main.status()["alerts"], len(main.monitor.active_alerts()))


if __name__ == "__main__":
    unittest.main()
