package dev.jarvis.phone;

import android.content.ContentResolver;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Matrix;
import android.media.ExifInterface;
import android.net.Uri;
import android.os.Build;
import android.util.Base64;

import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;

/**
 * "Share to JARVIS": text, a link or a picture sent from another app's Share menu. The app only reads it and shows a sheet that asks what to do;
 * nothing is sent anywhere until you choose. A picture is shrunk to at most 1920 pixels on its long side and saved again as a plain JPEG
 * (which also drops its location and camera details), which keeps the upload small and quick. Only content:// pictures are read, never file paths.
 */
final class Share {
    static final int MAX_TEXT = 4000;
    static final int MAX_SIDE = 1920;
    private static volatile String pending = "";

    private Share() { }

    static File file(Context c) { return new File(c.getCacheDir(), "share.jpg"); }

    static boolean isShare(Intent i) { return i != null && Intent.ACTION_SEND.equals(i.getAction()); }

    /** Reads what was shared (a picture is processed off the main thread) and calls `done` when it is ready to hand to the page. */
    static void read(Context c, Intent i, Runnable done) {
        final Context app = c.getApplicationContext();
        final String type = String.valueOf(i.getType());
        if (type.startsWith("image/")) {
            final Uri uri = stream(i);
            new Thread(() -> {
                String made = "";
                try {
                    if (uri != null && ContentResolver.SCHEME_CONTENT.equals(uri.getScheme()) && shrink(app, uri)) made = new JSONObject().put("kind", "image").toString();
                } catch (Exception ignored) { }
                if (!made.isEmpty()) pending = made;
                if (!made.isEmpty()) done.run();
            }, "share").start();
            return;
        }
        CharSequence text = i.getCharSequenceExtra(Intent.EXTRA_TEXT);
        if (text == null || text.toString().trim().isEmpty()) text = i.getCharSequenceExtra(Intent.EXTRA_SUBJECT);
        String clean = text == null ? "" : text.toString().trim();
        if (clean.isEmpty()) return;
        if (clean.length() > MAX_TEXT) clean = clean.substring(0, MAX_TEXT);
        try {
            pending = new JSONObject().put("kind", "text").put("text", clean).toString();
        } catch (Exception e) {
            return;
        }
        done.run();
    }

    @SuppressWarnings("deprecation")
    private static Uri stream(Intent i) {
        return Build.VERSION.SDK_INT >= 33 ? i.getParcelableExtra(Intent.EXTRA_STREAM, Uri.class) : (Uri) i.getParcelableExtra(Intent.EXTRA_STREAM);
    }

    /**
     * A picture taken with the phone's camera app for the "Look" button: shrunk and cleaned like a shared picture, and then offered to the page the same way
     * (the page asks what to do with it). The copy the camera app saved in the gallery is deleted straight away, so nothing is left behind.
     */
    static void fromCamera(Context c, Uri uri, Runnable done) {
        final Context app = c.getApplicationContext();
        new Thread(() -> {
            boolean made = false;
            try {
                made = shrink(app, uri);
                if (made) pending = new JSONObject().put("kind", "image").toString();
            } catch (Exception ignored) {
            } finally {
                try { app.getContentResolver().delete(uri, null, null); } catch (Exception ignored) { }
            }
            if (made) done.run();
        }, "look").start();
    }

    /** What the page asks for: the shared item ({kind, text?}) once, or "" when there is nothing. */
    static String take() {
        String p = pending;
        pending = "";
        return p;
    }

    static String imageBase64(Context c) {
        File f = file(c);
        if (!f.isFile() || f.length() > 6_000_000) return "";
        try (InputStream in = new FileInputStream(f)) {
            java.io.ByteArrayOutputStream all = new java.io.ByteArrayOutputStream((int) f.length());
            byte[] buf = new byte[16384];
            for (int n; (n = in.read(buf)) > 0; ) all.write(buf, 0, n);
            return Base64.encodeToString(all.toByteArray(), Base64.NO_WRAP);
        } catch (Exception e) {
            return "";
        }
    }

    static void discard(Context c) { file(c).delete(); }

    private static boolean shrink(Context c, Uri uri) throws Exception {
        ContentResolver cr = c.getContentResolver();
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        try (InputStream in = cr.openInputStream(uri)) { BitmapFactory.decodeStream(in, null, bounds); }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return false;
        int sample = 1;
        while (Math.max(bounds.outWidth, bounds.outHeight) / (sample * 2) >= MAX_SIDE) sample *= 2;      // decode near the target size, never the full photo
        BitmapFactory.Options opts = new BitmapFactory.Options();
        opts.inSampleSize = sample;
        Bitmap raw;
        try (InputStream in = cr.openInputStream(uri)) { raw = BitmapFactory.decodeStream(in, null, opts); }
        if (raw == null) return false;

        int orientation = ExifInterface.ORIENTATION_NORMAL;
        try (InputStream in = cr.openInputStream(uri)) { orientation = new ExifInterface(in).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL); } catch (Exception ignored) { }
        Matrix m = new Matrix();
        switch (orientation) {
            case ExifInterface.ORIENTATION_ROTATE_90: m.postRotate(90); break;
            case ExifInterface.ORIENTATION_ROTATE_180: m.postRotate(180); break;
            case ExifInterface.ORIENTATION_ROTATE_270: m.postRotate(270); break;
            case ExifInterface.ORIENTATION_FLIP_HORIZONTAL: m.postScale(-1, 1); break;
            case ExifInterface.ORIENTATION_FLIP_VERTICAL: m.postScale(1, -1); break;
            default: break;
        }
        float scale = Math.min(1f, (float) MAX_SIDE / Math.max(raw.getWidth(), raw.getHeight()));
        m.postScale(scale, scale);
        Bitmap turned = Bitmap.createBitmap(raw, 0, 0, raw.getWidth(), raw.getHeight(), m, true);
        Bitmap flat = Bitmap.createBitmap(turned.getWidth(), turned.getHeight(), Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(flat);
        canvas.drawColor(Color.WHITE);                                  // a transparent PNG would turn black as a JPEG
        canvas.drawBitmap(turned, 0, 0, null);
        try (FileOutputStream out = new FileOutputStream(file(c))) { flat.compress(Bitmap.CompressFormat.JPEG, 85, out); }
        if (turned != raw) raw.recycle();
        turned.recycle();
        flat.recycle();
        return true;
    }
}
