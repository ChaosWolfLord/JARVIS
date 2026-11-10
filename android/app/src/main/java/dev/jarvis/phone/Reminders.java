package dev.jarvis.phone;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.HashSet;
import java.util.Set;
import java.util.UUID;

/**
 * The phone's own copy of the reminders, and the alarms that ring them. They are kept here (not in the page) so they ring when the PC is
 * off, the page is closed and the app is not running. When the PC is reachable the page syncs them with the PC's list (see /reminders/sync).
 *
 * Each entry: id (the PC's id, or "L..." until the PC has seen it), text, due (ms), pc (does the PC know it), fired, deleted.
 * A fired or deleted entry that the PC knows about stays until the next sync tells the PC.
 */
final class Reminders {
    static final long MAX_AHEAD_MS = 366L * 24 * 3600 * 1000;
    static final int MAX_TEXT = 200;
    private static final String KEY = "reminders";
    private static final String SCHEDULED = "scheduled";
    static final String ACTION = "dev.jarvis.phone.REMINDER";

    private Reminders() { }

    private static SharedPreferences prefs(Context c) { return c.getSharedPreferences("jarvis", Context.MODE_PRIVATE); }

    private static JSONArray read(Context c) {
        try { return new JSONArray(prefs(c).getString(KEY, "[]")); } catch (JSONException e) { return new JSONArray(); }
    }

    private static void write(Context c, JSONArray a) { prefs(c).edit().putString(KEY, a.toString()).apply(); }

    private static boolean open(JSONObject r) { return !r.optBoolean("fired") && !r.optBoolean("deleted"); }

    static String clean(String text) {
        String t = text == null ? "" : text.trim().replaceAll("\\s+", " ");
        return t.length() > MAX_TEXT ? t.substring(0, MAX_TEXT) : t;
    }

    // ---- what the pages see ----------------------------------------------------------------------------------------------
    /** The waiting reminders, soonest first: [{id, text, due, pc}]. */
    static synchronized String list(Context c) {
        JSONArray a = read(c), out = new JSONArray();
        try {
            for (int i = 0; i < a.length(); i++) {
                JSONObject r = a.getJSONObject(i);
                if (open(r)) out.put(new JSONObject().put("id", r.getString("id")).put("text", r.getString("text")).put("due", r.getLong("due")).put("pc", r.optBoolean("pc")));
            }
            return sorted(out).toString();
        } catch (JSONException e) { return "[]"; }
    }

    private static JSONArray sorted(JSONArray a) throws JSONException {
        java.util.List<JSONObject> l = new java.util.ArrayList<>();
        for (int i = 0; i < a.length(); i++) l.add(a.getJSONObject(i));
        java.util.Collections.sort(l, (x, y) -> Long.compare(x.optLong("due"), y.optLong("due")));
        return new JSONArray(l);
    }

    /** Adds a reminder made on the phone. Returns "" when it worked, otherwise what is wrong. */
    static synchronized String add(Context c, String text, long dueMs) {
        text = clean(text);
        long now = System.currentTimeMillis();
        if (text.isEmpty()) return "What should I remind you about?";
        if (dueMs < now + 20_000) return "Pick a time at least a minute from now.";
        if (dueMs > now + MAX_AHEAD_MS) return "A reminder can be at most a year ahead.";
        JSONArray a = read(c);
        int count = 0;
        for (int i = 0; i < a.length(); i++) if (open(a.optJSONObject(i))) count++;
        if (count >= 50) return "There are already 50 reminders waiting.";
        try {
            a.put(new JSONObject().put("id", "L" + UUID.randomUUID().toString().substring(0, 8)).put("text", text).put("due", dueMs).put("pc", false));
        } catch (JSONException e) { return "Could not save that."; }
        write(c, a);
        scheduleAll(c);
        return "";
    }

