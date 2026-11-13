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
                                        "FOREGROUND_SERVICE", "FOREGROUND_SERVICE_DATA_SYNC", "USE_FULL_SCREEN_INTENT", "VIBRATE",
                                        "FOREGROUND_SERVICE_MEDIA_PLAYBACK", "SYSTEM_ALERT_WINDOW", "MODIFY_AUDIO_SETTINGS"]))

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


PHONE = APP / "java" / "dev" / "jarvis" / "phone"


class ReminderCalls(unittest.TestCase):
    """"JARVIS calls you": a reminder rings like a call, but never overrides silent mode or Do Not Disturb."""

    @classmethod
    def setUpClass(cls):
        cls.sources = {p.name: p.read_text("utf-8") for p in PHONE.glob("*.java")}
        cls.all = chr(10).join(cls.sources.values())

    def test_nothing_bypasses_silent_mode_or_do_not_disturb(self):
        for banned in ("setBypassDnd", "STREAM_RING", "setRingerMode", "setInterruptionFilter", "ACCESS_NOTIFICATION_POLICY", "setStreamMute", "adjustVolume",
                       "adjustStreamVolume", "setMicrophoneMute"):
            self.assertNotIn(banned, self.all, banned)
        for name, source in self.sources.items():                         # the alarm sound and a raised volume belong to "find my phone" alone, behind its own switch
            if name != "FindService.java":
                for banned in ("USAGE_ALARM", "STREAM_ALARM", "setStreamVolume"):
                    self.assertNotIn(banned, source, f"{name}: {banned}")
        self.assertNotIn("ACCESS_NOTIFICATION_POLICY", MANIFEST)

    def test_an_answered_call_has_a_speaker_button_and_gives_the_audio_back(self):
        call = self.sources["CallActivity.java"]
        for name in ("setMode(AudioManager.MODE_IN_COMMUNICATION)", "setCommunicationDevice(", "setSpeakerphoneOn(", "clearCommunicationDevice()", "setMode(oldMode)"):
            self.assertIn(name, call, name)
        self.assertIn("USAGE_VOICE_COMMUNICATION", call)
        self.assertIn("speakerBtn.setOnClickListener", call)
        for other in ("CallService.java", "Notify.java", "Reminders.java", "AlarmReceiver.java"):                 # the ringing side never touches call audio
            for name in ("setMode(", "setCommunicationDevice", "setSpeakerphoneOn"):
                self.assertNotIn(name, self.sources[other], f"{other}: {name}")
        self.assertIn("RINGER_MODE_NORMAL", call)                          # the first time: the speaker only when the ringer is on
        self.assertIn("endCallAudio();", call[call.index("private void hangUp()"):call.index("protected void onDestroy()")])
        self.assertIn("endCallAudio();", call[call.index("protected void onDestroy()"):])

    def test_the_call_screen_shows_jarvis_s_orb_and_it_follows_the_call(self):
        call, orb = self.sources["CallActivity.java"], self.sources["OrbView.java"]
        self.assertIn("new OrbView(this)", call)
        for state in ("SPEAKING", "LISTENING", "THINKING", "IDLE"):
            self.assertIn(f"OrbView.{state}", call)
        self.assertIn("orb.hear(", call)                                    # it moves with your voice while it listens
        self.assertIn("postInvalidateDelayed(", orb)                        # a frame rate cap, not every screen refresh
        self.assertNotIn("new android.graphics.RadialGradient", orb[orb.index("long gap"):orb.index("if (glowFor != s)")])

    def test_find_my_phone_follows_silent_mode_unless_its_own_switch_is_on(self):
        find = self.sources["FindService.java"]
        self.assertIn('getBoolean("find_loud", false)', find)               # off unless the person turns it on
        ring = find[find.index("private void ring(boolean loud)"):find.index("private void play(")]
        loud_branch, quiet_branch = ring[ring.index("if (loud) {"):ring.index("} else {")], ring[ring.index("} else {"):]
        self.assertIn("USAGE_ALARM", loud_branch)
        self.assertIn("setStreamVolume", loud_branch)
        for name in ("USAGE_ALARM", "setStreamVolume"):
            self.assertNotIn(name, quiet_branch)
        self.assertIn("CallService.mayRing(this)", quiet_branch)           # the same check as a reminder call
        self.assertIn("CallService.mayBuzz(this)", quiet_branch)
        self.assertIn("alarmVolumeWas", find[find.index("private void release()"):])        # the raised volume is put back
        self.assertIn("RING_MS = 120_000", find)
        self.assertNotIn("find_loud", PHONE_JS.replace("setFindLoud", ""))   # the page cannot turn it on by itself
        self.assertRegex(MANIFEST, r'<service android:name="\.FindService" android:exported="false" android:foregroundServiceType="mediaPlayback"')
        for name in ("startFinding", "stopFinding", "findLoud", "setFindLoud"):
            self.assertIn(name, bridge_methods())

    def test_the_ringtone_only_plays_when_the_phone_allows_a_call_to_ring(self):
        service, notify = self.sources["CallService.java"], self.sources["Notify.java"]
        self.assertIn("RINGER_MODE_NORMAL", service)
        self.assertIn("INTERRUPTION_FILTER_ALL", service)
        self.assertIn("RINGER_MODE_SILENT", service)                       # silent mode: no buzz either
        ring = service[service.index("private void ring()"):]
        self.assertLess(ring.index("if (mayRing(this))"), ring.index("ringtone.play()"))      # nothing plays before the check
        self.assertLess(ring.index("if (mayBuzz(this))"), ring.index("vibrator.vibrate("))
        self.assertEqual(service.count("ringtone.play()"), 1)
        self.assertEqual(service.count("vibrator.vibrate("), 1)
        self.assertIn("USAGE_NOTIFICATION_RINGTONE", service)
        self.assertIn("setSound(null, null)", notify)                      # the notification itself is silent; the service rings
        self.assertIn("CATEGORY_REMINDER", notify[notify.index("static Notification callNotification("):])
        self.assertNotIn("CATEGORY_CALL", notify)                         # Do Not Disturb lets calls through; this is a reminder
        self.assertIn("setTimeoutAfter(CALL_RINGS_MS)", notify)
        self.assertIn("CALL_RINGS_MS", service)                            # and it hangs up by itself
        for name in ("Ringtone", "MediaPlayer", "Vibrator"):
            self.assertNotIn(name, self.sources["CallActivity.java"])      # the call screen makes no sound of its own
        self.assertRegex(MANIFEST, r'<service android:name="\.CallService" android:exported="false" android:foregroundServiceType="mediaPlayback"')

    def test_a_reminder_rings_as_a_call_only_when_switched_on_and_on_time(self):
        ring = self.sources["Reminders.java"]
        self.assertIn("Notify.callsOn(c) && late <= 120_000", ring)
        self.assertIn("else Notify.reminder(", ring)
        self.assertIn('getBoolean("calls", true)', self.sources["Notify.java"])

    def test_the_call_screen_is_private_and_works_over_the_lock_screen(self):
        self.assertRegex(MANIFEST, r'<activity\s+android:name="\.CallActivity"\s+android:exported="false"')
        self.assertIn('android:showWhenLocked="true"', MANIFEST)
        self.assertIn("setFullScreenIntent(", self.sources["Notify.java"])

    def test_the_page_can_switch_it_on_and_off(self):
        for name in ("callsOn", "setCallsOn", "callScreenAllowed", "allowCallScreen", "overlayAllowed", "allowOverlay"):
            self.assertIn(name, bridge_methods())
        self.assertIn("setCallsOn(", PHONE_JS)
        self.assertIn('id="opt-call"', (ROOT / "web" / "phone" / "phone.html").read_text("utf-8"))

    def test_what_you_say_back_is_understood(self):
        call = self.sources["CallActivity.java"]
        self.assertIn("static int minutesIn(", call)
        self.assertIn("static boolean isSnooze(", call)
        self.assertIn("static boolean isThanks(", call)


