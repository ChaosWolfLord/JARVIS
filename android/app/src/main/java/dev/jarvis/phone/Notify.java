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
    static final String REMINDERS = "reminders", ALERTS = "alerts", SERVICE = "service";

    private Notify() { }

    private static void channels(Context c) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
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
