package dev.jarvis.phone;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.os.SystemClock;
import android.view.View;

/**
 * JARVIS's orb on the call screen: the same sphere of dots as on the PC and in the chat, drawn natively. It turns slowly, and the dots push outward
 * with the sound: with your voice while it listens (the phone's recognizer reports how loud you are), by itself while JARVIS speaks or thinks.
 * It is redrawn about 20 times a second when idle and 30 when active, and not at all while the screen is off. Nothing is recorded or sent.
 */
final class OrbView extends View {
    static final int IDLE = 0, LISTENING = 1, SPEAKING = 2, THINKING = 3;
    private static final int DOTS = 420, BANDS = 16;
    private static final double TAU = Math.PI * 2;

    private final float[] px = new float[DOTS], py = new float[DOTS], pz = new float[DOTS], phase = new float[DOTS];
    private final int[] band = new int[DOTS];
    private final float[] bands = new float[BANDS];
    private final float[][] pts = new float[6][DOTS * 2];                 // [back or front][quiet, medium, loud] point lists
    private final int[] count = new int[6];
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint glow = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final int accent = Color.rgb(122, 190, 255), accent2 = Color.rgb(176, 142, 255);
    private int state = IDLE;
    private float level, levelTarget, smooth, yaw, glowFor = -1;
    private long last = 0, levelAt = 0;

    OrbView(Context c) {
        super(c);
        paint.setStrokeCap(Paint.Cap.ROUND);
        double golden = Math.PI * (3 - Math.sqrt(5));
        long seed = 11;
        for (int i = 0; i < DOTS; i++) {
            double y = 1 - (2 * (i + 0.5)) / DOTS, r = Math.sqrt(1 - y * y);
            px[i] = (float) (Math.cos(golden * i) * r);
            py[i] = (float) y;
            pz[i] = (float) (Math.sin(golden * i) * r);
            band[i] = Math.min(BANDS - 1, (int) Math.floor(Math.abs(y) * BANDS));
            seed = (seed * 16807) % 2147483647L;
            phase[i] = (float) (seed / 2147483647.0 * TAU);
        }
    }

    void setState(int s) {
        if (s == state) return;
        state = s;
        invalidate();
    }

    /** How loud the person is right now, 0 to 1 (from the recognizer). */
    void hear(float v) {
        level = Math.max(0f, Math.min(1f, v));
        levelAt = SystemClock.uptimeMillis();
    }

    private float[] targets(double t) {
        float[] out = new float[BANDS];
        boolean fresh = SystemClock.uptimeMillis() - levelAt < 400;
        if (state == LISTENING && fresh) {
            for (int b = 0; b < BANDS; b++) out[b] = (float) Math.min(1, level * (0.55 + 0.7 * Math.abs(Math.sin(t * 7 + b * 0.9) * Math.sin(t * 3.1 + b * 0.31))));
            levelTarget = level;
        } else if (state == LISTENING) {
            for (int b = 0; b < BANDS; b++) out[b] = (float) (0.18 + 0.45 * Math.abs(Math.sin(t * 4.2 + b * 0.6) * Math.sin(t * 1.7 + b * 0.21)));
            levelTarget = 0.35f;
        } else if (state == SPEAKING) {
            for (int b = 0; b < BANDS; b++) out[b] = (float) (0.2 + 0.55 * Math.abs(Math.sin(t * 5.2 + b * 0.5) * Math.sin(t * 2.1 + b * 0.19)));
            levelTarget = (float) (0.5 + 0.25 * Math.sin(t * 7));
        } else if (state == THINKING) {
            for (int b = 0; b < BANDS; b++) out[b] = (float) (0.1 + 0.16 * (0.5 + 0.5 * Math.sin(t * 6 - b * 0.45)));
            levelTarget = 0.22f;
        } else {
            levelTarget = 0;
        }
        return out;
    }

    private int mix(int a, int b, float t) {
        return Color.rgb(Math.round(Color.red(a) + (Color.red(b) - Color.red(a)) * t), Math.round(Color.green(a) + (Color.green(b) - Color.green(a)) * t),
                Math.round(Color.blue(a) + (Color.blue(b) - Color.blue(a)) * t));
    }

