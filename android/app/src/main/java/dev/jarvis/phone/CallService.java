package dev.jarvis.phone;

import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.Ringtone;
import android.media.RingtoneManager;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.provider.Settings;

/**
 * Rings a reminder call: shows "JARVIS is calling" (Answer, Decline, and the full-screen call screen), plays the phone's ringtone and buzzes,
 * until you answer, decline, or about 45 seconds pass.
 *
 * It rings only when the phone's own settings say a call may ring: the ringer is on (not silent, not vibrate) and Do Not Disturb is off.
 * It never changes the volume, the ringer mode or Do Not Disturb, never uses the alarm sound, and has no way past silent mode:
 * in vibrate mode it only buzzes, in silent mode or with Do Not Disturb on it makes no sound or buzz at all.
 */
public class CallService extends Service {
    private final Handler ui = new Handler(Looper.getMainLooper());
    private Ringtone ringtone;
    private Vibrator vibrator;
    private String id = "";

    /** Starts the ringing. False when the phone would not allow it (the caller then shows a plain reminder instead). */
    static boolean start(Context c, String id, String text) {
        try {
            c.startForegroundService(new Intent(c, CallService.class).putExtra("id", id).putExtra("text", text));
            return true;
        } catch (RuntimeException e) {
            android.util.Log.w("JarvisCall", "the ringer service could not start", e);
            return false;
        }
    }

    static void stop(Context c) { c.stopService(new Intent(c, CallService.class)); }

    /** May a call make a sound right now? Only with the ringer on and Do Not Disturb off, as set on the phone. */
    static boolean mayRing(Context c) {
        AudioManager am = c.getSystemService(AudioManager.class);
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        return am.getRingerMode() == AudioManager.RINGER_MODE_NORMAL && nm.getCurrentInterruptionFilter() == NotificationManager.INTERRUPTION_FILTER_ALL;
    }

    /** May a call buzz? Ringer on or on vibrate (not silent), and Do Not Disturb off. */
    static boolean mayBuzz(Context c) {
        AudioManager am = c.getSystemService(AudioManager.class);
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        return am.getRingerMode() != AudioManager.RINGER_MODE_SILENT && nm.getCurrentInterruptionFilter() == NotificationManager.INTERRUPTION_FILTER_ALL;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        id = intent == null ? "" : String.valueOf(intent.getStringExtra("id"));
        String text = intent == null ? "" : Reminders.clean(intent.getStringExtra("text"));
        try {
            startForeground(Notify.callKey(id), Notify.callNotification(this, id, text), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
        } catch (RuntimeException e) {
            android.util.Log.w("JarvisCall", "the ringer service could not go to the foreground", e);
            Notify.reminder(this, id, "Reminder", text);               // the phone refused: still a reminder
            stopSelf();
            return START_NOT_STICKY;
        }
        ring();
        // With "display over other apps" allowed (menu), the call screen opens at once even while the phone is in use; without it the phone
        // opens it over the lock screen when it is locked, and shows the notification when it is not.
        if (Settings.canDrawOverlays(this)) {
            try { startActivity(Notify.screenFor(this, id, text)); } catch (RuntimeException ignored) { }
        }
        ui.removeCallbacksAndMessages(null);
        ui.postDelayed(() -> { Notify.endCall(this, id); }, Notify.CALL_RINGS_MS);
        return START_NOT_STICKY;
    }

    private void ring() {
        release();
        if (mayRing(this)) {
            try {
                ringtone = RingtoneManager.getRingtone(this, RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE));
                if (ringtone != null) {
                    ringtone.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
                            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build());
                    ringtone.setLooping(true);
                    ringtone.play();
                }
            } catch (RuntimeException ignored) { }
        }
        if (mayBuzz(this)) {
            try {
                vibrator = getSystemService(Vibrator.class);
                if (vibrator != null) vibrator.vibrate(VibrationEffect.createWaveform(new long[]{0, 800, 600}, 0));
            } catch (RuntimeException ignored) { }
        }
    }

    private void release() {
        if (ringtone != null) { try { ringtone.stop(); } catch (RuntimeException ignored) { } ringtone = null; }
        if (vibrator != null) { try { vibrator.cancel(); } catch (RuntimeException ignored) { } vibrator = null; }
    }

    @Override
    public void onDestroy() {
        ui.removeCallbacksAndMessages(null);
        release();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
