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
    def test_only_the_permissions_the_features_need(self):
        asked = sorted(re.findall(r'uses-permission android:name="android\.permission\.(\w+)"', MANIFEST))
        self.assertEqual(asked, sorted(["INTERNET", "RECORD_AUDIO", "POST_NOTIFICATIONS", "RECEIVE_BOOT_COMPLETED", "USE_EXACT_ALARM", "SCHEDULE_EXACT_ALARM",
                                        "FOREGROUND_SERVICE", "FOREGROUND_SERVICE_DATA_SYNC"]))

    def test_only_the_boot_receiver_can_be_reached_from_outside(self):
        self.assertRegex(MANIFEST, r'<receiver android:name="\.AlarmReceiver" android:exported="false"')
        self.assertRegex(MANIFEST, r'<receiver android:name="\.BootReceiver" android:exported="true"')
        self.assertRegex(MANIFEST, r'<service android:name="\.AlertService" android:exported="false" android:foregroundServiceType="dataSync"')
        self.assertEqual(MANIFEST.count('android:exported="true"'), 2)                   # the screen and the boot receiver

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
        self.assertIn('giveUp("certificate")', refuse[:400])
        self.assertIn('SETUP + "?offline=1&address="', JAVA[JAVA.index("private void giveUp"):])
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

    def test_reminder_alarms_ring_without_the_app_and_are_set_again_after_a_restart(self):
        reminders = (APP / "java" / "dev" / "jarvis" / "phone" / "Reminders.java").read_text("utf-8")
        self.assertIn("setExactAndAllowWhileIdle", reminders)
        self.assertIn("RTC_WAKEUP", reminders)
        boot = (APP / "java" / "dev" / "jarvis" / "phone" / "BootReceiver.java").read_text("utf-8")
        self.assertIn("scheduleAll", boot)
        self.assertIn("ACTION_BOOT_COMPLETED", boot)
        self.assertIn("scheduleAll(this)", JAVA)                      # also every time the app opens

    def test_the_alert_listener_only_trusts_the_pinned_key(self):
        service = (APP / "java" / "dev" / "jarvis" / "phone" / "AlertService.java").read_text("utf-8")
        pinned = (APP / "java" / "dev" / "jarvis" / "phone" / "Pinned.java").read_text("utf-8")
        self.assertIn("Pinned.open(", service)                          # it uses the one pinned connection, not its own trust rules
        self.assertIn("the PC's key is not the one that was confirmed", pinned)
        self.assertNotIn("TrustManager", service)
        self.assertIn('getBoolean("alerts", false)', service)         # it stops itself when the setting is off

    def test_the_ai_keys_stay_in_the_app(self):
        net = (APP / "java" / "dev" / "jarvis" / "phone" / "Net.java").read_text("utf-8")
        for host in ("generativelanguage.googleapis.com", "api.groq.com", "openrouter.ai"):
            self.assertIn(host, net)
        self.assertIn("!known || !base.startsWith(\"https://\")", net)                  # keys are only accepted for the known AI services
        bridge = JAVA[JAVA.index("private final class Bridge"):]
        names = bridge_methods()
        for leaky in ("getKeys", "keys", "readKeys", "getKey"):
            self.assertNotIn(leaky, names)
        self.assertIn("!onBundledPage()", bridge)                                            # only the PC's own page may hand over keys
        self.assertNotIn('"key"', JAVA)                                                     # the keys are never read out in the activity

    def test_the_assistant_cannot_reach_the_home_network(self):
        net = (APP / "java" / "dev" / "jarvis" / "phone" / "Net.java").read_text("utf-8")
        for needle in ("isSiteLocalAddress", "isLoopbackAddress", "isLinkLocalAddress", 'equals(u.getProtocol())', "setInstanceFollowRedirects(false)"):
            self.assertIn(needle, net)

    def test_the_chat_page_is_bundled_from_the_same_source_as_the_pcs(self):
        gradle = (ROOT / "android" / "app" / "build.gradle.kts").read_text("utf-8")
        self.assertIn('from("../../web/phone")', gradle)
        self.assertIn("LOCAL = \"file:///android_asset/phone/phone.html\"", JAVA)
        self.assertIn("Net.keyCount(this) > 0) web.loadUrl(LOCAL)", JAVA)                 # unreachable PC -> standalone page, when the keys are here

    def test_an_unreachable_pc_never_leaves_a_black_screen(self):
        load = JAVA[JAVA.index("private void load()"):JAVA.index("private boolean ours")]
        self.assertIn("Connecting to your PC", load)                                       # something to read while it checks
        self.assertIn("reach(a, p)", load)                                                 # a quick pinned check before the WebView is sent there
        self.assertIn("setConnectTimeout(4000)", load)
        self.assertIn("it took too long", load)                                            # and a limit on the page itself
        for needle in ("onReceivedHttpError", "onRenderProcessGone", "onPageFinished", "about:blank"):
            self.assertIn(needle, JAVA)

    def test_the_setup_page_and_the_app_agree_on_the_probe(self):
        self.assertIn("window.onProbe&&window.onProbe(", JAVA)
        self.assertIn("window.onProbe = (r)", SETUP)

    def test_the_build_script_and_project_are_complete(self):
        for rel in ("build.bat", "gradlew.bat", "settings.gradle.kts", "build.gradle.kts", "app/build.gradle.kts", "gradle/wrapper/gradle-wrapper.properties"):
            self.assertTrue((ROOT / "android" / rel).exists(), rel)
        self.assertIn("assemble%KIND%", (ROOT / "android" / "build.bat").read_text("utf-8"))


