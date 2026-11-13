package dev.jarvis.tv;

import android.content.Context;
import android.graphics.Canvas;
import android.view.View;

/** The same ball of turning dots as a plain view: the welcome screen uses it (it needs to scale and fade, which the home screen's surface can't). */
final class DotOrb extends View {
    private static final long FRAME_MS = 50;                  // 20 frames a second
    private final OrbPainter painter = new OrbPainter(true);
    private boolean running;
    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            if (!running) return;
            invalidate();
            postDelayed(this, FRAME_MS);
        }
    };

    DotOrb(Context context) {
        super(context);
    }

    @Override
    protected void onSizeChanged(int w, int h, int oldw, int oldh) {
        painter.resize(w, h);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        painter.draw(canvas, getWidth(), getHeight());
    }

    private void update() {
        boolean should = isShown() && getWindowVisibility() == VISIBLE;
        if (should == running) return;
        running = should;
        removeCallbacks(tick);
        if (running) post(tick);
    }

    @Override
    protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        update();
    }

    @Override
    protected void onDetachedFromWindow() {
        running = false;
        removeCallbacks(tick);
        super.onDetachedFromWindow();
    }

    @Override
    protected void onVisibilityChanged(View changed, int visibility) {
        super.onVisibilityChanged(changed, visibility);
        update();
    }

    @Override
    protected void onWindowVisibilityChanged(int visibility) {
        super.onWindowVisibilityChanged(visibility);
        update();
    }
}
