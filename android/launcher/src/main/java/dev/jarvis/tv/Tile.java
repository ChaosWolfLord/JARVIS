package dev.jarvis.tv;

import android.content.Context;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

/** One app on the home screen: an icon and a name on a rounded card that lights up and grows when the remote selects it. */
final class Tile extends LinearLayout {
    final String key;                 // package name of the app (or "jarvis" for the placeholder)

    Tile(Context context, String key, CharSequence label, Drawable icon, int widthDp, int heightDp, int iconDp, float density) {
        super(context);
        this.key = key;
        setOrientation(VERTICAL);
        setGravity(Gravity.CENTER);
        setFocusable(true);
        setClickable(true);
        setLongClickable(true);
        int pad = Math.round(6 * density);
        setPadding(pad, pad, pad, pad);
        setMinimumWidth(Math.round(widthDp * density));
        setMinimumHeight(Math.round(heightDp * density));

        ImageView image = new ImageView(context);
        image.setImageDrawable(icon);
        image.setScaleType(ImageView.ScaleType.FIT_CENTER);
        addView(image, new LayoutParams(Math.round(iconDp * density), Math.round(iconDp * density)));

        TextView name = new TextView(context);
        name.setText(label);
        name.setTextColor(0xFFDDE9F2);
        name.setTextSize(13);
        name.setGravity(Gravity.CENTER);
        name.setSingleLine();
        name.setEllipsize(TextUtils.TruncateAt.END);
        LayoutParams nameParams = new LayoutParams(Math.round((widthDp - 12) * density), LayoutParams.WRAP_CONTENT);
        nameParams.topMargin = Math.round(4 * density);
        addView(name, nameParams);

        float radius = 14 * density;
        GradientDrawable idle = new GradientDrawable();
        idle.setCornerRadius(radius);
        idle.setColor(0x55102235);
        idle.setStroke(Math.round(density), 0x22FFFFFF);
        GradientDrawable focus = new GradientDrawable();
        focus.setCornerRadius(radius);
        focus.setColor(0xCC16314A);
        focus.setStroke(Math.round(3 * density), 0xFF3FD8FF);
        StateListDrawable background = new StateListDrawable();
        background.addState(new int[]{android.R.attr.state_focused}, focus);
        background.addState(new int[]{android.R.attr.state_pressed}, focus);
        background.addState(new int[]{}, idle);
        setBackground(background);

        setOnFocusChangeListener((v, hasFocus) -> v.animate().scaleX(hasFocus ? 1.08f : 1f).scaleY(hasFocus ? 1.08f : 1f).setDuration(120).start());
    }
}
