package dev.jarvis.tv;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.view.View;

/** The home screen's background: a dark blue gradient with two soft glows. Drawn once, nothing animates (easy on the projector). */
final class Backdrop extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private Shader base, glowA, glowB;

    Backdrop(Context context) {
        super(context);
    }

    @Override
    protected void onSizeChanged(int w, int h, int oldw, int oldh) {
        base = new LinearGradient(0, 0, 0, h, 0xFF040A12, 0xFF0A1826, Shader.TileMode.CLAMP);
        glowA = new RadialGradient(w * 0.85f, -h * 0.05f, w * 0.65f, 0x3328D8FF, 0x0028D8FF, Shader.TileMode.CLAMP);
        glowB = new RadialGradient(w * 0.05f, h * 1.05f, w * 0.55f, 0x224A7CFF, 0x004A7CFF, Shader.TileMode.CLAMP);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        if (base == null) return;
        for (Shader s : new Shader[]{base, glowA, glowB}) {
            paint.setShader(s);
            canvas.drawRect(0, 0, getWidth(), getHeight(), paint);
        }
    }
}
