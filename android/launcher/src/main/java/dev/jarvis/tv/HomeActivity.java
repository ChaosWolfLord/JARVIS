package dev.jarvis.tv;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.GridLayout;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextClock;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * JARVIS Home: the projector's home screen. A clock, a row of pinned apps (JARVIS first) and every other app below it,
 * all reachable with the remote's arrow keys and OK. Long-press OK (or press Menu) on an app for pin, hide, app info and uninstall.
 */
public class HomeActivity extends Activity {
    // Two buttons that are not apps: HDMI (shows whatever is plugged into the projector's HDMI socket) and USB (the file manager, which lists a plugged-in drive).
    static final String HDMI = "tv:hdmi";
    static final String USB = "tv:usb";
    private static final String FILE_MANAGER = "com.hisilicon.explorer";
    private static final String[] DEFAULT_PINNED = {HDMI, "com.htc.magcubicos", "com.softwinner.awsource", "com.android.tv.settings", "com.android.vending", FILE_MANAGER};
    // The factory test menu (nothing to do there) and Google's touch-screen "Files" app: it can't be steered with arrow keys, and the
    // projector already has its own remote-friendly file manager (the pinned "Files"). "Hidden apps..." in the options brings either back.
    private static final String[] DEFAULT_HIDDEN = {"com.softwinner.tv.factorymenu", "com.android.documentsui"};
    private static final Map<String, String> NAMES = new LinkedHashMap<>();
    static {
        NAMES.put("com.htc.magcubicos", "Projector menu");      // the projector's own screen: keystone, focus, picture settings
        NAMES.put("com.softwinner.awsource", "Inputs");          // HDMI / AV sources
        NAMES.put("com.android.tv.settings", "Settings");
        NAMES.put("com.hisilicon.explorer", "Files");
        NAMES.put("com.android.vending", "Play Store");
    }

    /** What one app is. */
    private static final class App {
        String pkg;
        String label;
        ResolveInfo info;        // the icon is only loaded (and shrunk to the tile's size) for apps that are actually shown; null for the HDMI and USB buttons
        boolean system;
    }

