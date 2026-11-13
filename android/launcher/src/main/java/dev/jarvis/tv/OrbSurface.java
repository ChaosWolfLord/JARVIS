package dev.jarvis.tv;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.PixelFormat;
import android.graphics.PorterDuff;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;

/**
 * The big orb on the home screen. It is drawn on a surface of its own, about 15 times a second, so the rest of the screen (background and
 * tiles) is not redrawn each time: that is most of what animating costs on this projector's graphics chip. It sits on top of the window
 * (nothing else overlaps it), and it stops drawing whenever it is hidden, covered by another app or the screen is off.
 */
final class OrbSurface extends SurfaceView implements SurfaceHolder.Callback {
    private static final long FRAME_MS = 66;                  // 15 frames a second
    private final OrbPainter painter = new OrbPainter(false);
    private boolean surfaceReady, running;
    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            if (!running) return;
            drawFrame();
            postDelayed(this, FRAME_MS);
        }
    };

    OrbSurface(Context context) {
        super(context);
        setZOrderOnTop(true);                                  // above the window, so its see-through edge blends over the background
        getHolder().setFormat(PixelFormat.TRANSLUCENT);
        getHolder().addCallback(this);
    }

    private void drawFrame() {
        Canvas canvas;
        try {
            canvas = getHolder().lockCanvas();
        } catch (IllegalStateException | IllegalArgumentException e) {
            return;
        }
        if (canvas == null) return;
        try {
            canvas.drawColor(0, PorterDuff.Mode.CLEAR);
            painter.draw(canvas, canvas.getWidth(), canvas.getHeight());
        } finally {
            getHolder().unlockCanvasAndPost(canvas);
        }
    }

    private void update() {
        boolean should = surfaceReady && isShown() && getWindowVisibility() == VISIBLE;
        if (should == running) return;
        running = should;
        removeCallbacks(tick);
        if (running) post(tick);
    }

    @Override
    public void surfaceCreated(SurfaceHolder holder) {
        surfaceReady = true;
        update();
    }

    @Override
    public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {
        painter.resize(width, height);
        if (running) drawFrame();
    }

    @Override
    public void surfaceDestroyed(SurfaceHolder holder) {
        surfaceReady = false;
        update();
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

    @Override
    protected void onDetachedFromWindow() {
        running = false;
        removeCallbacks(tick);
        super.onDetachedFromWindow();
    }
}
