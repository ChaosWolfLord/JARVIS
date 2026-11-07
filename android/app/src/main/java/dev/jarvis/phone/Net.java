package dev.jarvis.phone;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

/**
 * What the standalone assistant needs from the network, done here so the page never touches the AI keys and cannot be talked into
 * reaching things on the home network:
 *  - the AI keys (copied from the PC once) live in the app's private storage and are only ever sent to the AI services they came with;
 *  - llm() asks the services in order and moves on to the next when one is busy or down;
 *  - web() reads a public web page (https only; never this phone's own network, never a private address).
 */
final class Net {
    private Net() { }

    static final String[] AI_HOSTS = {"generativelanguage.googleapis.com", "api.groq.com", "openrouter.ai"};
    private static final int MAX_BODY = 400_000;
    private static final Map<String, Long> cooling = new HashMap<>();        // provider:model -> time it may be tried again

    private static SharedPreferences prefs(Context c) { return c.getSharedPreferences("jarvis", Context.MODE_PRIVATE); }

    // ---- the AI keys -------------------------------------------------------------------------------------------------
    /** Saves the services the PC sent: [{provider, model, base_url, key}]. Only the known AI hosts are accepted. Returns how many. */
    static int importKeys(Context c, String json) {
        try {
            JSONArray in = new JSONArray(json), out = new JSONArray();
            for (int i = 0; i < in.length() && out.length() < 8; i++) {
                JSONObject p = in.getJSONObject(i);
                String base = p.getString("base_url");
                String host = new URL(base).getHost();
                boolean known = false;
                for (String h : AI_HOSTS) if (h.equals(host)) known = true;
                if (!known || !base.startsWith("https://") || p.getString("key").length() < 8 || p.getString("model").isEmpty()) continue;
                out.put(new JSONObject().put("provider", p.getString("provider")).put("model", p.getString("model")).put("base_url", base).put("key", p.getString("key")));
            }
            prefs(c).edit().putString("ai", out.toString()).apply();
            return out.length();
        } catch (Exception e) {
            return 0;
        }
    }

    private static JSONArray providers(Context c) {
        try { return new JSONArray(prefs(c).getString("ai", "[]")); } catch (JSONException e) { return new JSONArray(); }
    }

    static int keyCount(Context c) { return providers(c).length(); }

    /** The models that are ready, without their keys: ["gemini: gemini-3.6-flash", ...]. */
    static String modelNames(Context c) {
        JSONArray names = new JSONArray();
        JSONArray p = providers(c);
        for (int i = 0; i < p.length(); i++) names.put(p.optJSONObject(i).optString("provider") + ": " + p.optJSONObject(i).optString("model"));
        return names.toString();
    }

    static void clearKeys(Context c) { prefs(c).edit().remove("ai").apply(); }

    // ---- the AI call --------------------------------------------------------------------------------------------------
    /** Sends one chat request ({messages, tools, ...} in the OpenAI format) to the first service that answers. Returns {ok, body|error, model}. */
    static String llm(Context c, String requestJson) {
        JSONArray list = providers(c);
        if (list.length() == 0) return fail("No AI keys on this phone yet. Open the app while it is connected to your PC and copy them (menu, AI keys).");
        String lastError = "";
        long now = System.currentTimeMillis();
        for (int pass = 0; pass < 2; pass++) {                       // second pass tries the ones that were cooling, if nothing else worked
            for (int i = 0; i < list.length(); i++) {
                JSONObject p = list.optJSONObject(i);
                String key = p.optString("provider") + ":" + p.optString("model");
                Long until = cooling.get(key);
                if (pass == 0 && until != null && until > now) continue;
                try {
                    JSONObject body = new JSONObject(requestJson);
                    body.put("model", p.getString("model"));
                    body.put("stream", false);
                    String url = p.getString("base_url").replaceAll("/+$", "") + "/chat/completions";
                    HttpURLConnection h = (HttpURLConnection) new URL(url).openConnection();
                    h.setRequestMethod("POST");
                    h.setConnectTimeout(15_000);
                    h.setReadTimeout(60_000);
                    h.setDoOutput(true);
                    h.setRequestProperty("Content-Type", "application/json");
                    h.setRequestProperty("Authorization", "Bearer " + p.getString("key"));
                    try (OutputStream o = h.getOutputStream()) { o.write(body.toString().getBytes(StandardCharsets.UTF_8)); }
                    int code = h.getResponseCode();
                    String text = read(code >= 400 ? h.getErrorStream() : h.getInputStream(), MAX_BODY);
                    h.disconnect();
                    if (code == 200) return new JSONObject().put("ok", true).put("body", text).put("model", key).toString();
                    lastError = key + " answered " + code;
                    cooling.put(key, System.currentTimeMillis() + (code == 429 ? 90_000 : 20_000));
                } catch (Exception e) {
                    lastError = key + ": " + e.getClass().getSimpleName();
                    cooling.put(key, System.currentTimeMillis() + 20_000);
                }
            }
        }
        return fail("The AI services didn't answer (" + lastError + "). Check the phone's internet connection, or try again in a minute.");
    }

