package dev.jarvis.phone;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Rings one reminder when its alarm goes off (the app does not need to be running), and hangs up a call from its Decline button. Not exported: only the app's own alarms and notifications can reach it. */
public class AlarmReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        String id = intent.getStringExtra("id");
        if (id == null) return;
        if (Reminders.ACTION.equals(intent.getAction())) Reminders.ring(context, id);
        else if (Notify.CALL_DECLINE.equals(intent.getAction())) Notify.endCall(context, id);      // the quiet copy of the reminder stays
    }
}
