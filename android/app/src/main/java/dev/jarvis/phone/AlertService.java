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
import java.nio.charset.StandardCharsets;

import javax.net.ssl.HttpsURLConnection;

/**
 * Optional: keeps a connection to the PC's /events stream while the app is closed, so alerts (a finished timer, Claude finishing, a problem
 * found, a reminder) arrive as notifications. Android requires a visible notification while this runs. It only talks to the PC the app was
 * set up with, and only accepts the pinned key. It stops by itself when the setting is turned off or the phone is forgotten.
 */
public class AlertService extends Service {
    private static final long RETRY_FIRST_MS = 2_000, RETRY_MAX_MS = 5 * 60_000;     // away from home the PC cannot be reached: ask less and less often (every ask wakes the radio)
    private final Object nap = new Object();
    private boolean nudged = false;
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
        } else {
            synchronized (nap) { nudged = true; nap.notifyAll(); }      // the app was opened: try the PC now instead of waiting out a long pause
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
        long wait = RETRY_FIRST_MS;
        while (running) {
            SharedPreferences p = prefs();
            if (!p.getBoolean("alerts", false) || p.getString("token", "").isEmpty()) {
                stopSelf();
                return;
            }
            try {
                if (listen(p.getString("address", ""), p.getString("pin", ""), p.getString("token", ""))) wait = RETRY_FIRST_MS;
            } catch (InterruptedException e) {
                return;
            } catch (Exception e) {
                // offline, PC off or restarting: try again below
            }
            boolean early;
            try {
                synchronized (nap) {
                    if (!nudged) nap.wait(wait);
                    early = nudged;
                    nudged = false;
                }
            } catch (InterruptedException e) {
                return;
            }
            wait = early ? RETRY_FIRST_MS : Math.min(wait * 2, RETRY_MAX_MS);
        }
    }

    /** One connection: reads events until it ends. True if it connected at all. */
    private boolean listen(String address, String pin, String token) throws Exception {
        if (address.isEmpty() || pin.isEmpty()) return false;
        HttpsURLConnection c = Pinned.open(address, pin, "/events");
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
                    String kind = ev.optString("type");
                    if ("find".equals(kind)) { FindService.start(this); continue; }          // "find my phone" on the PC
                    if ("find_stop".equals(kind)) { FindService.stop(this); continue; }
                    if (!"push".equals(kind)) continue;
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