    private static String fail(String message) {
        try { return new JSONObject().put("ok", false).put("error", message).toString(); } catch (JSONException e) { return "{\"ok\":false}"; }
    }

    // ---- reading a public web page --------------------------------------------------------------------------------------
    private static boolean publicHost(String host) {
        try {
            for (InetAddress a : InetAddress.getAllByName(host)) {
                if (a.isAnyLocalAddress() || a.isLoopbackAddress() || a.isLinkLocalAddress() || a.isSiteLocalAddress() || a.isMulticastAddress()) return false;
                byte[] b = a.getAddress();
                if (b.length == 4 && (b[0] & 0xff) == 100 && (b[1] & 0xc0) == 0x40) return false;           // 100.64.0.0/10 (carrier-grade NAT, Tailscale)
                if (b.length == 16 && (b[0] & 0xfe) == 0xfc) return false;                                   // fc00::/7 unique local
            }
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    /** GETs an https page and returns {ok, status, url, text} (text capped). Redirects are followed by hand, each one checked again. */
    static String web(String start) {
        try {
            String url = start;
            for (int hop = 0; hop < 5; hop++) {
                URL u = new URL(url);
                if (!"https".equals(u.getProtocol()) || u.getUserInfo() != null || !publicHost(u.getHost())) return fail("That address isn't a public web page.");
                HttpURLConnection h = (HttpURLConnection) u.openConnection();
                h.setInstanceFollowRedirects(false);
                h.setConnectTimeout(10_000);
                h.setReadTimeout(15_000);
                h.setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 14) JARVIS-phone/1.2");
                h.setRequestProperty("Accept", "text/html,text/plain,application/json;q=0.9,*/*;q=0.5");
                int code = h.getResponseCode();
                if (code >= 300 && code < 400 && h.getHeaderField("Location") != null) {
                    url = new URL(u, h.getHeaderField("Location")).toString();
                    h.disconnect();
                    continue;
                }
                String type = String.valueOf(h.getContentType()).toLowerCase();
                if (code != 200) { h.disconnect(); return fail("The page answered HTTP " + code + "."); }
                if (!(type.contains("text") || type.contains("json") || type.contains("xml"))) { h.disconnect(); return fail("That isn't a text page."); }
                String text = read(h.getInputStream(), MAX_BODY);
                h.disconnect();
                return new JSONObject().put("ok", true).put("status", code).put("url", url).put("text", text).toString();
            }
            return fail("Too many redirects.");
        } catch (Exception e) {
            return fail("Could not read that page (" + e.getClass().getSimpleName() + ").");
        }
    }

    private static String read(InputStream in, int max) throws IOException {
        if (in == null) return "";
        try (InputStream s = in) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = s.read(buf)) > 0 && out.size() < max) out.write(buf, 0, Math.min(n, max - out.size()));
            return out.toString("UTF-8");
        }
    }
}
