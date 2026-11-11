package dev.jarvis.phone;

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

/**
 * "Find my phone": the PC asked this phone to ring (say "Jarvis, find my phone" or press the button in the PC's status menu). It rings and buzzes for
 * two minutes, or until Stop is pressed here or on the PC.
 *
 * Out of the box it follows the phone's own rules, exactly like a reminder call: it rings only when the ringer is on and Do Not Disturb is off, buzzes in
 * vibrate mode, and in silent mode only shows the notification (which says so). A phone that is on silent is the usual reason it cannot be found, so
 * there is a switch in the app's menu, OFF until the person turns it on, that lets this one thing ring on the alarm sound at full volume even when the
 * phone is silent or in Do Not Disturb. Only this service does that, and only behind that switch; the volume it raises is put back when it stops.
 */
public class FindService extends Service {
    static final long RING_MS = 120_000;
    private static final int NOTIFICATION = 7;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private Ringtone ringtone;
    private Vibrator vibrator;
    private AudioManager audio;
    private int alarmVolumeWas = -1;

    /** Has the person allowed "find my phone" to ring even on silent? (Off unless they switched it on.) */
    static boolean loud(Context c) { return c.getSharedPreferences("jarvis", Context.MODE_PRIVATE).getBoolean("find_loud", false); }

    static void start(Context c) {
        try {
            c.startForegroundService(new Intent(c, FindService.class));
        } catch (RuntimeException e) {
            android.util.Log.w("JarvisFind", "could not start", e);
        }
    }

    static void stop(Context c) { c.stopService(new Intent(c, FindService.class)); }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        boolean loud = loud(this);
        boolean quiet = !loud && !CallService.mayRing(this);
        String text = loud ? "Ringing at full volume. Press Stop here or on the PC when you have found it."
                : quiet ? "This phone is on silent (or Do Not Disturb is on), so it is not ringing. You can allow that in JARVIS's menu: Alerts and battery."
                : "Ringing. Press Stop here or on the PC when you have found it.";
        try {
            startForeground(NOTIFICATION, Notify.finding(this, text), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
        } catch (RuntimeException e) {
            android.util.Log.w("JarvisFind", "could not go to the foreground", e);
            stopSelf();
            return START_NOT_STICKY;
        }
        ring(loud);
        ui.removeCallbacksAndMessages(null);
        ui.postDelayed(this::stopSelf, RING_MS);
        return START_NOT_STICKY;
    }

    private void ring(boolean loud) {
        release();
        audio = getSystemService(AudioManager.class);
        try {
            if (loud) {
                alarmVolumeWas = audio.getStreamVolume(AudioManager.STREAM_ALARM);
                audio.setStreamVolume(AudioManager.STREAM_ALARM, audio.getStreamMaxVolume(AudioManager.STREAM_ALARM), 0);
                play(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM), AudioAttributes.USAGE_ALARM);
                buzz();
            } else {
                if (CallService.mayRing(this)) play(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE), AudioAttributes.USAGE_NOTIFICATION_RINGTONE);
                if (CallService.mayBuzz(this)) buzz();
            }
        } catch (RuntimeException e) {
            android.util.Log.w("JarvisFind", "could not ring", e);
        }
    }

    private void play(android.net.Uri uri, int usage) {
        ringtone = RingtoneManager.getRingtone(this, uri);
        if (ringtone == null) return;
        ringtone.setAudioAttributes(new AudioAttributes.Builder().setUsage(usage).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build());
        ringtone.setLooping(true);
        ringtone.play();
    }

    private void buzz() {
        vibrator = getSystemService(Vibrator.class);
        if (vibrator != null) vibrator.vibrate(VibrationEffect.createWaveform(new long[]{0, 900, 500}, 0));
    }

    private void release() {
        if (ringtone != null) { try { ringtone.stop(); } catch (RuntimeException ignored) { } ringtone = null; }
        if (vibrator != null) { try { vibrator.cancel(); } catch (RuntimeException ignored) { } vibrator = null; }
        if (alarmVolumeWas >= 0 && audio != null) {                         // the volume it raised goes back
            try { audio.setStreamVolume(AudioManager.STREAM_ALARM, alarmVolumeWas, 0); } catch (RuntimeException ignored) { }
            alarmVolumeWas = -1;
        }
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
