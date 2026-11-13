package dev.jarvis.tv;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.view.View;
import android.view.ViewGroup;

/**
 * The middle of the home screen: the orb in the centre and the tiles spaced evenly round it on an oval. The first child is the orb; every
 * other child is a tile. Tiles are placed clockwise, starting just right of the top, so the first one (HDMI) is at the top right.
 */
final class Ring extends ViewGroup {
    private final View orb;
    private final int gap;
    private final Paint glow = new Paint(Paint.ANTI_ALIAS_FLAG);   // the soft glow behind the orb: drawn here, once, not by the animation
    private int tileW, tileH;

    Ring(Context context, View orb, float density) {
        super(context);
        this.orb = orb;
        this.gap = Math.round(10 * density);
        setClipChildren(false);
        setWillNotDraw(false);
        addView(orb);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        float half = orb.getWidth() / 2f;
        if (half > 0) canvas.drawCircle(orb.getLeft() + half, orb.getTop() + orb.getHeight() / 2f, half, glow);
    }

    /** The orb sits on its own surface above the window, so while the welcome screen covers the window it has to be hidden. */
    void showOrb(boolean show) {
        orb.setVisibility(show ? VISIBLE : INVISIBLE);
    }

    /** Selects the tile that is {@code steps} places clockwise from {@code from} (negative: anticlockwise), wrapping all the way round. */
    void moveFocus(View from, int steps) {
        int tiles = getChildCount() - 1;
        if (tiles < 1) return;
        int index = indexOfChild(from) - 1;
        getChildAt(1 + Math.floorMod(index + steps, tiles)).requestFocus();
    }

    /** Takes away every tile and keeps the orb. */
    void clearTiles() {
        removeViews(1, getChildCount() - 1);
    }

    @Override
    protected void onMeasure(int widthSpec, int heightSpec) {
        int w = MeasureSpec.getSize(widthSpec), h = MeasureSpec.getSize(heightSpec);
        tileW = 0;
        tileH = 0;
        for (int i = 1; i < getChildCount(); i++) {
            View tile = getChildAt(i);
            tile.measure(MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED), MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED));
            tileW = Math.max(tileW, tile.getMeasuredWidth());
            tileH = Math.max(tileH, tile.getMeasuredHeight());
        }
        // the orb is as big as fits: its radius reaches the nearest tile (minus a gap)
        int n = getChildCount() - 1;
        float rx = (w - tileW) / 2f - gap, ry = (h - tileH) / 2f - gap;
        float nearest = Math.min(rx, ry);
        for (int i = 0; i < n; i++) {
            double angle = Math.toRadians(-90 + (i + 0.5) * 360.0 / n);
            float dx = Math.max(Math.abs((float) Math.cos(angle) * rx) - tileW / 2f, 0);
            float dy = Math.max(Math.abs((float) Math.sin(angle) * ry) - tileH / 2f, 0);
            nearest = Math.min(nearest, (float) Math.hypot(dx, dy));
        }
        int size = Math.max(0, Math.round((nearest - gap) * 2));
        orb.measure(MeasureSpec.makeMeasureSpec(size, MeasureSpec.EXACTLY), MeasureSpec.makeMeasureSpec(size, MeasureSpec.EXACTLY));
        setMeasuredDimension(w, h);
    }

    @Override
    protected void onLayout(boolean changed, int l, int t, int r, int b) {
        int w = r - l, h = b - t;
        float cx = w / 2f, cy = h / 2f;
        orb.layout(Math.round(cx - orb.getMeasuredWidth() / 2f), Math.round(cy - orb.getMeasuredHeight() / 2f),
                Math.round(cx + orb.getMeasuredWidth() / 2f), Math.round(cy + orb.getMeasuredHeight() / 2f));
        glow.setShader(OrbPainter.glowShader(cx, cy, orb.getMeasuredWidth() / 2f));
        int n = getChildCount() - 1;
        float rx = (w - tileW) / 2f - gap, ry = (h - tileH) / 2f - gap;
        for (int i = 0; i < n; i++) {
            View tile = getChildAt(i + 1);
            double angle = Math.toRadians(-90 + (i + 0.5) * 360.0 / n);
            float x = cx + (float) Math.cos(angle) * rx, y = cy + (float) Math.sin(angle) * ry;
            int tw = tile.getMeasuredWidth(), th = tile.getMeasuredHeight();
            tile.layout(Math.round(x - tw / 2f), Math.round(y - th / 2f), Math.round(x + tw / 2f), Math.round(y + th / 2f));
        }
    }
}
