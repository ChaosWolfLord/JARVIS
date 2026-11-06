package dev.jarvis.phone;

import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.os.IBinder;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;

import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/**
 * Optional: keeps a connection to the PC's /events stream while the app is closed, so alerts (a finished timer, Claude finishing, a problem
 * found, a reminder) arrive as notifications. Android requires a visible notification while this runs. It only talks to the PC the app was
 * set up with, and only accepts the pinned key. It stops by itself when the setting is turned off or the phone is forgotten.
 */
public class AlertService extends Service {
    private volatile boolean running = false;
    private Thread worker;

    static void start(Context c) {
        c.startForegroundService(new Intent(c, AlertService.class));
    }

    static void stop(Context c) {
        c.stopService(new Intent(c, AlertService.class));
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForeground(1, Notify.listening(this), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        if (!running) {
            running = true;
            worker = new Thread(this::loop, "alerts");
            worker.setDaemon(true);
            worker.start();
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        running = false;
        if (worker != null) worker.interrupt();
        super.onDestroy();
    }

    private SharedPreferences prefs() { return getSharedPreferences("jarvis", MODE_PRIVATE); }

    private void loop() {
        long wait = 2000;
        while (running) {
            SharedPreferences p = prefs();
            if (!p.getBoolean("alerts", false) || p.getString("token", "").isEmpty()) {
                stopSelf();
                return;
            }
            try {
                if (listen(p.getString("address", ""), p.getString("pin", ""), p.getString("token", ""))) wait = 2000;
            } catch (InterruptedException e) {
                return;
            } catch (Exception e) {
                // offline, PC off or restarting: try again below
            }
            try {
                Thread.sleep(wait);
            } catch (InterruptedException e) {
                return;
            }
            wait = Math.min(wait * 2, 60_000);
        }
    }

    /** One connection: reads events until it ends. True if it connected at all. */
    private boolean listen(String address, String pin, String token) throws Exception {
        if (address.isEmpty() || pin.isEmpty()) return false;
        final String wanted = pin;
        TrustManager pinned = new X509TrustManager() {
            @Override public void checkClientTrusted(X509Certificate[] c, String t) throws CertificateException { throw new CertificateException("no client certificates"); }

            @Override
            public void checkServerTrusted(X509Certificate[] chain, String t) throws CertificateException {
                try {
                    byte[] d = MessageDigest.getInstance("SHA-256").digest(chain[0].getPublicKey().getEncoded());
                    StringBuilder sb = new StringBuilder();
                    for (byte b : d) sb.append(String.format("%02x", b));
                    if (!sb.toString().equals(wanted)) throw new CertificateException("the PC's key is not the one that was confirmed");
                } catch (java.security.NoSuchAlgorithmException e) {
                    throw new CertificateException(e);
                }
            }

            @Override public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
        };
        SSLContext ctx = SSLContext.getInstance("TLS");
        ctx.init(null, new TrustManager[]{pinned}, null);
        HttpsURLConnection c = (HttpsURLConnection) new URL("https://" + address + "/events").openConnection();
        c.setSSLSocketFactory(ctx.getSocketFactory());
        c.setHostnameVerifier((h, s) -> true);                  // the pinned key is what identifies the PC, not its address
        c.setConnectTimeout(8000);
        c.setReadTimeout(60_000);                               // the PC sends a ping every 15 seconds
        c.setRequestProperty("Authorization", "Bearer " + token);
        try {
            if (c.getResponseCode() == 401) {                    // forgotten on the PC
                prefs().edit().remove("token").apply();
                return true;
            }
            try (BufferedReader r = new BufferedReader(new InputStreamReader(c.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while (running && (line = r.readLine()) != null) {
                    if (!line.startsWith("data:")) continue;
                    JSONObject ev = new JSONObject(line.substring(5).trim());
                    if (!"push".equals(ev.optString("type"))) continue;
                    String rid = ev.optString("rid", "");
                    String title = ev.optString("title", "JARVIS"), text = ev.optString("text", "");
                    if (!rid.isEmpty()) { Notify.reminder(this, rid, title, text); Reminders.heard(this, rid); }
                    else Notify.alert(this, title + text, title, text);
                    MainActivity.deliver(ev.toString());
                }
            }
            return true;
        } finally {
            c.disconnect();
        }
    }
}
