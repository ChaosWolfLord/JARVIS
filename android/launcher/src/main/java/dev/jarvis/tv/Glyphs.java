package dev.jarvis.tv;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;

/** The pictures on the HDMI, USB and All apps buttons, drawn straight into a bitmap of the size they are shown at (they are not apps, so they have no icon of their own). */
final class Glyphs {
    private Glyphs() {
    }

    static Bitmap draw(String key, int px) {
        Bitmap bitmap = Bitmap.createBitmap(px, px, Bitmap.Config.ARGB_8888);
        Canvas c = new Canvas(bitmap);
        c.scale(px, px);                                  // draw in a 1 x 1 square
        Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
        line.setStyle(Paint.Style.STROKE);
        line.setStrokeWidth(0.06f);
        line.setStrokeCap(Paint.Cap.ROUND);
        line.setStrokeJoin(Paint.Join.ROUND);
        line.setColor(0xFF3FD8FF);
        Paint solid = new Paint(Paint.ANTI_ALIAS_FLAG);
        solid.setColor(0xFF3FD8FF);
        if (key.equals(HomeActivity.HDMI)) hdmi(c, line);
        else if (key.equals(HomeActivity.ALL)) grid(c, line);
        else usb(c, line, solid);
        return bitmap;
    }

    /** Four rounded squares: "all apps". */
    private static void grid(Canvas c, Paint line) {
        Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
        fill.setColor(0x333FD8FF);
        for (int row = 0; row < 2; row++) {
            for (int col = 0; col < 2; col++) {
                float left = 0.17f + col * 0.35f, top = 0.17f + row * 0.35f;
                c.drawRoundRect(left, top, left + 0.30f, top + 0.30f, 0.06f, 0.06f, fill);
                c.drawRoundRect(left, top, left + 0.30f, top + 0.30f, 0.06f, 0.06f, line);
            }
        }
    }

    /** An HDMI plug seen from the front: the flat-topped, chamfered-bottom shape with its row of pins. */
    private static void hdmi(Canvas c, Paint line) {
        Path plug = new Path();
        plug.moveTo(0.12f, 0.26f);
        plug.lineTo(0.88f, 0.26f);
        plug.lineTo(0.88f, 0.54f);
        plug.lineTo(0.72f, 0.78f);
        plug.lineTo(0.28f, 0.78f);
        plug.lineTo(0.12f, 0.54f);
        plug.close();
        Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
        fill.setColor(0x333FD8FF);
        c.drawPath(plug, fill);
        c.drawPath(plug, line);
        for (int i = 0; i < 5; i++) {
            float x = 0.26f + i * 0.12f;
            c.drawLine(x, 0.38f, x, 0.52f, line);
        }
    }

    /** The USB trident: a stem with an arrow on top, a circle on one branch and a square on the other. */
    private static void usb(Canvas c, Paint line, Paint solid) {
        c.drawLine(0.5f, 0.84f, 0.5f, 0.22f, line);
        c.drawCircle(0.5f, 0.86f, 0.07f, solid);
        Path arrow = new Path();
        arrow.moveTo(0.5f, 0.07f);
        arrow.lineTo(0.41f, 0.23f);
        arrow.lineTo(0.59f, 0.23f);
        arrow.close();
        c.drawPath(arrow, solid);
        Path left = new Path();
        left.moveTo(0.5f, 0.64f);
        left.lineTo(0.28f, 0.50f);
        left.lineTo(0.28f, 0.40f);
        c.drawPath(left, line);
        c.drawCircle(0.28f, 0.35f, 0.06f, solid);
        Path right = new Path();
        right.moveTo(0.5f, 0.52f);
        right.lineTo(0.72f, 0.38f);
        right.lineTo(0.72f, 0.32f);
        c.drawPath(right, line);
        c.drawRect(0.66f, 0.20f, 0.78f, 0.32f, solid);
    }
}
