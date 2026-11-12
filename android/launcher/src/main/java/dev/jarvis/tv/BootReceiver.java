package dev.jarvis.tv;

import android.content.ActivityNotFoundException;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;

/**
 * The projector's firmware starts its own home screen by name every time it is switched on, so JARVIS Home would otherwise only appear
 * after you press Home. A few seconds after start-up (once the firmware's own screen is up) this brings JARVIS Home forward. Android only lets an
 * app start a screen from the background if it has been given "Display over other apps" (switched on by you in Settings; the menu entry
 * "Start after power-on" takes you there), so without that this does nothing. It is switched off by the same menu entry.
 */
public class BootReceiver extends BroadcastReceiver {
    static final String PREF_ENABLED = "boot_start";
    private static final long DELAY_MS = 4000;

    @Override
    public void onReceive(Context context, Intent intent) {
        if (!Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) return;
        SharedPreferences prefs = context.getSharedPreferences("home", Context.MODE_PRIVATE);
        if (!prefs.getBoolean(PREF_ENABLED, true) || !Settings.canDrawOverlays(context)) return;
        final PendingResult pending = goAsync();
        new Handler(Looper.getMainLooper()).postDelayed(() -> {
            try {
                context.startActivity(new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
                        .setComponent(new ComponentName(context, HomeActivity.class)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            } catch (ActivityNotFoundException | SecurityException ignored) {
                // not allowed to: nothing to do
            }
            pending.finish();
        }, DELAY_MS);
    }
}
