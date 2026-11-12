package dev.jarvis.tv;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.graphics.Typeface;
import android.view.Gravity;
import android.view.View;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.Calendar;

/** A short welcome shown once each time the projector is switched on: JARVIS's orb, the name and a greeting, then it fades into the home screen. */
final class Welcome extends FrameLayout {
    private final Runnable onDone;
    private final LinearLayout column;                        // the orb and the words: they fade in over the solid background
    private boolean finished;

    Welcome(Context context, float density, Runnable onDone) {
        super(context);
        this.onDone = onDone;
        setClickable(true);                                   // while it is showing it takes the presses, so OK can't open a tile behind it
        addView(new Backdrop(context), new LayoutParams(-1, -1));

        column = new LinearLayout(context);
        column.setOrientation(LinearLayout.VERTICAL);
        column.setGravity(Gravity.CENTER);
        addView(column, new LayoutParams(-1, -1));

        OrbView orb = new OrbView(context);
        column.addView(orb, new LinearLayout.LayoutParams(Math.round(120 * density), Math.round(120 * density)));
        orb.setScaleX(0.85f);
        orb.setScaleY(0.85f);
        orb.animate().scaleX(1.08f).scaleY(1.08f).setDuration(1800).start();

        TextView name = new TextView(context);
        name.setText("J.A.R.V.I.S");
        name.setTextColor(0xFF3FD8FF);
        name.setTextSize(34);
        name.setTypeface(Typeface.create("sans-serif-light", Typeface.BOLD));
        name.setLetterSpacing(0.3f);
        name.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams nameParams = new LinearLayout.LayoutParams(-2, -2);
        nameParams.topMargin = Math.round(18 * density);
        column.addView(name, nameParams);

        TextView greeting = new TextView(context);
        greeting.setText(greeting());
        greeting.setTextColor(0xFF9DB4C6);
        greeting.setTextSize(16);
        greeting.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams greetingParams = new LinearLayout.LayoutParams(-2, -2);
        greetingParams.topMargin = Math.round(8 * density);
        column.addView(greeting, greetingParams);
    }

    private static String greeting() {
        int hour = Calendar.getInstance().get(Calendar.HOUR_OF_DAY);
        return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
    }

    /** Fades in, holds for a moment, fades out, then calls the "done" action (which removes this view). */
    void play() {
        column.setAlpha(0f);                                  // the background is solid at once, so the home screen is never seen through it
        column.animate().alpha(1f).setDuration(350).withEndAction(() -> postDelayed(() -> {
            if (!finished) animate().alpha(0f).setDuration(500).withEndAction(this::finish).start();
        }, 1300)).start();
    }

    /** Ends it now (any remote button does this). */
    void skip() {
        column.animate().cancel();
        animate().cancel();
        finish();
    }

    private void finish() {
        if (finished) return;
        finished = true;
        onDone.run();
    }

    /** A glowing cyan ball inside a thin ring. */
    private static final class OrbView extends View {
        private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint ring = new Paint(Paint.ANTI_ALIAS_FLAG);

        OrbView(Context context) {
            super(context);
            ring.setStyle(Paint.Style.STROKE);
            ring.setColor(0xFF3FD8FF);
        }

        @Override
        protected void onSizeChanged(int w, int h, int oldw, int oldh) {
            float r = Math.min(w, h) / 2f;
            fill.setShader(new RadialGradient(w / 2f, h / 2f, r, new int[]{0xFFE8FBFF, 0xFF3FD8FF, 0x00102030}, new float[]{0f, 0.45f, 1f}, Shader.TileMode.CLAMP));
            ring.setStrokeWidth(Math.max(2f, r * 0.05f));
        }

        @Override
        protected void onDraw(Canvas canvas) {
            float cx = getWidth() / 2f, cy = getHeight() / 2f, r = Math.min(getWidth(), getHeight()) / 2f;
            canvas.drawCircle(cx, cy, r * 0.95f, fill);
            canvas.drawCircle(cx, cy, r * 0.95f, ring);
        }
    }
}
