package dev.jarvis.tv;

import android.content.ComponentName;
import android.content.Intent;

/**
 * How to show the projector's HDMI input: ask its Live TV screen for the input, exactly as the projector's own Inputs screen does.
 * The projector has one HDMI socket. The firmware lists three inputs (HDMI1-3), but only "hdmi2" is wired to it (it is the only one that
 * raises the hot-plug line, and the firmware's own saved source is HDMI2), so that is the one to open.
 */
final class Hdmi {
    private Hdmi() {
    }

    static Intent intent() {
        return new Intent().setComponent(new ComponentName("com.softwinner.awlivetv", "com.softwinner.awlivetv.MainActivity"))
                .putExtra("input_source", "hdmi2")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_MULTIPLE_TASK);
    }
}
