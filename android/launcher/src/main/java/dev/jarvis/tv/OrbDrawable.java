package dev.jarvis.tv;

import android.graphics.Canvas;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.PixelFormat;
import android.graphics.RadialGradient;
import android.graphics.Rect;
import android.graphics.Shader;
import android.graphics.drawable.Drawable;

/** JARVIS's orb as an icon: a glowing cyan ball inside a ring. Used for the JARVIS tile when the JARVIS app is not installed yet. */
final class OrbDrawable extends Drawable {
    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint ring = new Paint(Paint.ANTI_ALIAS_FLAG);

    OrbDrawable() {
        ring.setStyle(Paint.Style.STROKE);
        ring.setColor(0xFF3FD8FF);
    }

    @Override
    protected void onBoundsChange(Rect b) {
        float r = Math.min(b.width(), b.height()) / 2f;
        fill.setShader(new RadialGradient(b.exactCenterX(), b.exactCenterY(), r, new int[]{0xFFE8FBFF, 0xFF3FD8FF, 0x00102030}, new float[]{0f, 0.45f, 1f}, Shader.TileMode.CLAMP));
        ring.setStrokeWidth(Math.max(2f, r * 0.08f));
    }

    @Override
    public void draw(Canvas canvas) {
        Rect b = getBounds();
        float r = Math.min(b.width(), b.height()) / 2f;
        canvas.drawCircle(b.exactCenterX(), b.exactCenterY(), r * 0.9f, fill);
        canvas.drawCircle(b.exactCenterX(), b.exactCenterY(), r * 0.9f, ring);
    }

    @Override public void setAlpha(int alpha) { fill.setAlpha(alpha); ring.setAlpha(alpha); }
    @Override public void setColorFilter(ColorFilter filter) { fill.setColorFilter(filter); ring.setColorFilter(filter); }
    @Override public int getOpacity() { return PixelFormat.TRANSLUCENT; }
}
