package dev.jarvis.phone;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.net.Uri;
import android.net.http.SslCertificate;
import android.net.http.SslError;
import android.os.Bundle;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

import java.net.URL;
import java.security.MessageDigest;
import java.security.cert.X509Certificate;
import java.lang.ref.WeakReference;
import java.util.ArrayList;
import java.util.regex.Pattern;

import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/**
 * The JARVIS app: a full-screen WebView on the phone page that the PC serves over the home Wi-Fi, plus the few things a web page cannot do
 * by itself: it trusts the PC's own certificate (by its pinned public key, never by switching checks off), keeps the pairing token,
 * and uses the phone's speech recognition. Nothing else is ever loaded: other addresses are refused.
 */
public class MainActivity extends Activity {
    static final String SETUP = "file:///android_asset/setup.html";
    static final String LOCAL = "file:///android_asset/phone/phone.html";      // the same chat page, bundled in the app, for use without the PC
    private final java.util.concurrent.ExecutorService network = java.util.concurrent.Executors.newFixedThreadPool(3);
    static final int MIC_REQUEST = 7;
    static final Pattern ADDRESS = Pattern.compile("^[A-Za-z0-9.\\-]{1,100}(:\\d{1,5})?$");
    static final Pattern HEX64 = Pattern.compile("^[0-9a-f]{64}$");

    private SharedPreferences prefs;
    private WebView web;
    private volatile boolean trustedPage = false;       // is the page on screen one of ours (the setup page or the pinned PC)?
    private SpeechRecognizer recognizer;
    private String pendingLanguage;
    private static WeakReference<MainActivity> visible = new WeakReference<>(null);   // the activity on screen, if any (alarms hand it the reminder to show too)

    static final int NOTIFY_REQUEST = 8;
    private volatile boolean chatInProgress = false;        // set by the standalone page while it is talking, so reopening the app does not interrupt it

