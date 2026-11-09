package dev.jarvis.phone;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URL;
import java.util.regex.Pattern;

import javax.net.ssl.HttpsURLConnection;

/**
 * Looks for a newer version of the app on the project's GitHub releases page. It only asks GitHub (one fixed address, over HTTPS, with
 * the phone's normal certificate checks) and only ever offers a file from that project's own release downloads. Nothing about the phone is sent.
 * It never installs anything by itself: the person opens the downloaded file, and Android refuses it unless it is signed with the same key.
 */
final class Updates {
    private Updates() { }

    static final String REPO = "ChaosWolfLord/JARVIS";
    static final String API = "https://api.github.com/repos/" + REPO + "/releases/latest";
    static final String DOWNLOADS = "https://github.com/" + REPO + "/releases/download/";
    static final long EVERY = 12L * 60 * 60 * 1000;                       // at most twice a day, unless asked
    private static final Pattern VERSION = Pattern.compile("^\\d{1,3}(\\.\\d{1,3}){1,3}$");

    static final class Found {
        final String version, url, notes;

        Found(String version, String url, String notes) {
            this.version = version;
            this.url = url;
            this.notes = notes;
        }
    }

    /** The newer release, or null if this is the newest (or the release isn't usable). Throws when GitHub can't be reached. */
    static Found check(String installed) throws Exception {
        HttpsURLConnection c = (HttpsURLConnection) new URL(API).openConnection();
        c.setConnectTimeout(6000);
        c.setReadTimeout(8000);
        c.setInstanceFollowRedirects(false);
        c.setRequestProperty("Accept", "application/vnd.github+json");
        c.setRequestProperty("User-Agent", "JARVIS-app");
        try {
            int code = c.getResponseCode();
            if (code == 404) return null;                                  // no release published yet
            if (code != 200) throw new IOException("GitHub answered " + code);
            return parse(read(c.getInputStream()), installed);
        } finally {
            c.disconnect();
        }
    }

    static Found parse(String body, String installed) throws Exception {
        JSONObject release = new JSONObject(body);
        if (release.optBoolean("draft") || release.optBoolean("prerelease")) return null;
        String version = release.optString("tag_name", "").replaceFirst("^v", "");
        if (!VERSION.matcher(version).matches() || compare(version, installed) <= 0) return null;
        JSONArray assets = release.optJSONArray("assets");
        if (assets == null) return null;
        for (int i = 0; i < assets.length(); i++) {
            JSONObject a = assets.getJSONObject(i);
            String url = a.optString("browser_download_url", "");
            if ("jarvis.apk".equals(a.optString("name")) && url.startsWith(DOWNLOADS) && !url.contains("..")) {
                String notes = release.optString("body", "").replaceAll("(?s)\\s*SHA-256.*$", "").trim();
                return new Found(version, url, notes.length() > 400 ? notes.substring(0, 400) + "…" : notes);
            }
        }
        return null;
    }

    /** Negative, zero or positive as a is older than, the same as, or newer than b ("1.10" is newer than "1.9"). */
    static int compare(String a, String b) {
        String[] x = a.split("\\."), y = b.split("\\.");
        for (int i = 0; i < Math.max(x.length, y.length); i++) {
            int p = i < x.length ? number(x[i]) : 0, q = i < y.length ? number(y[i]) : 0;
            if (p != q) return Integer.compare(p, q);
        }
        return 0;
    }

    private static int number(String s) {
        try {
            return Integer.parseInt(s.replaceAll("\\D", ""));
        } catch (NumberFormatException e) {
            return 0;
        }
    }

    private static String read(InputStream in) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) {
            out.write(buf, 0, n);
            if (out.size() > 300_000) throw new IOException("the answer was too long");
        }
        return out.toString("UTF-8");
    }
}
