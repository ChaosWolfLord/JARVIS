package dev.jarvis.tv;

import android.accessibilityservice.AccessibilityService;
import android.content.ActivityNotFoundException;
import android.content.SharedPreferences;
import android.view.KeyEvent;
import android.view.accessibility.AccessibilityEvent;
import android.widget.Toast;

/**
 * Makes one remote button open HDMI from anywhere. Android only gives button presses to the app in front, and the projector's own
 * buttons (Miracast, AirPlay, Source...) are taken by the system before any app sees them. An accessibility service (switched on once
 * in the projector's Settings, Accessibility) is shown every key press first, so it can see them all. All it does is compare each press
 * with the single button you chose in JARVIS Home ("Remote button for HDMI..."). That button is used up (the system and the app in front
 * never see it, so a button that normally opens Miracast stops doing that); every other key is passed on untouched. It reads no screen
 * content and sends nothing anywhere.
 */
public class KeyService extends AccessibilityService {
    static final String PREFS = "home";
    static final String KEY_CODE = "hdmi_key";
    static final String KEY_SCAN = "hdmi_scan";
    static final String LEARNING_UNTIL = "hdmi_learning_until";               // set by the choose-a-button screen: the next press (until this time) becomes the button
    static final int NONE = -1;                                                // "no button chosen" (0 is a real value: KEYCODE_UNKNOWN, a button known only by its scan code)

    private int swallowUp = Integer.MIN_VALUE;                                 // the release of the press that was just chosen must not open HDMI

    /** Buttons that are needed to move around, so they can't be taken over. */
    static boolean reserved(int keyCode) {
        switch (keyCode) {
            case KeyEvent.KEYCODE_DPAD_UP: case KeyEvent.KEYCODE_DPAD_DOWN: case KeyEvent.KEYCODE_DPAD_LEFT: case KeyEvent.KEYCODE_DPAD_RIGHT:
            case KeyEvent.KEYCODE_DPAD_CENTER: case KeyEvent.KEYCODE_ENTER: case KeyEvent.KEYCODE_BACK: case KeyEvent.KEYCODE_HOME:
            case KeyEvent.KEYCODE_MENU: case KeyEvent.KEYCODE_POWER: case KeyEvent.KEYCODE_VOLUME_UP: case KeyEvent.KEYCODE_VOLUME_DOWN:
            case KeyEvent.KEYCODE_VOLUME_MUTE:
                return true;
            default:
                return false;
        }
    }

    @Override
    protected boolean onKeyEvent(KeyEvent event) {
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        int keyCode = event.getKeyCode();

        long learningUntil = prefs.getLong(LEARNING_UNTIL, 0);
        if (learningUntil > System.currentTimeMillis()) {                      // the choose-a-button screen is open: take the next press
            if (reserved(keyCode)) return false;
            if (event.getAction() == KeyEvent.ACTION_DOWN && event.getRepeatCount() == 0) {
                prefs.edit().putInt(KEY_CODE, keyCode).putInt(KEY_SCAN, event.getScanCode()).remove(LEARNING_UNTIL).apply();
                swallowUp = keyCode;
                Toast.makeText(this, KeyEvent.keyCodeToString(keyCode).replace("KEYCODE_", "") + " now opens HDMI", Toast.LENGTH_LONG).show();
            }
            return true;
        }
        if (event.getAction() == KeyEvent.ACTION_UP && keyCode == swallowUp) {
            swallowUp = Integer.MIN_VALUE;
            return true;
        }

        int code = prefs.getInt(KEY_CODE, NONE);
        if (code == NONE) return false;                                        // no button chosen: pass everything on
        boolean mine = code != KeyEvent.KEYCODE_UNKNOWN ? keyCode == code
                : keyCode == KeyEvent.KEYCODE_UNKNOWN && event.getScanCode() == prefs.getInt(KEY_SCAN, -1);
        if (!mine) return false;
        if (event.getAction() == KeyEvent.ACTION_UP) {
            try {
                startActivity(Hdmi.intent());
            } catch (ActivityNotFoundException | SecurityException ignored) {
                // Live TV missing or refused: nothing to show
            }
        }
        return true;                                                           // the press (down and up) is used up
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // not interested in what is on the screen
    }

    @Override
    public void onInterrupt() {
    }
}