    /** An alert or a ringing reminder, for the page to show too when the app is open. */
    static void deliver(String eventJson) {
        final MainActivity a = visible.get();
        if (a == null) return;
        final String js = "window.__alert&&window.__alert(" + eventJson + ")";
        a.runOnUiThread(() -> a.web.evaluateJavascript(js, null));
    }

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("jarvis", MODE_PRIVATE);
        if ((getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0) WebView.setWebContentsDebuggingEnabled(true);   // debug builds only: lets the PC inspect the page
        web = new WebView(this);
        web.setBackgroundColor(0xFF080A10);
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccessFromFileURLs(false);
        s.setAllowUniversalAccessFromFileURLs(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setSupportMultipleWindows(false);

        web.addJavascriptInterface(new Bridge(), "JarvisApp");
        web.setWebViewClient(new Client());
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                request.deny();                         // the page never gets the microphone itself: speech goes through the bridge
            }
        });
        if (state != null) web.restoreState(state); else load();
        if (prefs.getBoolean("alerts", false) && !prefs.getString("token", "").isEmpty()) AlertService.start(this);
        Reminders.scheduleAll(this);                    // alarms are set again every time the app opens (cheap, and heals anything lost)
    }

    @Override
    protected void onResume() {
        super.onResume();
        visible = new WeakReference<>(this);
        String shown = web.getUrl();
        if (shown != null && !address().isEmpty() && ((shown.startsWith(SETUP) && shown.contains("offline=1")) || shown.startsWith(LOCAL)) && !chatInProgress) load();      // coming back to the app: try the PC again
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (visible.get() == this) visible = new WeakReference<>(null);
        stopRecognizer();
    }

    @Override
    protected void onDestroy() {
        stopRecognizer();
        web.destroy();
        super.onDestroy();
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }

    // ---- what to show -----------------------------------------------------------------------------------------------
    private String address() { return prefs.getString("address", ""); }

    private volatile boolean bundled = false;                // is the page on screen one that came inside the app (not the PC's page)?

    private boolean onBundledPage() { return bundled; }

    private void emitNet(String id, String json) {
        final String js = "window.__net&&window.__net(" + JSONObject.quote(id) + "," + JSONObject.quote(json) + ")";
        runOnUiThread(() -> web.evaluateJavascript(js, null));
    }

    private String pin() { return prefs.getString("pin", ""); }

    private void load() {
        if (!address().isEmpty() && !pin().isEmpty()) web.loadUrl("https://" + address() + "/");
        else web.loadUrl(SETUP);
    }

    private boolean ours(String url) {
        if (url == null) return false;
        if (url.equals(SETUP) || url.startsWith(SETUP + "?") || url.equals(LOCAL) || url.startsWith(LOCAL + "?")) return true;
        Uri u = Uri.parse(url);
        String a = address();
        if (a.isEmpty() || !"https".equals(u.getScheme())) return false;
        String hostPort = u.getPort() > 0 ? u.getHost() + ":" + u.getPort() : u.getHost();
        return hostPort != null && (hostPort.equals(a) || (u.getPort() <= 0 && (a.equals(u.getHost() + ":443"))));
    }

    private static String spkiHex(X509Certificate cert) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(cert.getPublicKey().getEncoded());
        StringBuilder sb = new StringBuilder();
        for (byte b : digest) sb.append(String.format("%02x", b));
        return sb.toString();
    }

    private final class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            return !ours(request.getUrl().toString());          // anything else is refused (true = handled: nothing loads)
        }

        @Override
        public void onPageStarted(WebView view, String url, Bitmap favicon) {
            trustedPage = ours(url);
            bundled = url != null && url.startsWith("file:");
        }

        @Override
        public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
            try {
                SslCertificate sc = error.getCertificate();
                X509Certificate x = sc == null ? null : sc.getX509Certificate();
                if (x != null && !pin().isEmpty() && ours(error.getUrl()) && pin().equals(spkiHex(x))) {
                    handler.proceed();                          // the very key that was confirmed when the app was set up
                    return;
                }
            } catch (Exception ignored) {
                // fall through to refusing
            }
            handler.cancel();
            // never leave a blank screen: say why, and offer "Change PC"
            runOnUiThread(() -> web.loadUrl(SETUP + "?offline=1&address=" + Uri.encode(address()) + "&why=certificate"));
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame() && !request.getUrl().toString().startsWith("file:")) {
                String why = error.getDescription() == null ? "" : error.getDescription().toString();
                if (Net.keyCount(MainActivity.this) > 0) web.loadUrl(LOCAL);      // away from home or the PC is off: the standalone assistant
                else web.loadUrl(SETUP + "?offline=1&address=" + Uri.encode(address()) + "&why=" + Uri.encode(why));
            }
        }
    }

    // ---- speech -----------------------------------------------------------------------------------------------------
    private void emit(String type, String text) {
        final String js = "window.__speech&&window.__speech(" + JSONObject.quote(type) + "," + JSONObject.quote(text == null ? "" : text) + ")";
        runOnUiThread(() -> web.evaluateJavascript(js, null));
    }

    private void startRecognizer(String language) {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            emit("error", "service-not-allowed");
            return;
        }
        stopRecognizer();
        recognizer = SpeechRecognizer.createSpeechRecognizer(this);
        recognizer.setRecognitionListener(new RecognitionListener() {
            private String first(Bundle b) {
                ArrayList<String> list = b == null ? null : b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                return list == null || list.isEmpty() ? "" : list.get(0);
            }

            @Override public void onReadyForSpeech(Bundle p) { emit("start", ""); }
            @Override public void onBeginningOfSpeech() { }
            @Override public void onRmsChanged(float v) { }
            @Override public void onBufferReceived(byte[] b) { }
            @Override public void onEndOfSpeech() { }
            @Override public void onEvent(int t, Bundle b) { }
            @Override public void onPartialResults(Bundle b) { emit("partial", first(b)); }

            @Override
            public void onResults(Bundle b) {
                emit("final", first(b));
                emit("end", "");
            }

            @Override
            public void onError(int code) {
                String name;
                switch (code) {
                    case SpeechRecognizer.ERROR_NO_MATCH:
                    case SpeechRecognizer.ERROR_SPEECH_TIMEOUT: name = "no-speech"; break;
                    case SpeechRecognizer.ERROR_NETWORK:
                    case SpeechRecognizer.ERROR_NETWORK_TIMEOUT: name = "network"; break;
                    case SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS: name = "not-allowed"; break;
                    case SpeechRecognizer.ERROR_RECOGNIZER_BUSY: name = "busy"; break;
                    default: name = "error";
                }
                emit("error", name);
                emit("end", "");
            }
        });
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        i.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
        i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
        if (language != null && !language.isEmpty()) i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, language);
        recognizer.startListening(i);
    }

    private void stopRecognizer() {
        if (recognizer != null) {
            try { recognizer.destroy(); } catch (RuntimeException ignored) { }
            recognizer = null;
        }
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results);
        if (code == NOTIFY_REQUEST) return;               // the system remembers the answer; the page asks again with allowed()
        if (code != MIC_REQUEST) return;
        if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED && pendingLanguage != null) startRecognizer(pendingLanguage);
        else { emit("error", "not-allowed"); emit("end", ""); }
        pendingLanguage = null;
    }

    // ---- what the pages may ask the app to do ----------------------------------------------------------------------------------
    private final class Bridge {
        private boolean ok() { return trustedPage; }

        @JavascriptInterface
        public String version() { return "1.2"; }

        /** The saved address (host:port) of the PC, or "" before setup. */
        @JavascriptInterface
        public String address() { return ok() ? MainActivity.this.address() : ""; }

        /** Setup page: fetch the PC's certificate and report its fingerprint, to be compared with the PC's screen. Answer goes to window.onProbe. */
        @JavascriptInterface
        public void probe(String raw) {
            if (!ok()) return;
            final String a = (raw == null ? "" : raw.trim().replaceFirst("^https?://", "").replaceAll("/+$", ""));
            new Thread(() -> {
                JSONObject out = new JSONObject();
                try {
                    if (!ADDRESS.matcher(a).matches()) throw new IllegalArgumentException("That doesn't look like an address. Use something like 192.168.1.20:8443.");
                    String target = a.contains(":") ? a : a + ":8443";
                    final X509Certificate[] seen = new X509Certificate[1];
                    TrustManager grab = new X509TrustManager() {      // only to read the certificate: nothing is trusted because of this connection
                        @Override public void checkClientTrusted(X509Certificate[] c, String t) { }
                        @Override public void checkServerTrusted(X509Certificate[] c, String t) { seen[0] = c[0]; }
                        @Override public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
                    };
                    SSLContext ctx = SSLContext.getInstance("TLS");
                    ctx.init(null, new TrustManager[]{grab}, null);
                    HttpsURLConnection c = (HttpsURLConnection) new URL("https://" + target + "/").openConnection();
                    c.setSSLSocketFactory(ctx.getSocketFactory());
                    c.setHostnameVerifier((h, session) -> true);
                    c.setConnectTimeout(6000);
                    c.setReadTimeout(6000);
                    c.getResponseCode();
                    c.disconnect();
                    if (seen[0] == null) throw new IllegalStateException("The PC did not show a certificate.");
                    String hex = spkiHex(seen[0]);
                    out.put("ok", true).put("address", target).put("pin", hex)
                       .put("print", (hex.substring(0, 4) + " " + hex.substring(4, 8) + " " + hex.substring(8, 12) + " " + hex.substring(12, 16)).toUpperCase());
                } catch (java.net.UnknownHostException | java.net.ConnectException | java.net.SocketTimeoutException e) {
                    try { out.put("ok", false).put("error", "Could not reach the PC there. Is JARVIS running, and is the phone on the same Wi-Fi?"); } catch (Exception ignored) { }
                } catch (Exception e) {
                    try { out.put("ok", false).put("error", String.valueOf(e.getMessage())); } catch (Exception ignored) { }
                }
                final String js = "window.onProbe&&window.onProbe(" + out + ")";
                runOnUiThread(() -> web.evaluateJavascript(js, null));
            }, "probe").start();
        }

        /** Setup page: the person confirmed the fingerprint matches the PC's screen. */
        @JavascriptInterface
        public void trust(String address, String pin) {
            if (!ok() || address == null || pin == null || !ADDRESS.matcher(address).matches() || !HEX64.matcher(pin).matches()) return;
            prefs.edit().putString("address", address).putString("pin", pin).remove("token").apply();
            runOnUiThread(MainActivity.this::load);
        }

        /** "Change PC": forget the saved address and show setup again. */
        @JavascriptInterface
        public void forgetServer() {
            if (!ok()) return;
            prefs.edit().remove("address").remove("pin").remove("token").apply();
            runOnUiThread(MainActivity.this::load);
        }

        /** Offline page: try the saved address again. */
        @JavascriptInterface
        public void retry() {
            if (ok()) runOnUiThread(MainActivity.this::load);
        }

        /** The pairing token lives here, not in the page's storage, so a new PC address doesn't lose the pairing. */
        @JavascriptInterface
        public String getToken() { return ok() ? prefs.getString("token", "") : ""; }

        @JavascriptInterface
        public void setToken(String token) {
            if (ok() && token != null && token.length() < 200) prefs.edit().putString("token", token).apply();
        }

        @JavascriptInterface
        public void clearToken() {
            if (ok()) prefs.edit().remove("token").apply();
        }

        @JavascriptInterface
        public void startListening(String language) {
            if (!ok()) return;
            runOnUiThread(() -> {
                if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                    pendingLanguage = language == null ? "" : language;
                    requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, MIC_REQUEST);
                } else {
                    startRecognizer(language);
                }
            });
        }

        // ---- the standalone assistant: storage, AI keys, network (the page never sees the keys) ----
        private boolean kvName(String name) { return "facts".equals(name) || "brain".equals(name); }

        @JavascriptInterface
        public String kvGet(String name) { return ok() && kvName(name) ? prefs.getString("kv_" + name, "") : ""; }

        @JavascriptInterface
        public void kvSet(String name, String value) {
            if (ok() && kvName(name) && value != null && value.length() <= 400_000) prefs.edit().putString("kv_" + name, value).apply();
        }

        @JavascriptInterface
        public int keyCount() { return ok() ? Net.keyCount(MainActivity.this) : 0; }

        /** Which models are ready, as JSON, never their keys. */
        @JavascriptInterface
        public String keyNames() { return ok() ? Net.modelNames(MainActivity.this) : "[]"; }

        /** The keys from the PC (JSON list). Only accepted from the PC's own page, never from the bundled pages. */
        @JavascriptInterface
        public int importKeys(String json) {
            return ok() && json != null && !onBundledPage() ? Net.importKeys(MainActivity.this, json) : 0;
        }

        @JavascriptInterface
        public void clearKeys() {
            if (ok()) Net.clearKeys(MainActivity.this);
        }

        /** One AI request. The answer comes back to window.__net(id, json). */
        @JavascriptInterface
        public void llm(String id, String requestJson) {
            if (!ok() || id == null || requestJson == null || requestJson.length() > 300_000) return;
            network.execute(() -> emitNet(id, Net.llm(MainActivity.this, requestJson)));
        }

        /** Reads a public web page for the assistant. The answer comes back to window.__net(id, json). */
        @JavascriptInterface
        public void web(String id, String url) {
            if (!ok() || id == null || url == null || url.length() > 2000) return;
            network.execute(() -> emitNet(id, Net.web(url)));
        }

        /** Is the PC reachable right now (with its pinned key)? Answer: window.__net(id, {ok}). */
        @JavascriptInterface
        public void pcPing(String id) {
            if (!ok() || id == null) return;
            final String a = MainActivity.this.address(), p = pin();
            network.execute(() -> {
                boolean up = false;
                if (!a.isEmpty() && !p.isEmpty()) {
                    try {
                        javax.net.ssl.HttpsURLConnection c = Pinned.open(a, p, "/ping");
                        c.setConnectTimeout(4000);
                        c.setReadTimeout(4000);
                        int code = c.getResponseCode();                          // 401 is fine: it just means "not signed in"
                        up = code == 200 || code == 401;
                        c.disconnect();
                    } catch (Exception ignored) { /* not reachable */ }
                }
                emitNet(id, up ? "{\"ok\":true}" : "{\"ok\":false}");
            });
        }

        /** Open the bundled assistant page (works without the PC; needs the AI keys). */
        @JavascriptInterface
        public void openLocal() {
            if (ok() && Net.keyCount(MainActivity.this) > 0) runOnUiThread(() -> web.loadUrl(LOCAL));
        }

        @JavascriptInterface
        public void busy(boolean on) { chatInProgress = on; }

        // ---- reminders and alerts ----
        /** The waiting reminders as JSON: [{id, text, due(ms), pc}]. */
        @JavascriptInterface
        public String reminders() { return ok() ? Reminders.list(MainActivity.this) : "[]"; }

        /** Adds a reminder made on the phone; returns "" or what is wrong. */
        @JavascriptInterface
        public String addReminder(String text, double dueMs) {
            if (!ok()) return "Not allowed here.";
            String problem = Reminders.add(MainActivity.this, text, (long) dueMs);
            if (problem.isEmpty()) requestNotifications();
            return problem;
        }

        @JavascriptInterface
        public void deleteReminder(String id) {
            if (ok() && id != null) Reminders.delete(MainActivity.this, id);
        }

        /** What the PC has not been told about yet (JSON), for POST /reminders/sync. */
        @JavascriptInterface
        public String pendingReminders() { return ok() ? Reminders.pending(MainActivity.this) : "{}"; }

        /** The PC's answer to the sync, with what was sent. */
        @JavascriptInterface
        public void applySync(String sent, String answer) {
            if (ok() && sent != null && answer != null) Reminders.applySync(MainActivity.this, sent, answer);
        }

        /** The page already announced this reminder (the PC pushed it): don't ring it again here. */
        @JavascriptInterface
        public void heard(String id) {
            if (ok() && id != null) Reminders.heard(MainActivity.this, id);
        }

        @JavascriptInterface
        public boolean notificationsAllowed() { return Notify.allowed(MainActivity.this); }

        @JavascriptInterface
        public void requestNotifications() {
            if (!ok() || Notify.allowed(MainActivity.this)) return;
            runOnUiThread(() -> requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, NOTIFY_REQUEST));
        }

        /** Alerts from the PC while the app is closed (a small notification stays up while this is on). */
        @JavascriptInterface
        public boolean backgroundAlerts() { return ok() && prefs.getBoolean("alerts", false); }

        @JavascriptInterface
        public void setBackgroundAlerts(boolean on) {
            if (!ok()) return;
            prefs.edit().putBoolean("alerts", on).apply();
            if (on) { requestNotifications(); AlertService.start(MainActivity.this); } else AlertService.stop(MainActivity.this);
        }

        @JavascriptInterface
        public void stopListening() {
            if (!ok()) return;
            runOnUiThread(() -> { if (recognizer != null) recognizer.stopListening(); });
        }

        @JavascriptInterface
        public void keepScreenOn(boolean on) {
            if (!ok()) return;
            runOnUiThread(() -> {
                if (on) getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            });
        }
    }
}