class UpdatesAndWebsite(unittest.TestCase):
    UPDATES = (APP / "java" / "dev" / "jarvis" / "phone" / "Updates.java").read_text("utf-8")
    SITE = (ROOT / "docs" / "index.html").read_text("utf-8")
    GRADLE = (ROOT / "android" / "app" / "build.gradle.kts").read_text("utf-8")

    def test_it_only_asks_the_projects_own_github_releases_over_https(self):
        self.assertIn('API = "https://api.github.com/repos/" + REPO + "/releases/latest"', self.UPDATES)
        self.assertIn('REPO = "ChaosWolfLord/JARVIS"', self.UPDATES)
        self.assertIn('DOWNLOADS = "https://github.com/" + REPO + "/releases/download/"', self.UPDATES)
        self.assertIn("url.startsWith(DOWNLOADS)", self.UPDATES)                         # a file from anywhere else is never offered
        self.assertIn("setInstanceFollowRedirects(false)", self.UPDATES)
        self.assertNotIn("http://", self.UPDATES)
        self.assertNotIn("TrustManager", self.UPDATES)                                    # the phone's normal certificate checks, nothing relaxed

    def test_it_never_installs_by_itself(self):
        for forbidden in ("REQUEST_INSTALL_PACKAGES", "PackageInstaller", "application/vnd.android.package-archive"):
            self.assertNotIn(forbidden, MANIFEST + JAVA + self.UPDATES)
        self.assertIn("Intent.ACTION_VIEW", JAVA)                                          # it opens the download; the person installs it

    def test_the_check_is_throttled_and_can_be_switched_off(self):
        self.assertIn('prefs.getBoolean("updates", true)', JAVA)
        self.assertIn("Updates.EVERY", JAVA)
        for name in ("updatesOn", "setUpdates", "checkUpdates"):
            self.assertIn(name, bridge_methods())
        self.assertIn("app.updatesOn", PHONE_JS)
        page = (ROOT / "web" / "phone" / "phone.html").read_text("utf-8")
        for ident in ("opt-upd", "upd-now", "upd-ver", "set-app"):
            self.assertIn(f'id="{ident}"', page)

    def test_the_version_comparison_is_numeric(self):
        # mirrors Updates.compare: "1.10" is newer than "1.9", "1.2.3" equals "1.2.3.0"
        def compare(a, b):
            x, y = [int(n) for n in a.split(".")], [int(n) for n in b.split(".")]
            for i in range(max(len(x), len(y))):
                p, q = x[i] if i < len(x) else 0, y[i] if i < len(y) else 0
                if p != q:
                    return (p > q) - (p < q)
            return 0
        self.assertEqual(compare("1.10", "1.9"), 1)
        self.assertEqual(compare("1.2.3", "1.2.3.0"), 0)
        self.assertEqual(compare("1.2.2", "1.2.3"), -1)
        self.assertIn("Integer.compare(p, q)", self.UPDATES)

    def test_a_release_has_notes_and_the_website_points_at_the_same_file(self):
        version = re.search(r'versionName = "([^"]+)"', self.GRADLE).group(1)
        self.assertTrue((ROOT / "android" / "release-notes" / f"{version}.md").exists(), "write android/release-notes/<version>.md")
        self.assertIn("releases/latest/download/jarvis.apk", self.SITE)
        self.assertIn("ChaosWolfLord/JARVIS", self.SITE)
        script = (ROOT / "android" / "release.ps1").read_text("utf-8")
        self.assertIn("jarvis.apk", script)                                                  # the name the links and the update check rely on
        self.assertIn("jarvis.apk", self.UPDATES)

    def test_back_leaves_the_app_instead_of_walking_the_page_history(self):
        back = JAVA[JAVA.index("public void onBackPressed()"):]
        back = back[:back.index("}") + 1]
        self.assertIn("moveTaskToBack(true)", back)
        self.assertNotIn("goBack", JAVA)          # the history after setup still holds the setup page: going back would look like being logged out

    def test_the_website_is_self_contained(self):
        self.assertNotRegex(self.SITE, r'(src|href)="https?://(?!github\.com/ChaosWolfLord/JARVIS)')   # no outside scripts, fonts or trackers
        self.assertTrue((ROOT / "docs" / ".nojekyll").exists())


if __name__ == "__main__":
    unittest.main()