    private String lastFocus;    // which app was selected when the screen was released, so it can be selected again
    private SharedPreferences prefs;
    private float density;
    private LinearLayout pinnedRow;
    private GridLayout grid;
    private ScrollView scroll;
    private List<App> everyApp = new ArrayList<>();
    private final BroadcastReceiver packagesChanged = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            refresh();
        }
    };

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("home", MODE_PRIVATE);
        density = getResources().getDisplayMetrics().density;

        FrameLayout root = new FrameLayout(this);
        root.addView(new Backdrop(this), new FrameLayout.LayoutParams(-1, -1));

        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(dp(44), dp(22), dp(44), 0);
        root.addView(page, new FrameLayout.LayoutParams(-1, -1));

        page.addView(header());

        scroll = new ScrollView(this);
        scroll.setVerticalScrollBarEnabled(false);
        scroll.setClipChildren(false);
        scroll.setClipToPadding(false);
        scroll.setPadding(0, dp(4), 0, dp(24));
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setClipChildren(false);
        scroll.addView(body);
        page.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1f));

        body.addView(sectionLabel("PINNED"));
        HorizontalScrollView pinnedScroll = new HorizontalScrollView(this);
        pinnedScroll.setHorizontalScrollBarEnabled(false);
        pinnedScroll.setClipChildren(false);
        pinnedScroll.setClipToPadding(false);
        pinnedScroll.setPadding(dp(6), dp(8), dp(6), dp(12));
        pinnedRow = new LinearLayout(this);
        pinnedRow.setClipChildren(false);
        pinnedScroll.addView(pinnedRow);
        body.addView(pinnedScroll);

        body.addView(sectionLabel("ALL APPS"));
        grid = new GridLayout(this);
        grid.setColumnCount(6);
        grid.setClipChildren(false);
        grid.setPadding(dp(6), dp(8), dp(6), dp(12));
        body.addView(grid);

        setContentView(root);
        refresh();
    }

    private View header() {
        LinearLayout bar = new LinearLayout(this);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setPadding(0, 0, 0, dp(6));

        TextView mark = new TextView(this);
        mark.setText("J.A.R.V.I.S");
        mark.setTextColor(0xFF3FD8FF);
        mark.setTextSize(22);
        mark.setTypeface(Typeface.create("sans-serif-light", Typeface.BOLD));
        mark.setLetterSpacing(0.25f);
        bar.addView(mark, new LinearLayout.LayoutParams(0, -2, 1f));

        LinearLayout when = new LinearLayout(this);
        when.setOrientation(LinearLayout.VERTICAL);
        when.setGravity(Gravity.END);
        TextClock time = new TextClock(this);
        time.setFormat12Hour("h:mm a");
        time.setFormat24Hour("HH:mm");
        time.setTextColor(Color.WHITE);
        time.setTextSize(26);
        time.setGravity(Gravity.END);
        TextClock date = new TextClock(this);
        date.setFormat12Hour("EEEE, MMMM d");
        date.setFormat24Hour("EEEE, MMMM d");
        date.setTextColor(0xFF8FA6B8);
        date.setTextSize(13);
        date.setGravity(Gravity.END);
        when.addView(time);
        when.addView(date);
        bar.addView(when);
        return bar;
    }

    private TextView sectionLabel(String text) {
        TextView label = new TextView(this);
        label.setText(text);
        label.setTextColor(0xFF5E7A90);
        label.setTextSize(11);
        label.setLetterSpacing(0.2f);
        label.setPadding(dp(8), dp(10), 0, 0);
        return label;
    }

    // ---- the list of apps -------------------------------------------------------------------------------------

    private List<App> queryApps() {
        PackageManager pm = getPackageManager();
        Map<String, App> found = new LinkedHashMap<>();
        for (String category : new String[]{Intent.CATEGORY_LEANBACK_LAUNCHER, Intent.CATEGORY_LAUNCHER}) {
            for (ResolveInfo info : pm.queryIntentActivities(new Intent(Intent.ACTION_MAIN).addCategory(category), 0)) {
                String pkg = info.activityInfo.packageName;
                if (pkg.equals(getPackageName()) || found.containsKey(pkg)) continue;
                App app = new App();
                app.pkg = pkg;
                String custom = NAMES.get(pkg);
                app.label = custom != null ? custom : String.valueOf(info.loadLabel(pm));
                app.info = info;
                app.system = (info.activityInfo.applicationInfo.flags & ApplicationInfo.FLAG_SYSTEM) != 0;
                found.put(pkg, app);
            }
        }
        List<App> apps = new ArrayList<>(found.values());
        Collections.sort(apps, (a, b) -> a.label.toLowerCase(Locale.ROOT).compareTo(b.label.toLowerCase(Locale.ROOT)));
        apps.add(0, button(USB, "USB"));
        apps.add(0, button(HDMI, "HDMI"));
        return apps;
    }

    private App button(String key, String label) {
        App app = new App();
        app.pkg = key;
        app.label = label;
        return app;
    }

    private List<String> pinnedKeys() {
        String saved = prefs.getString("pinned", null);
        return new ArrayList<>(saved == null ? Arrays.asList(DEFAULT_PINNED) : (saved.isEmpty() ? new ArrayList<String>() : Arrays.asList(saved.split(","))));
    }

    private void savePinned(List<String> keys) {
        prefs.edit().putString("pinned", String.join(",", keys)).apply();
    }

    private Set<String> hiddenKeys() {
        Set<String> saved = prefs.getStringSet("hidden", null);
        return new HashSet<>(saved == null ? new HashSet<>(Arrays.asList(DEFAULT_HIDDEN)) : saved);
    }

    private void saveHidden(Set<String> keys) {
        prefs.edit().putStringSet("hidden", keys).apply();
    }

    private void refresh() {
        String focused = getCurrentFocus() instanceof Tile ? ((Tile) getCurrentFocus()).key : lastFocus;
        lastFocus = null;
        everyApp = queryApps();
        Map<String, App> byPkg = new LinkedHashMap<>();
        for (App a : everyApp) byPkg.put(a.pkg, a);
        Set<String> hidden = hiddenKeys();
        List<String> pinned = pinnedKeys();

        pinnedRow.removeAllViews();
        grid.removeAllViews();
        Tile first = null, wanted = null;
        for (String key : pinned) {
            App app = byPkg.get(key);
            if (app == null) continue;
            Tile tile = tile(app, 112, 104, 52);              // six of these (plus their margins) fill the width of a 16:9 screen
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
            lp.setMargins(dp(6), 0, dp(6), 0);
            pinnedRow.addView(tile, lp);
            if (first == null) first = tile;
            if (key.equals(focused)) wanted = tile;
        }
        for (App app : everyApp) {
            if (pinned.contains(app.pkg) || hidden.contains(app.pkg)) continue;
            Tile tile = tile(app, 108, 92, 44);
            GridLayout.LayoutParams lp = new GridLayout.LayoutParams();
            lp.setMargins(dp(6), dp(6), dp(6), dp(6));
            grid.addView(tile, lp);
            if (first == null) first = tile;
            if (app.pkg.equals(focused)) wanted = tile;
        }
        final Tile target = wanted != null ? wanted : first;
        if (target != null) target.post(target::requestFocus);
    }

    /** An app's icon drawn once into a bitmap exactly as big as it is shown (apps' own icons can be 512 pixels wide: about 1 MB each). */
    private Drawable smallIcon(App app, int sizeDp) {
        int px = dp(sizeDp);
        if (app.info == null) return new android.graphics.drawable.BitmapDrawable(getResources(), Glyphs.draw(app.pkg, px));
        Drawable full = app.info.loadIcon(getPackageManager());
        android.graphics.Bitmap bitmap = android.graphics.Bitmap.createBitmap(px, px, android.graphics.Bitmap.Config.ARGB_8888);
        full.setBounds(0, 0, px, px);
        full.draw(new android.graphics.Canvas(bitmap));
        return new android.graphics.drawable.BitmapDrawable(getResources(), bitmap);
    }

    private Tile tile(App app, int w, int h, int icon) {
        Tile tile = new Tile(this, app.pkg, app.label, smallIcon(app, icon), w, h, icon, density);
        tile.setOnClickListener(v -> open(app));
        tile.setOnLongClickListener(v -> {
            options(app);
            return true;
        });
        return tile;
    }

    // ---- opening and options ----------------------------------------------------------------------------------

    private void open(App app) {
        Intent launch;
        if (app.pkg.equals(HDMI)) {
            launch = Hdmi.intent();
        } else {
            String pkg = app.pkg.equals(USB) ? FILE_MANAGER : app.pkg;
            launch = getPackageManager().getLeanbackLaunchIntentForPackage(pkg);
            if (launch == null) launch = getPackageManager().getLaunchIntentForPackage(pkg);
        }
        try {
            if (launch == null) throw new ActivityNotFoundException();
            launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
            startActivity(launch);
        } catch (ActivityNotFoundException | SecurityException e) {
            Toast.makeText(this, app.label + " can't be opened", Toast.LENGTH_SHORT).show();
        }
    }

    private void options(App app) {
        List<String> pinned = pinnedKeys();
        boolean isPinned = pinned.contains(app.pkg);
        List<String> labels = new ArrayList<>();
        List<Runnable> actions = new ArrayList<>();

        labels.add(isPinned ? "Unpin from the top row" : "Pin to the top row");
        actions.add(() -> {
            if (isPinned) pinned.remove(app.pkg); else pinned.add(app.pkg);
            savePinned(pinned);
            refresh();
        });
        if (isPinned && pinned.indexOf(app.pkg) > 0) {
            labels.add("Move left");
            actions.add(() -> {
                int i = pinned.indexOf(app.pkg);
                Collections.swap(pinned, i, i - 1);
                savePinned(pinned);
                refresh();
            });
        }
        if (isPinned && pinned.indexOf(app.pkg) < pinned.size() - 1) {
            labels.add("Move right");
            actions.add(() -> {
                int i = pinned.indexOf(app.pkg);
                Collections.swap(pinned, i, i + 1);
                savePinned(pinned);
                refresh();
            });
        }
        labels.add("Hide from the list");
        actions.add(() -> {
            Set<String> hidden = hiddenKeys();
            hidden.add(app.pkg);
            saveHidden(hidden);
            if (isPinned) {
                pinned.remove(app.pkg);
                savePinned(pinned);
            }
            refresh();
        });
        if (app.info != null) {                                       // the HDMI and USB buttons are not apps
            labels.add("App info");
            actions.add(() -> {
                try {
                    startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + app.pkg)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                } catch (ActivityNotFoundException | SecurityException e) {
                    Toast.makeText(this, "This projector has no app info screen", Toast.LENGTH_SHORT).show();
                }
            });
            if (!app.system) {
                labels.add("Uninstall");
                actions.add(() -> {
                    try {
                        startActivity(new Intent(Intent.ACTION_DELETE, Uri.parse("package:" + app.pkg)));
                    } catch (ActivityNotFoundException | SecurityException e) {
                        Toast.makeText(this, "This projector can't uninstall it from here", Toast.LENGTH_SHORT).show();
                    }
                });
            }
        }
        labels.add("Hidden apps...");
        actions.add(this::hiddenDialog);
        labels.add("Reset pinned apps");
        actions.add(() -> {
            prefs.edit().remove("pinned").apply();
            refresh();
        });

        new AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog_Alert)
                .setTitle(app.label)
                .setItems(labels.toArray(new String[0]), (d, which) -> actions.get(which).run())
                .show();
    }

    private void hiddenDialog() {
        Set<String> hidden = hiddenKeys();
        List<App> candidates = new ArrayList<>();
        for (App a : everyApp) if (hidden.contains(a.pkg)) candidates.add(a);
        if (candidates.isEmpty()) {
            Toast.makeText(this, "No apps are hidden", Toast.LENGTH_SHORT).show();
            return;
        }
        String[] names = new String[candidates.size()];
        boolean[] shown = new boolean[candidates.size()];
        for (int i = 0; i < names.length; i++) names[i] = candidates.get(i).label;
        new AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog_Alert)
                .setTitle("Tick the apps to show again")
                .setMultiChoiceItems(names, shown, (d, which, checked) -> shown[which] = checked)
                .setPositiveButton("Done", (d, w) -> {
                    for (int i = 0; i < shown.length; i++) if (shown[i]) hidden.remove(candidates.get(i).pkg);
                    saveHidden(hidden);
                    refresh();
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    // ---- the remote ----------------------------------------------------------------------------------------------

    @Override
    public boolean onKeyUp(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_MENU && getCurrentFocus() instanceof Tile) {
            Tile tile = (Tile) getCurrentFocus();
            for (App a : everyApp) if (a.pkg.equals(tile.key)) { options(a); return true; }
        }
        return super.onKeyUp(keyCode, event);
    }

    @Override
    public void onBackPressed() {
        // A home screen has nowhere to go back to.
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (intent.hasCategory(Intent.CATEGORY_HOME)) {              // Home pressed again: back to the top, first app selected
            lastFocus = null;
            scroll.smoothScrollTo(0, 0);
            if (pinnedRow.getChildCount() > 0) pinnedRow.getChildAt(0).requestFocus();
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        IntentFilter filter = new IntentFilter();
        filter.addAction(Intent.ACTION_PACKAGE_ADDED);
        filter.addAction(Intent.ACTION_PACKAGE_REMOVED);
        filter.addAction(Intent.ACTION_PACKAGE_REPLACED);
        filter.addDataScheme("package");
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(packagesChanged, filter, Context.RECEIVER_EXPORTED);
        else registerReceiver(packagesChanged, filter);
    }

    @Override
    protected void onRestart() {
        super.onRestart();
        refresh();                       // coming back from another app: catch anything installed or removed meanwhile
    }

    @Override
    protected void onStop() {
        super.onStop();
        unregisterReceiver(packagesChanged);
        release();
    }

    /** The projector has about 1 GB of memory, so while another app is in front this screen keeps nothing: no tiles, no icons, no app list.
     *  It is rebuilt (a few milliseconds) when you come back. */
    private void release() {
        if (getCurrentFocus() instanceof Tile) lastFocus = ((Tile) getCurrentFocus()).key;
        pinnedRow.removeAllViews();
        grid.removeAllViews();
        everyApp = new ArrayList<>();
        System.gc();
    }

    private int dp(float v) {
        return Math.round(v * density);
    }
}
