"""Checks on the Android app's source (it is built by android/build.bat, which these tests do not run): what it is allowed to do, that the
pages and the app agree on the functions between them, and that the one place it accepts the PC's own certificate is guarded by the pin."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "android" / "app" / "src" / "main"
JAVA = (APP / "java" / "dev" / "jarvis" / "phone" / "MainActivity.java").read_text("utf-8")
MANIFEST = (APP / "AndroidManifest.xml").read_text("utf-8")
SETUP = (APP / "assets" / "setup.html").read_text("utf-8")
PHONE_JS = (ROOT / "web" / "phone" / "phone.js").read_text("utf-8")


def bridge_methods() -> set[str]:
    """Every method the pages can call: the ones marked @JavascriptInterface."""
    return set(re.findall(r"@JavascriptInterface\s+public\s+\w+\s+(\w+)\(", JAVA))


class Permissions(unittest.TestCase):
    def test_only_the_internet_and_the_microphone(self):
        self.assertEqual(sorted(re.findall(r'uses-permission android:name="android\.permission\.(\w+)"', MANIFEST)), ["INTERNET", "RECORD_AUDIO"])

    def test_no_plain_http_and_no_backup_of_the_pairing(self):
        self.assertIn('usesCleartextTraffic="false"', MANIFEST)
        self.assertIn('allowBackup="false"', MANIFEST)

    def test_old_phones_that_cannot_check_the_pin_are_not_supported(self):
        self.assertRegex((ROOT / "android" / "app" / "build.gradle.kts").read_text("utf-8"), r"minSdk = 29")


class Pinning(unittest.TestCase):
    def test_the_certificate_is_only_accepted_when_it_matches_the_pin(self):
        self.assertEqual(JAVA.count("handler.proceed()"), 1, "there must be exactly one place that accepts a certificate")
        before = JAVA[:JAVA.index("handler.proceed()")]
        self.assertIn("pin().equals(spkiHex(x))", before[-400:])
        self.assertIn("ours(error.getUrl())", before[-400:])

    def test_nothing_but_the_pc_and_the_setup_page_is_ever_shown(self):
        self.assertIn("return !ours(request.getUrl().toString());", JAVA)
        self.assertIn("setAllowUniversalAccessFromFileURLs(false)", JAVA)
        self.assertIn("request.deny()", JAVA)                              # the page never gets the microphone itself

    def test_a_refused_certificate_leaves_a_way_out_not_a_blank_screen(self):
        refuse = JAVA[JAVA.index("handler.cancel();"):]
        self.assertIn("why=certificate", refuse[:400])
        self.assertIn("why === 'certificate'", SETUP)

    def test_the_bridge_checks_where_it_is_called_from(self):
        bridge = JAVA[JAVA.index("private final class Bridge"):]
        for name in bridge_methods() - {"version"}:
            body = bridge[bridge.index(f" {name}("):]
            self.assertIn("ok()", body[:350], f"{name} does not check that the page is one of ours")


class Contract(unittest.TestCase):
    def test_every_function_the_pages_call_exists_in_the_app(self):
        have = bridge_methods()
        called = set(re.findall(r"\bapp\??\.(\w+)\(", PHONE_JS)) | set(re.findall(r"\bapp\.(\w+)\(", SETUP))
        called |= set(re.findall(r"window\.JarvisApp\.(\w+)\(", PHONE_JS))
        self.assertTrue(called, "found no calls to check")
        self.assertEqual(sorted(called - have), [], "the pages call something the app does not have")

    def test_the_app_reports_speech_the_way_the_page_listens(self):
        self.assertIn("window.__speech&&window.__speech(", JAVA)
        self.assertIn("window.__speech = (type, text)", PHONE_JS)
        for kind in ("start", "partial", "final", "error", "end"):
            self.assertIn(f"'{kind}'", PHONE_JS)

    def test_the_setup_page_and_the_app_agree_on_the_probe(self):
        self.assertIn("window.onProbe&&window.onProbe(", JAVA)
        self.assertIn("window.onProbe = (r)", SETUP)

    def test_the_build_script_and_project_are_complete(self):
        for rel in ("build.bat", "gradlew.bat", "settings.gradle.kts", "build.gradle.kts", "app/build.gradle.kts", "gradle/wrapper/gradle-wrapper.properties"):
            self.assertTrue((ROOT / "android" / rel).exists(), rel)
        self.assertIn("assemble%KIND%", (ROOT / "android" / "build.bat").read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
