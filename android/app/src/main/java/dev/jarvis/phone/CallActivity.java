package dev.jarvis.phone;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * "JARVIS is calling": the screen a reminder call opens (over the lock screen where the phone allows it). Answer, and JARVIS says the reminder out
 * loud and listens for a reply: "thanks" ends the call, "snooze" or "remind me in 20 minutes" calls again later, and anything else is a short
 * conversation with the AI keys already on this phone. It needs neither the PC nor a phone number, and it only rings when the phone's ringer
 * and Do Not Disturb let a notification ring: this screen never plays a ringtone or touches the volume of its own.
 */
public class CallActivity extends Activity {
    private String id = "", text = "";
    private TextToSpeech tts;
    private boolean ttsReady = false, answered = false, ended = false, wantsToSpeak = false;
    private SpeechRecognizer recognizer;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ArrayList<String[]> talk = new ArrayList<>();     // {role, text} of this call, for the AI
    private int quiet = 0;                                          // replies in a row that were not heard
    private TextView title, line, hint;
    private Button answerBtn, declineBtn, snoozeBtn;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        setShowWhenLocked(true);
        setTurnScreenOn(true);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        build();
        read(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        read(intent);
    }

    private void read(Intent i) {
        String newId = i.getStringExtra("id");
        if (newId != null && !newId.equals(id)) { id = newId; text = Reminders.clean(i.getStringExtra("text")); }
        if (i.getBooleanExtra("answer", false) && !answered) answer();
    }

    private void build() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setBackgroundColor(0xFF080A10);
        int pad = dp(28);
        root.setPadding(pad, dp(72), pad, dp(48));

        TextView name = label("JARVIS", 38, 0xFFEAF2FF, true);
        title = label("is calling…", 18, 0xFF8FA3C4, false);
        line = label("", 20, 0xFFEAF2FF, false);
        line.setGravity(Gravity.CENTER);
        line.setPadding(0, dp(36), 0, 0);
        hint = label("", 14, 0xFF8FA3C4, false);
        hint.setPadding(0, dp(20), 0, 0);
        hint.setGravity(Gravity.CENTER);

        View gap = new View(this);
        LinearLayout buttons = new LinearLayout(this);
        buttons.setOrientation(LinearLayout.HORIZONTAL);
        buttons.setGravity(Gravity.CENTER);
        declineBtn = round("Decline", 0xFFD64545);
        answerBtn = round("Answer", 0xFF2FA866);
        declineBtn.setOnClickListener((v) -> hangUp());
        answerBtn.setOnClickListener((v) -> answer());
        LinearLayout.LayoutParams each = new LinearLayout.LayoutParams(dp(112), dp(112));
        each.setMargins(dp(28), 0, dp(28), 0);
        buttons.addView(declineBtn, each);
        buttons.addView(answerBtn, each);

        snoozeBtn = new Button(this);
        snoozeBtn.setText("Call me again in 10 minutes");
        snoozeBtn.setAllCaps(false);
        snoozeBtn.setTextColor(0xFFEAF2FF);
        snoozeBtn.setBackground(rounded(0xFF1B2433, dp(24)));
        snoozeBtn.setVisibility(View.GONE);
        snoozeBtn.setOnClickListener((v) -> snooze(10));

