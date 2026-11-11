package dev.jarvis.tv;

import android.accessibilityservice.AccessibilityService;
import android.content.ActivityNotFoundException;
import android.content.SharedPreferences;
import android.view.KeyEvent;
import android.view.accessibility.AccessibilityEvent;

/**
 * Makes one remote button open HDMI from anywhere. Android only gives button presses to the app in front, so this is an accessibility
 * service (switched on once in the projector's Settings, Accessibility): it is shown every key press before the app in front, and all
 * it does is compare each one with the single button you chose in JARVIS Home ("Remote button for HDMI..."). That button is used up
 * (the app in front never sees it); every other key is passed on untouched. It reads no screen content and sends nothing anywhere.
 */
public class KeyService extends AccessibilityService {
    static final String PREFS = "home";
    static final String KEY_CODE = "hdmi_key";
    static final String KEY_SCAN = "hdmi_scan";
    static final int NONE = -1;                                                // "no button chosen" (0 is a real value: KEYCODE_UNKNOWN, a button known only by its scan code)

    @Override
    protected boolean onKeyEvent(KeyEvent event) {
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        int code = prefs.getInt(KEY_CODE, NONE);
        if (code == NONE) return false;                                        // no button chosen: pass everything on
        boolean mine = code != KeyEvent.KEYCODE_UNKNOWN ? event.getKeyCode() == code
                : event.getKeyCode() == KeyEvent.KEYCODE_UNKNOWN && event.getScanCode() == prefs.getInt(KEY_SCAN, -1);
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
