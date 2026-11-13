package dev.jarvis.tv;

import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.os.SystemClock;

import java.util.Arrays;

/**
 * Draws the ball of dots: 260 dots spread evenly over a sphere, turned a little further around the upright axis each time it is asked to draw
 * (one full turn every 24 seconds), smaller and fainter when on the far side. The dots are drawn in 8 depth bands, one paint per band.
 */
final class OrbPainter {
    private static final int COUNT = 260;
    private static final int BANDS = 8;
    private static final long PERIOD_MS = 24000;
    private static final float TILT = (float) Math.toRadians(-16);

    private final float[] x = new float[COUNT], y = new float[COUNT], z = new float[COUNT];    // the dots on a unit sphere, already tilted
    private final float[][] points = new float[BANDS][COUNT * 2];                              // this frame's screen positions, grouped by depth band
    private final int[] inBand = new int[BANDS];
    private final Paint[] bandPaint = new Paint[BANDS];
    private final float[] bandRadius = new float[BANDS];
    private final Paint glow = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final boolean withGlow;                            // the home screen draws the glow once, behind the orb, instead of on every frame

    OrbPainter(boolean withGlow) {
        this.withGlow = withGlow;
        for (int k = 0; k < BANDS; k++) {                      // far bands: small, faint, blue; near bands: bigger, brighter, nearly white
            float depth = (k + 0.5f) / BANDS, lift = depth * depth;
            Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
            p.setColor(Color.argb(60 + (int) (195 * depth), 63 + (int) (170 * lift), 216 + (int) (39 * lift), 255));
            bandPaint[k] = p;
        }
        double golden = Math.PI * (3 - Math.sqrt(5));
        float cosT = (float) Math.cos(TILT), sinT = (float) Math.sin(TILT);
        for (int i = 0; i < COUNT; i++) {
            float yy = 1f - 2f * (i + 0.5f) / COUNT;
            float r = (float) Math.sqrt(1f - yy * yy);
            float xx = (float) Math.cos(golden * i) * r;
            float zz = (float) Math.sin(golden * i) * r;
            x[i] = xx;
            y[i] = yy * cosT - zz * sinT;
            z[i] = yy * sinT + zz * cosT;
        }
    }

    /** Call when the size it is drawn at changes. */
    void resize(int w, int h) {
        float r = Math.min(w, h) / 2f;
        if (withGlow) glow.setShader(glowShader(w / 2f, h / 2f, r));
        for (int k = 0; k < BANDS; k++) bandRadius[k] = r * 0.03f * (0.5f + 0.95f * (k + 0.5f) / BANDS);
    }

    /** The soft cyan glow behind the dots. */
    static Shader glowShader(float cx, float cy, float r) {
        return new RadialGradient(cx, cy, r, new int[]{0x303FD8FF, 0x163FD8FF, 0x003FD8FF}, new float[]{0f, 0.7f, 1f}, Shader.TileMode.CLAMP);
    }

    void draw(Canvas canvas, int w, int h) {
        float cx = w / 2f, cy = h / 2f, radius = Math.min(cx, cy);
        if (withGlow) canvas.drawCircle(cx, cy, radius, glow);
        Arrays.fill(inBand, 0);

        double turn = (SystemClock.uptimeMillis() % PERIOD_MS) * (2 * Math.PI / PERIOD_MS);
        float c = (float) Math.cos(turn), s = (float) Math.sin(turn);
        for (int i = 0; i < COUNT; i++) {
            float zr = -x[i] * s + z[i] * c;                    // -1 = far side, +1 = nearest to you
            float xr = x[i] * c + z[i] * s;
            float near = 3.4f / (3.4f - zr);                    // a little perspective: nearer dots sit slightly further out
            int band = Math.min(BANDS - 1, (int) ((zr + 1f) / 2f * BANDS));
            float[] p = points[band];
            int n = inBand[band]++ * 2;
            p[n] = cx + xr * radius * near * 0.9f;
            p[n + 1] = cy + y[i] * radius * near * 0.9f;
        }
        for (int k = 0; k < BANDS; k++) {                       // far side first so the near dots are drawn over it
            float[] pts = points[k];
            for (int i = 0; i < inBand[k]; i++) canvas.drawCircle(pts[2 * i], pts[2 * i + 1], bandRadius[k], bandPaint[k]);
        }
    }
}