        root.addView(name);
        root.addView(title);
        root.addView(line);
        root.addView(hint);
        root.addView(gap, new LinearLayout.LayoutParams(1, 0, 1f));
        LinearLayout.LayoutParams wide = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(52));
        wide.setMargins(0, 0, 0, dp(18));
        root.addView(snoozeBtn, wide);
        root.addView(buttons);
        setContentView(root);
    }

    private int dp(int v) { return Math.round(v * getResources().getDisplayMetrics().density); }

    private TextView label(String s, int sp, int colour, boolean bold) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(colour);
        t.setGravity(Gravity.CENTER);
        if (bold) t.setTypeface(Typeface.DEFAULT_BOLD);
        return t;
    }

    private GradientDrawable rounded(int colour, int radius) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(colour);
        d.setCornerRadius(radius);
        return d;
    }

    private Button round(String s, int colour) {
        Button b = new Button(this);
        b.setText(s);
        b.setAllCaps(false);
        b.setTextColor(Color.WHITE);
        b.setBackground(rounded(colour, dp(56)));
        return b;
    }

    // ---- the call ----------------------------------------------------------------------------------------------------------
    private void answer() {
        if (answered || ended) return;
        answered = true;
        Notify.endCall(this, id);                       // stops the ringing
        Notify.clearReminder(this, id);
        title.setText("Connected");
        line.setText(text);
        answerBtn.setVisibility(View.GONE);
        declineBtn.setText("Hang up");
        snoozeBtn.setVisibility(View.VISIBLE);
        tts = new TextToSpeech(this, (status) -> {
            ttsReady = status == TextToSpeech.SUCCESS;
            if (ttsReady) {
                tts.setLanguage(Locale.getDefault());
                tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                    @Override public void onStart(String utteranceId) { }
                    @Override public void onError(String utteranceId) { ui.post(() -> doneSpeaking()); }
                    @Override public void onDone(String utteranceId) { ui.post(() -> doneSpeaking()); }
                });
                speak("Hi, it's JARVIS. A reminder: " + text + ". Say thanks to finish, or tell me to call you back later.");
            } else {
                hint.setText("This phone has no voice to read it out. The reminder is above.");
            }
        });
    }

    private void speak(String s) {
        if (!ttsReady || ended) return;
        wantsToSpeak = true;
        hint.setText("JARVIS is speaking…");
        tts.speak(s, TextToSpeech.QUEUE_FLUSH, null, "jarvis-call");
    }

    private void doneSpeaking() {
        if (ended) return;
        wantsToSpeak = false;
        if (goodbye) { hangUp(); return; }
        listen();
    }

    private boolean goodbye = false;

    private void listen() {
        if (ended || !answered) return;
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED || !SpeechRecognizer.isRecognitionAvailable(this)) {
            hint.setText("Tap a button to reply.");
            return;
        }
        if (recognizer == null) {
            recognizer = SpeechRecognizer.createSpeechRecognizer(this);
            recognizer.setRecognitionListener(new RecognitionListener() {
                @Override public void onReadyForSpeech(Bundle b) { hint.setText("Listening…"); }
                @Override public void onBeginningOfSpeech() { }
                @Override public void onRmsChanged(float v) { }
                @Override public void onBufferReceived(byte[] b) { }
                @Override public void onEndOfSpeech() { }
                @Override public void onPartialResults(Bundle b) { }
                @Override public void onEvent(int t, Bundle b) { }
                @Override public void onError(int error) {
                    if (ended) return;
                    quiet++;
                    if (quiet >= 2) { hint.setText("Tap a button to reply."); return; }
                    ui.postDelayed(CallActivity.this::listen, 400);
                }
                @Override public void onResults(Bundle b) {
                    ArrayList<String> r = b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                    if (r == null || r.isEmpty()) { onError(SpeechRecognizer.ERROR_NO_MATCH); return; }
                    quiet = 0;
                    heard(r.get(0));
                }
            });
        }
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault().toLanguageTag());
        recognizer.startListening(i);
    }

    private static final Pattern AMOUNT = Pattern.compile("(\\d+|an?|half an?|one|two|three|five|ten|fifteen|twenty|thirty)\\s*(minutes?|mins?|hours?|hrs?)");

    /** How many minutes the person asked to wait ("in 20 minutes", "an hour", "half an hour"), or 10 when they just said later/snooze. */
    static int minutesIn(String said) {
        Matcher m = AMOUNT.matcher(said);
        if (!m.find()) return 10;
        String n = m.group(1);
        boolean hour = m.group(2).startsWith("h");
        double v;
        switch (n) {
            case "a": case "an": case "one": v = 1; break;
            case "half a": case "half an": v = 0.5; break;
            case "two": v = 2; break;
            case "three": v = 3; break;
            case "five": v = 5; break;
            case "ten": v = 10; break;
            case "fifteen": v = 15; break;
            case "twenty": v = 20; break;
            case "thirty": v = 30; break;
            default: try { v = Double.parseDouble(n); } catch (NumberFormatException e) { v = 10; }
        }
        int minutes = (int) Math.round(hour ? v * 60 : v);
        return Math.max(1, Math.min(minutes, 24 * 60));
    }

    static boolean isThanks(String said) {
        return said.matches(".*\\b(thanks|thank you|okay|ok|got it|bye|goodbye|that's all|that is all|done|no)\\b.*") && !isSnooze(said);
    }

    static boolean isSnooze(String said) {
        return said.matches(".*\\b(snooze|later|again|call me back|remind me|call back)\\b.*");
    }

    private void heard(String said) {
        String s = said.toLowerCase(Locale.ROOT).trim();
        hint.setText("“" + said + "”");
        if (isSnooze(s)) { int min = minutesIn(s); snoozeThenBye(min); return; }
        if (isThanks(s) && s.split("\\s+").length <= 6) { goodbye = true; speak("You're welcome. Goodbye."); return; }
        talk.add(new String[]{"user", said});
        hint.setText("Thinking…");
        new Thread(() -> {
            String reply = ask();
            ui.post(() -> {
                if (ended) return;
                if (reply.isEmpty()) { goodbye = true; speak("Sorry, I can't answer that right now. Goodbye."); return; }
                talk.add(new String[]{"assistant", reply});
                line.setText(reply);
                speak(reply);
            });
        }, "call-ai").start();
    }

    /** One short answer from the AI keys on this phone, or "" when they are missing or nothing answered. */
    private String ask() {
        try {
            JSONArray messages = new JSONArray();
            messages.put(new JSONObject().put("role", "system").put("content",
                    "You are JARVIS, speaking to the user on a phone call that began with this reminder: \"" + text + "\". Answer in one or two short spoken sentences, no lists or markdown."));
            for (String[] t : talk) messages.put(new JSONObject().put("role", t[0]).put("content", t[1]));
            JSONObject out = new JSONObject(Net.llm(this, new JSONObject().put("messages", messages).put("max_tokens", 160).toString()));
            if (!out.optBoolean("ok")) return "";
            String content = new JSONObject(out.getString("body")).getJSONArray("choices").getJSONObject(0).getJSONObject("message").optString("content", "");
            return content.replaceAll("[*_#`]", "").trim();
        } catch (Exception e) {
            return "";
        }
    }

    private void snoozeThenBye(int minutes) {
        String problem = Reminders.add(this, text, System.currentTimeMillis() + minutes * 60_000L);
        goodbye = true;
        if (problem.isEmpty()) {
            String when = minutes % 60 == 0 && minutes >= 60 ? (minutes / 60) + (minutes == 60 ? " hour" : " hours") : minutes + (minutes == 1 ? " minute" : " minutes");
            line.setText("I'll call again in " + when + ".");
            speak("Okay, I'll call you again in " + when + ". Goodbye.");
        } else {
            speak("Sorry. " + problem);
        }
        if (!ttsReady) hangUp();
    }

    private void snooze(int minutes) {
        if (recognizer != null) recognizer.cancel();
        if (ttsReady) tts.stop();
        snoozeThenBye(minutes);
    }

    private void hangUp() {
        if (ended) return;
        ended = true;
        Notify.endCall(this, id);                       // a declined call keeps the quiet copy of the reminder in the list
        if (answered) Notify.clearReminder(this, id);
        finish();
    }

    @Override
    protected void onDestroy() {
        ended = true;
        ui.removeCallbacksAndMessages(null);
        if (recognizer != null) { recognizer.destroy(); recognizer = null; }
        if (tts != null) { tts.stop(); tts.shutdown(); tts = null; }
        super.onDestroy();
    }
}
