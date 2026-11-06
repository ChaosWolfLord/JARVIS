package dev.jarvis.phone;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Rings one reminder when its alarm goes off (the app does not need to be running). Not exported: only the app's own alarms can reach it. */
public class AlarmReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (!Reminders.ACTION.equals(intent.getAction())) return;
        String id = intent.getStringExtra("id");
        if (id != null) Reminders.ring(context, id);
    }
}