    static synchronized void delete(Context c, String id) {
        JSONArray a = read(c), keep = new JSONArray();
        for (int i = 0; i < a.length(); i++) {
            JSONObject r = a.optJSONObject(i);
            if (r == null) continue;
            if (r.optString("id").equals(id)) {
                if (!r.optBoolean("pc")) continue;                       // the PC never heard of it: just forget it
                try { r.put("deleted", true); } catch (JSONException ignored) { }
            }
            keep.put(r);
        }
        write(c, keep);
        scheduleAll(c);
    }

    // ---- sync with the PC ----------------------------------------------------------------------------------------------------
    /** What the PC has not been told yet: {created:[{lid,text,due(seconds),fired}], deleted:[ids], fired:[ids]}. */
    static synchronized String pending(Context c) {
        JSONArray a = read(c);
        JSONArray created = new JSONArray(), deleted = new JSONArray(), fired = new JSONArray();
        try {
            for (int i = 0; i < a.length(); i++) {
                JSONObject r = a.getJSONObject(i);
                String id = r.getString("id");
                if (!r.optBoolean("pc")) {
                    if (!r.optBoolean("deleted")) created.put(new JSONObject().put("lid", id).put("text", r.getString("text")).put("due", r.getLong("due") / 1000.0).put("fired", r.optBoolean("fired")));
                } else if (r.optBoolean("deleted")) deleted.put(id);
                else if (r.optBoolean("fired")) fired.put(id);
            }
            return new JSONObject().put("created", created).put("deleted", deleted).put("fired", fired).toString();
        } catch (JSONException e) { return "{\"created\":[],\"deleted\":[],\"fired\":[]}"; }
    }

    /**
     * The PC's answer to a sync. `sent` is what pending() returned when the sync started (so exactly that is acknowledged and anything
     * made meanwhile stays for next time); `answer` is {reminders:[{id,text,due(seconds)}], created:[{lid,id}]}.
     */
    static synchronized void applySync(Context c, String sentJson, String answerJson) {
        try {
            JSONObject sent = new JSONObject(sentJson), answer = new JSONObject(answerJson);
            Set<String> sentCreated = new HashSet<>(), ackDeleted = new HashSet<>(), ackFired = new HashSet<>();
            for (int i = 0; i < sent.getJSONArray("created").length(); i++) sentCreated.add(sent.getJSONArray("created").getJSONObject(i).getString("lid"));
            for (int i = 0; i < sent.getJSONArray("deleted").length(); i++) ackDeleted.add(sent.getJSONArray("deleted").getString(i));
            for (int i = 0; i < sent.getJSONArray("fired").length(); i++) ackFired.add(sent.getJSONArray("fired").getString(i));
            JSONArray made = answer.getJSONArray("created"), server = answer.getJSONArray("reminders");
            java.util.Map<String, String> lidToId = new java.util.HashMap<>();
            for (int i = 0; i < made.length(); i++) {
                JSONObject m = made.getJSONObject(i);
                lidToId.put(m.getString("lid"), m.isNull("id") ? "" : m.getString("id"));
            }
            Set<String> serverIds = new HashSet<>();
            for (int i = 0; i < server.length(); i++) serverIds.add(server.getJSONObject(i).getString("id"));

            JSONArray a = read(c), keep = new JSONArray();
            Set<String> have = new HashSet<>();
            for (int i = 0; i < a.length(); i++) {
                JSONObject r = a.getJSONObject(i);
                String id = r.getString("id");
                if (sentCreated.contains(id) && lidToId.containsKey(id)) {
                    String pcId = lidToId.get(id);
                    if (pcId.isEmpty() || r.optBoolean("fired") || r.optBoolean("deleted")) continue;      // refused by the PC, or already rung: done with it
                    r.put("id", pcId).put("pc", true);
                    id = pcId;
                } else if (r.optBoolean("pc")) {
                    if (ackDeleted.contains(id) || ackFired.contains(id)) continue;                     // the PC knows now
                    if (!r.optBoolean("fired") && !r.optBoolean("deleted") && !serverIds.contains(id)) continue;   // cancelled or announced on the PC
                }
                have.add(id);
                keep.put(r);
            }
            for (int i = 0; i < server.length(); i++) {
                JSONObject s = server.getJSONObject(i);
                String id = s.getString("id");
                if (have.contains(id)) {
                    for (int j = 0; j < keep.length(); j++) {
                        JSONObject r = keep.getJSONObject(j);
                        if (r.getString("id").equals(id) && open(r)) r.put("text", s.getString("text")).put("due", Math.round(s.getDouble("due") * 1000));
                    }
                } else {
                    keep.put(new JSONObject().put("id", id).put("text", s.getString("text")).put("due", Math.round(s.getDouble("due") * 1000)).put("pc", true));
                }
            }
            write(c, keep);
        } catch (JSONException e) {
            return;
        }
        scheduleAll(c);
    }