    @Override
    protected void onDraw(Canvas canvas) {
        long now = SystemClock.uptimeMillis();
        long gap = state == IDLE ? 50 : 33;
        float dt = last == 0 ? 0.033f : Math.min(0.1f, (now - last) / 1000f);
        last = now;
        double t = now / 1000.0;
        float steps = Math.max(1f, dt * 60f);                              // the smoothing was tuned for 60 frames a second
        float rise = 1f - (float) Math.pow(0.4, steps), fall = 1f - (float) Math.pow(0.88, steps), follow = 1f - (float) Math.pow(0.75, steps);
        float[] goal = targets(t);
        for (int b = 0; b < BANDS; b++) bands[b] += (goal[b] - bands[b]) * (goal[b] > bands[b] ? rise : fall);
        smooth += (levelTarget - smooth) * follow;
        yaw += (state == THINKING ? 1.6f : state == LISTENING ? 0.5f : state == IDLE ? 0.12f : 0.28f) * dt;

        float s = Math.min(getWidth(), getHeight());
        if (s <= 0) return;
        float cx = getWidth() / 2f, cy = getHeight() / 2f;
        float awake = state == IDLE ? 0.6f : 1f;
        float breathe = (float) (0.5 + 0.5 * Math.sin(t * (state == IDLE ? 1.1 : state == THINKING ? 4.5 : 1.8)));
        float r0 = s * 0.33f * (1f + smooth * 0.14f + (state == LISTENING ? 0.05f : 0f) + 0.025f * breathe);

        int g = state == THINKING ? mix(accent, accent2, 0.6f) : accent;
        if (glowFor != s) {                                                // made once per size, not every frame
            glow.setShader(new android.graphics.RadialGradient(cx, cy, s * 0.5f, accent, Color.argb(0, Color.red(accent), Color.green(accent), Color.blue(accent)),
                    android.graphics.Shader.TileMode.CLAMP));
            glowFor = s;
        }
        glow.setAlpha((int) (255 * Math.min(1f, 0.08f + 0.2f * smooth + 0.05f * awake)));
        canvas.drawCircle(cx, cy, s * 0.5f, glow);

        double tilt = 0.42 + 0.06 * Math.sin(t * 0.4);
        float cyaw = (float) Math.cos(yaw), syaw = (float) Math.sin(yaw), ct = (float) Math.cos(tilt), st = (float) Math.sin(tilt);
        java.util.Arrays.fill(count, 0);
        for (int i = 0; i < DOTS; i++) {
            float x1 = px[i] * cyaw + pz[i] * syaw, z1 = -px[i] * syaw + pz[i] * cyaw;
            float y2 = py[i] * ct - z1 * st, z2 = py[i] * st + z1 * ct;
            float amp = bands[band[i]] * (0.65f + 0.35f * (float) Math.sin(phase[i] + t * 2.4));
            if (state == THINKING) amp += 0.3f * (0.5f + 0.5f * (float) Math.sin(t * 5.5 - py[i] * 4.5 + phase[i] * 0.2));
            else if (state == IDLE) amp += 0.06f * (0.5f + 0.5f * (float) Math.sin(t * 0.9 + py[i] * 3 + phase[i]));
            amp = Math.min(1f, amp);
            float out = 1f + amp * 0.36f, persp = 1f / (1f - z2 * 0.3f);
            float depth = (z2 + 1f) / 2f;
            int level3 = Math.min(2, (int) ((amp * 0.8f + depth * 0.3f) * 3f));
            int bucket = (z2 >= 0 ? 3 : 0) + level3;
            pts[bucket][count[bucket] * 2] = cx + x1 * r0 * out * persp;
            pts[bucket][count[bucket] * 2 + 1] = cy + y2 * r0 * out * persp;
            count[bucket]++;
        }
        float dot = s * 0.0155f;
        for (int bucket = 0; bucket < 6; bucket++) {
            if (count[bucket] == 0) continue;
            boolean front = bucket >= 3;
            int lv = bucket % 3;
            int base = mix(g, Color.WHITE, 0.12f + 0.3f * lv);
            paint.setColor(base);
            paint.setAlpha(Math.round(255 * (front ? 0.95f : 0.4f) * awake));
            paint.setStrokeWidth(dot * ((front ? 1.0f : 0.7f) + 0.35f * lv));
            canvas.drawPoints(pts[bucket], 0, count[bucket] * 2, paint);
        }
        postInvalidateDelayed(Math.max(1, gap - (SystemClock.uptimeMillis() - now)));
    }

    @Override
    protected void onVisibilityChanged(View changed, int visibility) {
        super.onVisibilityChanged(changed, visibility);
        if (visibility == VISIBLE) { last = 0; invalidate(); }
    }
}