class ShareAndSavings(unittest.TestCase):
    """"Share to JARVIS", and the things that keep the app light on battery and data."""

    @classmethod
    def setUpClass(cls):
        cls.src = {p.name: p.read_text("utf-8") for p in PHONE.glob("*.java")}

    def test_other_apps_can_share_text_and_pictures_to_the_app_and_nothing_else(self):
        self.assertEqual(len(re.findall(r'<action android:name="android\.intent\.action\.SEND" />', MANIFEST)), 2)
        self.assertIn('android:mimeType="text/plain"', MANIFEST)
        self.assertIn('android:mimeType="image/*"', MANIFEST)
        self.assertNotIn("SEND_MULTIPLE", MANIFEST)
        self.assertNotIn("READ_EXTERNAL_STORAGE", MANIFEST)                # the shared picture is read through the grant the other app gives

    def test_a_shared_picture_is_only_read_from_a_content_address_shrunk_and_cleaned(self):
        share = self.src["Share.java"]
        self.assertIn("SCHEME_CONTENT.equals(uri.getScheme())", share)      # never a file path on the phone
        self.assertIn("MAX_SIDE = 1920", share)
        self.assertIn("CompressFormat.JPEG", share)                       # saved again, which drops the location and camera details
        self.assertIn("MAX_TEXT = 4000", share)

    def test_nothing_shared_is_sent_without_a_tap(self):
        js = PHONE_JS
        self.assertIn("window.__shareReady", js)
        for call in ("shareToPc('wall')", "shareToPc('note')", "shareToPc('open')"):
            self.assertIn(call, js)
        for line in js.splitlines():                                      # the only places that send what was shared are button handlers
            if "shareToPc(" in line and "function" not in line:
                self.assertIn("addEventListener('click'", line)

    def test_the_page_and_the_app_agree_about_sharing(self):
        for name in ("takeShare", "sharedImage", "discardShare"):
            self.assertIn(name, bridge_methods())
            self.assertIn(name, PHONE_JS)

    def test_the_look_button_uses_the_camera_app_and_leaves_nothing_behind(self):
        self.assertIn("takePhoto", bridge_methods())
        self.assertIn("takePhoto", PHONE_JS)
        manifest = (ROOT / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn("android.media.action.IMAGE_CAPTURE", manifest)
        self.assertNotIn("android.permission.CAMERA", manifest)           # the camera app takes the picture; JARVIS never holds the camera
        share = self.src["Share.java"]
        self.assertIn("static void fromCamera", share)
        self.assertIn("getContentResolver().delete(uri", share)             # the gallery copy is deleted straight away

    def test_checking_for_updates_costs_no_data_when_nothing_changed(self):
        updates = self.src["Updates.java"]
        self.assertIn("If-None-Match", updates)
        self.assertIn("code == 304", updates)
        self.assertIn('"upd_etag"', updates)

    def test_the_alert_listener_backs_off_when_the_pc_is_out_of_reach(self):
        alerts = self.src["AlertService.java"]
        self.assertIn("RETRY_MAX_MS = 5 * 60_000", alerts)
        self.assertIn("nap.notifyAll()", alerts)                          # opening the app tries again at once

    def test_the_orbs_are_not_redrawn_on_every_screen_refresh(self):
        for path in (ROOT / "web" / "orb.js", ROOT / "web" / "phone" / "orb.js"):
            text = path.read_text("utf-8")
            self.assertIn("FRAME_IDLE_MS", text, path.name)
            self.assertIn("FRAME_ACTIVE_MS", text, path.name)
            self.assertIn("document.hidden", text, path.name)


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
