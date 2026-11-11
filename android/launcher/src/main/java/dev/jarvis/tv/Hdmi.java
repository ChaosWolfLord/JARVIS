package dev.jarvis.tv;

import android.content.ComponentName;
import android.content.Intent;

/** How to show the projector's HDMI input: ask its Live TV screen for HDMI1, exactly as the projector's own Inputs screen does. */
final class Hdmi {
    private Hdmi() {
    }

    static Intent intent() {
        return new Intent().setComponent(new ComponentName("com.softwinner.awlivetv", "com.softwinner.awlivetv.MainActivity"))
                .putExtra("input_source", "hdmi1")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_MULTIPLE_TASK);
    }
}