    /** The PC (or the page) already announced this reminder: no need to ring it here too. The PC hears about it at the next sync. */
    static synchronized void heard(Context c, String id) {
        JSONArray a = read(c);
        boolean changed = false;
        for (int i = 0; i < a.length(); i++) {
            JSONObject r = a.optJSONObject(i);
            if (r != null && r.optString("id").equals(id) && open(r)) {
                try { r.put("fired", true); changed = true; } catch (JSONException ignored) { }
            }
        }
        if (changed) { write(c, a); scheduleAll(c); }
    }

    // ---- ringing ------------------------------------------------------------------------------------------------------------
    private static PendingIntent intentFor(Context c, String id, int flags) {
        Intent i = new Intent(c, AlarmReceiver.class).setAction(ACTION).setData(Uri.parse("jarvis://reminder/" + id)).putExtra("id", id);
        return PendingIntent.getBroadcast(c, 0, i, flags | PendingIntent.FLAG_IMMUTABLE);
    }

    /** (Re)sets one alarm per waiting reminder and clears the ones that are gone. Anything already overdue rings now, marked late. */
    static synchronized void scheduleAll(Context c) {
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        SharedPreferences p = prefs(c);
        for (String id : p.getStringSet(SCHEDULED, new HashSet<>())) {
            PendingIntent old = intentFor(c, id, PendingIntent.FLAG_NO_CREATE);
            if (old != null) { am.cancel(old); old.cancel(); }
        }
        Set<String> now = new HashSet<>();
        long t = System.currentTimeMillis();
        java.util.List<String> overdue = new java.util.ArrayList<>();
        JSONArray a = read(c);
        for (int i = 0; i < a.length(); i++) {
            JSONObject r = a.optJSONObject(i);
            if (r == null || !open(r)) continue;
            String id = r.optString("id");
            long due = r.optLong("due");
            if (due <= t + 1000) { overdue.add(id); continue; }
            PendingIntent pi = intentFor(c, id, PendingIntent.FLAG_UPDATE_CURRENT);
            if (Build.VERSION.SDK_INT >= 31 && !am.canScheduleExactAlarms()) am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, due, pi);
            else am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, due, pi);
            now.add(id);
        }
        p.edit().putStringSet(SCHEDULED, now).apply();
        for (String id : overdue) ring(c, id);
    }

    /** Marks a reminder as announced and shows it. Called by the alarm, and for ones that came due while the phone was off. */
    static synchronized void ring(Context c, String id) {
        JSONArray a = read(c);
        JSONObject hit = null;
        for (int i = 0; i < a.length(); i++) {
            JSONObject r = a.optJSONObject(i);
            if (r != null && r.optString("id").equals(id) && open(r)) { hit = r; break; }
        }
        if (hit == null) return;
        try {
            long late = System.currentTimeMillis() - hit.optLong("due");
            hit.put("fired", true);
            if (!hit.optBoolean("pc")) { /* kept as a "created and fired" entry until the PC hears about it */ }
            write(c, a);
            String text = hit.optString("text");
            if (Notify.callsOn(c) && late <= 120_000) Notify.call(c, id, text);      // rings like a call (a reminder that came due while the phone was off just shows, marked late)
            else Notify.reminder(c, id, late > 120_000 ? "Reminder (late)" : "Reminder", text);
            MainActivity.deliver(new JSONObject().put("type", "push").put("title", "Reminder").put("text", text).put("rid", id).toString());
        } catch (JSONException ignored) { }
    }
}
