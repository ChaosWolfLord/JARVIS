package dev.jarvis.phone;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;

/** The app's notifications: reminders and alerts (they pop up and buzz) and the quiet one that shows the alert listener is running. */
final class Notify {
    static final String REMINDERS = "reminders", ALERTS = "alerts", SERVICE = "service", CALLS = "calls", MISSED = "missed";
    static final String CALL_ANSWER = "dev.jarvis.phone.CALL_ANSWER", CALL_DECLINE = "dev.jarvis.phone.CALL_DECLINE";
    static final long CALL_RINGS_MS = 45_000;           // an unanswered call stops ringing after this

    private Notify() { }

    private static void channels(Context c) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm.getNotificationChannel(CALLS) != null) return;
        // The call rings like any notification: the phone's own rules decide. In silent mode it is silent, with Do Not Disturb it is held back,
        // in vibrate mode it buzzes. Deliberately NOT the alarm sound and NOT allowed to bypass Do Not Disturb.
        NotificationChannel calls = new NotificationChannel(CALLS, "JARVIS calls you", NotificationManager.IMPORTANCE_HIGH);
        calls.setDescription("A reminder that rings like an incoming call. Follows your silent mode and Do Not Disturb.");
        calls.setSound(android.media.RingtoneManager.getDefaultUri(android.media.RingtoneManager.TYPE_RINGTONE),
                new android.media.AudioAttributes.Builder().setUsage(android.media.AudioAttributes.USAGE_NOTIFICATION).setContentType(android.media.AudioAttributes.CONTENT_TYPE_SONIFICATION).build());
        calls.enableVibration(true);
        calls.setVibrationPattern(new long[]{0, 700, 500, 700, 500, 700});
        NotificationChannel missed = new NotificationChannel(MISSED, "Reminder text from a call", NotificationManager.IMPORTANCE_LOW);
        missed.setDescription("Quietly keeps the words of a reminder after JARVIS called you");
        nm.createNotificationChannel(calls);
        nm.createNotificationChannel(missed);
        if (nm.getNotificationChannel(REMINDERS) != null) return;
        NotificationChannel r = new NotificationChannel(REMINDERS, "Reminders", NotificationManager.IMPORTANCE_HIGH);
        r.setDescription("Reminders you or JARVIS set");
        NotificationChannel a = new NotificationChannel(ALERTS, "Alerts from your PC", NotificationManager.IMPORTANCE_HIGH);
        a.setDescription("Finished timers, Claude finishing, problems found on your PC");
        NotificationChannel s = new NotificationChannel(SERVICE, "Listening for alerts", NotificationManager.IMPORTANCE_MIN);
        s.setDescription("Shown while the app listens for alerts from your PC in the background");
        nm.createNotificationChannel(r);
        nm.createNotificationChannel(a);
        nm.createNotificationChannel(s);
    }

    private static PendingIntent open(Context c) {
        Intent i = new Intent(c, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        return PendingIntent.getActivity(c, 0, i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    static boolean allowed(Context c) {
        return Build.VERSION.SDK_INT < 33 || c.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
    }

    private static void post(Context c, String channel, String key, String title, String text, String category) {
        if (!allowed(c)) return;
        channels(c);
        Notification n = new Notification.Builder(c, channel)
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text))
                .setCategory(category)
                .setAutoCancel(true)
                .setContentIntent(open(c))
                .build();
        c.getSystemService(NotificationManager.class).notify(key.hashCode(), n);     // the same reminder from two sources replaces itself
    }

    static void reminder(Context c, String id, String title, String text) { post(c, REMINDERS, id, title, text, Notification.CATEGORY_REMINDER); }

    /** Does a reminder ring like a call? (the menu switch; on unless turned off) */
    static boolean callsOn(Context c) { return c.getSharedPreferences("jarvis", Context.MODE_PRIVATE).getBoolean("calls", true); }

    static int callKey(String id) { return ("call:" + id).hashCode(); }

    static boolean fullScreenAllowed(Context c) {
        return Build.VERSION.SDK_INT < 34 || c.getSystemService(NotificationManager.class).canUseFullScreenIntent();
    }

    /**
     * "JARVIS is calling": a high-priority notification that rings, with Answer and Decline, and opens the call screen over the lock screen where
     * the phone allows it. A quiet copy of the reminder's words stays in the notification list either way, so nothing is lost if you miss it.
     */
    static void call(Context c, String id, String text) {
        if (!allowed(c)) return;
        channels(c);
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        nm.notify(("missed:" + id).hashCode(), new Notification.Builder(c, MISSED)
                .setSmallIcon(R.drawable.ic_notification).setContentTitle("Reminder").setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text)).setCategory(Notification.CATEGORY_REMINDER)
                .setAutoCancel(true).setContentIntent(open(c)).build());
        Intent screen = new Intent(c, CallActivity.class).putExtra("id", id).putExtra("text", text)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent show = PendingIntent.getActivity(c, callKey(id), screen, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent answer = PendingIntent.getActivity(c, callKey(id) + 1, new Intent(screen).putExtra("answer", true), PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent decline = PendingIntent.getBroadcast(c, callKey(id) + 2, new Intent(c, AlarmReceiver.class).setAction(CALL_DECLINE).putExtra("id", id),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification n = new Notification.Builder(c, CALLS)
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle("JARVIS is calling")
                .setContentText("Reminder")
                .setCategory(Notification.CATEGORY_REMINDER)          // a reminder, not a phone call, so Do Not Disturb holds it back like any other reminder
                .setContentIntent(show)
                .setFullScreenIntent(show, true)
                .setTimeoutAfter(CALL_RINGS_MS)
                .setAutoCancel(true)
                .addAction(new Notification.Action.Builder(null, "Decline", decline).build())
                .addAction(new Notification.Action.Builder(null, "Answer", answer).build())
                .build();
        n.flags |= Notification.FLAG_INSISTENT;                       // keeps ringing until answered, declined or timed out (the phone's silent mode still applies)
        nm.notify(callKey(id), n);
    }

    static void endCall(Context c, String id) { c.getSystemService(NotificationManager.class).cancel(callKey(id)); }

    static void clearReminder(Context c, String id) { c.getSystemService(NotificationManager.class).cancel(("missed:" + id).hashCode()); }

    static void alert(Context c, String key, String title, String text) { post(c, ALERTS, key, title, text, Notification.CATEGORY_MESSAGE); }

    static Notification listening(Context c) {
        channels(c);
        return new Notification.Builder(c, SERVICE)
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle("JARVIS is listening for alerts")
                .setContentText("Tap to open. Turn this off in the app's menu.")
                .setOngoing(true)
                .setContentIntent(open(c))
                .build();
    }
}
