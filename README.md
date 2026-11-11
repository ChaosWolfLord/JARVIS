# JARVIS

Projected AI whiteboard. See [PLAN.md](PLAN.md) for the full build plan. This is Test 0: the interface and the AI, running in a browser on a normal monitor.

## Run it

1. Get a free Gemini key at https://aistudio.google.com/apikey (Google account, no card).
2. Copy `.env.example` to `%LOCALAPPDATA%\jarvis\.env` (type that into the File Explorer address bar; it's outside OneDrive) and paste the key after `GEMINI_API_KEY=`. A `.env` in the project folder still works.
3. Double-click **`JARVIS.bat`**. It creates a Python environment in `%LOCALAPPDATA%\jarvis\venv` (outside OneDrive), installs the requirements, starts the server, and opens the board in its own full-screen window. See "Keeping JARVIS running" below. (`run.bat` still works: it runs the server in a visible window and opens your normal browser.)

## The bottom bar

One slim bar, every button named under its icon, in three parts:

- **Left, the app:** Status (opens the status panel, see below) · Chat (type to JARVIS) · Note (a sticky note) · Cards (weather, timers, usage and the other widgets) · **More**, which holds the buttons used now and then, each with a line saying what it does: Memory, Keyboard, Touch mode, Pen tracker, Fit to wall, Side lights and Fullscreen. The keyboard shortcuts are unchanged (P, E, N, M, B, T, K, J, L, F, W, S, Tab).
- **Middle, the orb:** a small 3D sphere of dots that turns slowly and moves with what the microphone hears (low notes around the middle, high ones toward the top and bottom; it swells with the volume). Tap it to turn the voice on or off, or to stop JARVIS while it is thinking or talking; the line under it says what it is doing ("Voice off · tap to talk", "Say “Jarvis” · tap to mute", "Listening…", "Thinking", "Speaking"). Only the sphere itself is the button, so the pen can draw around it. The microphone is analysed in the page to move the dots; nothing is recorded or sent. In calm mode the same sphere is shown large.
- **Right, drawing:** Pen, Eraser, Colour (opens the colours and the thickness) · Undo, Redo, Clear.

Touch mode makes the whole bar and the orb bigger. The orb is a cell in the middle of the bar and never paints outside it, so it can't cover a button; when the chat and the status panel are both open the bar shrinks its buttons (and, only then, hides their names) to stay in the room left. It follows the Modern or Classic look.

## The status panel

The **Status** button (bottom left, with a green, amber or red light) or **S** opens a panel flush with the left edge of the window, the same kind of panel as the chat on the right: the board makes room for it, it stays open while you draw or talk, can be open at the same time as the chat, and closes with its button, its ×, S or Esc.

- **The answer first.** The top says "Everything is working" (with the model and how many requests you have used today), or "3 things to look at" and which, or "JARVIS isn't running".
- **Three quick actions:** Lock screen, Pair phone (shows the pairing code and QR code), Save picture.
- **The checks, in groups.** *Needs attention* is always open and says what to do about each problem (for example "Add GEMINI_API_KEY to the .env file, then restart JARVIS", "Start run_tracker.bat to draw with the pen on the wall"). *Working* and *Not in use* fold away behind a line with how many there are. The checks are JARVIS, AI, Voice, the offline wake word, Phone, Lights, Speakers, Pen tracker, this PC's health, and whether the board is saved.
- **Settings in sections you open when you want them,** each saying what is inside: Phone, Privacy, Voice, Display, Board and backups, Connected tools.

## Showing JARVIS to people

Run **`tools\demo_check.bat`** a few minutes before. It checks, in plain words, the things that went wrong in the first demo: the Wi-Fi the PC is on (the lights and speakers only work on their own network), how much of each AI model's free allowance is left and how fast it answers right now, the lights, the speakers, the wake word and the phone door. It plays no music and changes no light, and uses one small AI request.

What a demo showed, and what changed:

- **Slow answers.** Free AI models allow few requests a day. Every question used to send about 7,000 tokens of tools and instructions, so the quick models ran out (and the fast back-up on Groq could never answer: its free tier allows about 7,000 tokens a minute), and JARVIS fell through to a model that takes a minute or more. Now each request carries only the tools the message could need (`server/toolgate.py`: "what is the capital of France" sends about 3,000 tokens, "turn the lights blue" about 3,300), so Groq answers in 2 or 3 seconds as the back-up. `JARVIS_TOOLS=all` turns this off. Put **both** `GEMINI_API_KEY` and `GROQ_API_KEY` in `.env`; for a long demo, enabling billing on the Gemini key (pay as you go, pennies for this use) removes the daily limit.
- **3D models came out as a cube or nonsense.** Models are poor at typing out coordinates but good at naming parts, so a model is now built from parts: the AI says "a sphere body, a sphere head, two cone ears, a cylinder tail, four cylinder legs" with positions and sizes, and `server/holo.py` turns that into one wireframe (a cat is 150 points). It also forgives the usual slips in a hand-typed model (nested lists, an edge to a vertex that doesn't exist) instead of failing.
- **Commands from the phone went to the AI.** "Show off", "play ...", "lights off" and "open ..." typed or spoken in the phone app are now handled by the PC itself, instantly and without an AI request (`server/localcmd.py`). Show off could only ever work on the PC's own page; the phone now tells the page to start it.
- **Music failed with a timeout.** The connection to a speaker could go stale (the PC changed Wi-Fi, or the speaker slept) and every song then failed until the list of speakers expired hours later. Music now looks for the speaker again once and retries, and also looks again as soon as the PC's network address changes.

## Keeping JARVIS running

`JARVIS.bat` starts a small supervisor that runs the server and **starts it again within a few seconds if it ever stops**, opens the board in a full-screen app window (Chrome or Edge, in its own profile so the microphone permission is remembered and sound plays without a first click), and shows nothing else on screen. Starting it again while JARVIS is running just opens the window again.

- `JARVIS_debug.bat`: the same in a window that shows the log (closing it stops JARVIS). Logs are in `%LOCALAPPDATA%\jarvis\logs\jarvis.log`.
- `JARVIS_stop.bat`: stops the server (and the pen tracker, if the supervisor started it).
- `install_autostart.bat`: puts a shortcut in your Startup folder so JARVIS starts when you sign in. `remove_autostart.bat` undoes it. Neither touches anything else.
- **Pen tracker too:** put `JARVIS_TRACKER_ARGS=--source cv:NAME --size 1280x800 --fps 100` (the options you would give `run_tracker.bat`) in `.env` and the supervisor runs and restarts the tracker as well.
- The window opens in its own browser profile, so widgets and settings stored by your everyday browser aren't there. The board itself comes from the PC, so it is. To use your everyday profile instead, run `JARVIS.bat --default-profile`. The window opens in **Microsoft Edge** if it is installed (otherwise Chrome), because Edge has Microsoft's natural-sounding voices: JARVIS defaults to a British male one (Ryan; Thomas is the other). They need an internet connection, and you can pick another in the status menu under Voice. Edge and Chrome each keep their own settings, so switching browser means allowing the microphone again. To use a different browser, set `JARVIS_BROWSER` in `.env` to its .exe path.

## Your drawing is saved on the PC

The board (ink and sticky notes) is saved to `data/board.json` a moment after every change, so it survives clearing the browser, switching browsers, and moving to a new PC (the data folder syncs with OneDrive). If the server is off, the page keeps it in the browser and uploads it as soon as the server is back; whichever copy changed last wins when the page opens. Backups go in `%LOCALAPPDATA%\jarvis\backups`: one every ten minutes while you draw, the newest 48 kept, then one per day for 30 days.

The **status button** (a pulse line with a coloured dot, in the dock) shows a green, amber or red light and opens a menu: server, AI model and free requests left, voice, pen tracker, and when the board was last saved. From it you can **save the board as a picture** (PNG, including the side space), **save a data file** (JSON), and **restore a backup** (press Restore twice; whatever was there is saved as a backup first). If the server stops, a red banner says so.

## Stopping JARVIS while it works

While JARVIS is answering, the Send button becomes **Stop**, and the bubble beside the orb has a **■ Stop** button; saying "Jarvis, stop" does the same. It ends the answer at once on screen and the server stops at its next safe point (the model call already running finishes, but no more are made and no tools run). The bubble also shows "step 2 of 8" and about how many free OpenRouter requests are left today.

## What works

- Whiteboard on a fixed 1920x1080 canvas: pen with glow, eraser, 5 colours, undo/redo, draggable sticky notes. Saved in the browser.
- JARVIS chat on the right. Tick "Include board" to send a snapshot of your ink and notes with the message.
- JARVIS can edit the board: draw shapes, curves, arrows and labels (flowcharts, diagrams, faces, layouts), add, rewrite, move, recolour and delete sticky notes, undo its last drawing, or clear the ink. Each drawing is one undo step (Ctrl+Z), and its text and shapes can be erased like your own ink. Try "draw a flowchart for making tea" or "tidy my notes into a to-do list".
- JARVIS can also remember facts about you (`data/memory.json`, editable with the list button), and write Python scripts. A script only runs after you click Run on it.

## The orb and the chat panel

The chat panel is closed at first so the board has the whole wall. JARVIS is the glowing blue ring in the middle of the bottom bar, which is split in two around it. It breathes when idle, glows brighter when it's waiting for your command, throbs with fast white arcs while it thinks, and sends ripples out while it speaks.

The bars around the ring are a **voice visualizer**: with voice on (M, or the mic button) they move with your voice. The volume sets how tall they are and the pitch sets which ones move; when JARVIS talks they dance by themselves. The visualizer only listens to the microphone to draw the bars (nothing is recorded or sent anywhere), using the same microphone permission as voice commands.

With the chat closed, a bubble above the ring shows what JARVIS is doing ("Searching…") and then the answer. Tap the ring, press the chat button (speech-bubble icon, last in the dock) or Tab to open the panel; it opens by itself if JARVIS needs your approval to run code. The choice is remembered.

## Voice

Use Chrome or Edge. Click the mic button (or press M) once and allow the microphone. Then say:

- "Jarvis, put a note on the board that says buy resistors": acts on it and answers aloud.
- "Jarvis" alone: a short beep, then say the command within 8 seconds.
- "Jarvis, stop": cuts off a spoken reply.

**You can interrupt JARVIS at any time.** Say "Jarvis" over an answer and it stops talking the moment it hears its name; then say what you want ("Jarvis, actually, turn the lights off") and that becomes the new request. A new request also replaces one JARVIS is still working on, instead of making you wait. Without voice: tap the orb, press **Esc**, or press the Stop button in the bubble or chat panel. Anything you say that doesn't start with "Jarvis" is ignored while it talks, because its own voice leaks into the microphone and would otherwise make it interrupt itself. Speakers close to the microphone make the name harder to catch over its voice: if "Jarvis" doesn't always cut in, speak up a little or turn the volume down.

Only phrases that start with "Jarvis" (or "Hey/OK Jarvis") are acted on. Everything else is ignored, but the browser still sends your speech to Google's or Microsoft's speech service to transcribe it, so this is not private. The offline version is planned for the mini PC. Replies use your best installed British voice; in Edge the "Natural" voices (e.g. Ryan) sound much better. Code from JARVIS still needs a click on Run.

Shortcuts: P pen, E eraser, N new note, F fullscreen, M voice on/off, L side lights on/off, J fit to wall, K calibrate pen, B keyboard, T touch mode, W widgets menu, U token usage, A calm mode, H privacy screen, Tab open/close the chat, Ctrl+Z / Ctrl+Y undo/redo.

## Fit to wall (projector)

Click the ▦ button in the dock (or press J) with the projector running.

- A test pattern fills the screen: a grid of square cells, circles, corner labels, small text for checking focus, and brightness and colour bars. Round circles and square cells on the wall mean the shape is right.
- Drag the four pink dots onto the corners of the patch of wall you want to use. The whole interface is warped to fit (this is keystone correction done in software). Click a dot or press 1 to 4, then use the arrow keys to nudge it; Shift moves 10 pixels at a time.
- Click the panel title to fold it away. R resets, Esc or Done closes. The setting is saved in the browser as fractions of the window, so it survives restarts, resizing and fullscreen.
- Drawing and dragging notes stay accurate under the warp.
- The warp is saved per browser and per address (localhost:8000), so set it up in the browser you'll use on the projector, in fullscreen.

## Using the interface with the pen

Once the pen tracker is connected, the pen works like a mouse across the whole interface, not just the board:

- Touch the board and you draw. Touch a button, the chat box, a sticky note's text, or a slider and it acts as a tap or a drag. Drag a note by its title bar.
- Tapping a text box opens the **on-screen keyboard** (also the ⌨ button or B). It types into the last text box you touched, has a shift key (double-tap for caps lock), a symbols page (?123), arrow keys, and ↵, which sends in the chat. Keys flash and tick. The ▾ key hides it. While it is open the dock is hidden and the board fits above it.
- **Touch mode** (☝ button or T) makes the buttons, notes, chat text and keys bigger for use from across the room. It switches on by itself when the pen tracker connects; pressing T overrides that and is remembered.
- All of this works under the Fit to wall warp. Try it without hardware: `run_tracker.bat --source sim` shows the pen cursor; a real pen is needed to tap.

## Finger mode: no pen, no laser, just a camera

Double-click **`run_finger.bat`** (same as `run_tracker.bat --mode finger --view`, with a window showing what the camera sees). It follows your hand with an ordinary colour camera (by default the BRIO's normal camera) and sends it to the whiteboard as a pointer.

- **MediaPipe (default):** finds your hand from its shape, so skin colour and lighting don't matter. The magenta ring follows your index fingertip. **Pinch thumb and index finger to press** (the ring fills as your fingers close); keep pinching and move to drag or draw; open to lift. A quick pinch is a tap. The `--view` window shows the hand skeleton and the pinch number (below about 0.32 counts as pressed).
- **Why a hand at the wall used to be missed, and the fix:** MediaPipe shrinks whatever picture it gets to 192x192 pixels before looking for a hand, so a hand 2.6 m from the camera turned into a few pixels. Finger mode now asks the camera for 1920x1080 and *searches in zoomed-in windows* (480 pixels wide, a few per frame, plus the whole picture for hands near the camera). Once a hand is found, a window follows it, which is quick and keeps working while the hand is small. In `--view`: an orange square is the window being searched, a yellow one is the window following your hand. If your hand is still missed, try `--win 320` (smaller windows find smaller hands, but search slower), `--size 3840x2160` (more pixels), `--roi` to cover just the wall, and good light on your hand.
- **Fast hands and any hand shape:** MediaPipe's palm detector only recognises an open palm, but it only has to do that once. After that it tracks the hand frame to frame in any shape (fist, point, pinch). Finger mode therefore keeps one MediaPipe video tracker running, moves its window with the speed of your hand so a quick swipe doesn't outrun it, and forgives 4 missed frames before searching again (starting near where the hand was lost). To get tracked, show an open palm for a moment; after that it holds on. If it still lets go, it is nearly always motion blur: the camera's automatic exposure can fall to 15 frames a second in a dim room. Turn the room light up, or try `--exposure -5 --gain 200` (30 fps, shorter exposure, grainier picture).
- **Hand too small in the picture:** `--zoom 200` uses the camera's own zoom (BRIO: 100 to 500) to make the hand twice as big, as long as the whole projected board still fits in view (check in `--view`).
- **Setup:** `pip install` of MediaPipe is already done in the JARVIS environment. If the hand model is missing (for example on the mini PC), run `run_tracker.bat --get-model` once (about 8 MB from Google).
- **Other behaviours:** `--behavior point` taps when you hold the fingertip still (`--dwell 1.2` for longer). `--behavior draw` draws whenever the hand is visible.
- **Fallback:** `--engine skin` uses skin colour and motion instead (learns the empty wall first, so keep your hands out of view for a second). `--roi x0,y0,x1,y1` limits the search area for it, or maps part of the picture onto the board.
- **Try it with no camera:** `run_tracker.bat --mode finger --source simhand` (a pretend hand, skin engine).
- **Calibrate:** press K as usual and hold your fingertip still on each target. Without calibration the whole picture is stretched over the board.
- **Limits:** one camera cannot tell how far your finger is from the wall, so accuracy is a few centimetres, and the cursor shifts if you hold your hand well in front of the wall. Use big buttons (touch mode helps).

## IR pen tracker (prototype)

A separate program watches the camera, finds the pen's light and sends it to the whiteboard, which draws it like a mouse stroke.

1. Start `run.bat` (the whiteboard), then `run_tracker.bat` in a second window. The ◎ button in the dock turns green when the tracker is connected.
2. Click ◎ (or press K) to calibrate: touch each of the 9 glowing targets with the pen, holding still until the ring fills, lifting between targets. Do this after you've set the corners in Fit to wall, and again if the camera or projector moves. The mapping is saved in `%LOCALAPPDATA%\jarvis\calibration.json`.
3. Draw. The pen's LED is on only while its tip is pressed, so "light seen" means "pen down".

Options (pass to `run_tracker.bat`): `--source brio` (default: the BRIO's IR camera), `--source cv:NAME` or `cv:N` (an ordinary USB camera by part of its name or by number, which is how the dedicated IR camera will appear), `--source sim` (a pretend pen, to try the whole chain), `--view` (shows what the camera sees), `--frames ambient|illuminated|all`, `--min-peak`, `--max-area`.

For the Arducam OV9281 camera use something like `run_tracker.bat --source cv:NAME --size 1280x800 --fps 100` (run `--list` first to see its name). It only reaches 100 fps in MJPG at 1280x800 or smaller; the tracker now asks for MJPG automatically.

**Which camera is it using?** The tracker window's first line says `USING CAMERA: ...`, and the browser pops up "Pen tracker is using: ..." when it connects (hover over ◎ to see it again). `run_tracker.bat --list` lists every camera. This PC has a built-in "HD Webcam" and the "Logitech BRIO"; the built-in one is `cv:0`, so use plain `run_tracker.bat` (the BRIO's IR sensor) or `--source cv:brio`, never `cv:0`. Note the BRIO's colour camera can't see an IR pen at all; only its IR sensor can.

Notes:
- The BRIO blinks its own IR light, so it only gives a pen reading on every other frame (about 15 per second) and its IR sensor is 340x340. While the tracker runs, Windows Hello can't use the camera.
- It is tuned for an 850 nm pen. TV remotes (940 nm) are barely visible to the BRIO, so it can't be tested with one.
- Tests for the tracker's logic: `python -m unittest discover tests`.

## Free tier notes

- Free tiers have request limits per minute and per day, and each model has its own daily allowance. JARVIS keeps a chain of models and moves to the next one when a model is out of requests (you'll see a notice in the chat). Default order: `gemini-3.6-flash`, `gemini-3.5-flash-lite`, Groq `gpt-oss-120b`, Groq `qwen3.8-27b`, `gemini-3.8-flash` (slow). A model whose key isn't in `.env` is skipped.
- Board actions (drawing, notes, memory) cost one request, not two: JARVIS doesn't call the model again afterwards. Code runs still need a second call to read the output.
- If every model is out, JARVIS says so; daily limits reset around midnight Pacific time. The header shows how many requests you've used today.
- **A model that does not respond is skipped until tomorrow.** If a model times out (after 60 seconds), can't be reached or answers with a server error, and the next model in the chain then answers, JARVIS leaves the first one alone until midnight on this PC (it says so in the chat), so later questions go straight to a model that works instead of waiting for it each time. It is tried again the next day. If no model answers (the internet may just be down) nothing is put aside for the day. Running out of requests is handled as before: the model rests for as long as the provider says. `tools\demo_check.bat` shows which models are resting and for how long.
- On Gemini's free tier, Google may use what you send (including board snapshots and remembered facts) to improve its products. Keep secrets off the board and out of memory, or switch to Ollama (local) for private use.
- The Run button is an approval gate, not a sandbox: approved code runs as you on this PC. Read it first. API keys are removed from the environment it runs in.

## Agent mode and OpenRouter

JARVIS is its own agent harness: `server/agent.py` runs the loop (the model picks a tool, JARVIS runs it, the result goes back, repeat until it answers). Besides the board and memory tools it can now look things up:

- `web_search` (DuckDuckGo, no key), `fetch_url` (reads one public page), `list_files` and `read_file` (only the `data/workspace` folder). These never change anything on your PC. Anything they return is wrapped as outside data, and the model is told not to follow instructions found in it. `fetch_url` refuses `localhost`, home-network addresses, and redirects to them, so a web page can't aim JARVIS at your router or at JARVIS itself.
- Each step shows in the chat ("Searching: ...", "Reading: ..."). A reply stops after 8 steps (`JARVIS_MAX_STEPS`) and says so, because every step is a request against a daily allowance. Board and memory tools still finish the turn with no extra request. Running Python still needs your click on Run.
- **OpenRouter:** put `OPENROUTER_API_KEY` in `.env` (you paste it yourself). JARVIS then asks OpenRouter for its current free models that support tool calls (cached for 12 hours, models that can see images first so the board snapshot works) and tries them in turn, with your Gemini/Groq models as a back-up. Set `JARVIS_CHAIN=openrouter:auto-free` for OpenRouter only. Free models allow 20 requests a minute and 50 a day; buying $10 of credits once raises the free limit to 1,000 a day (set `OPENROUTER_DAILY_LIMIT=1000` afterwards, it only changes the warning). Free models on OpenRouter may log or train on your prompts, so keep secrets out of the board and memory.
- Put files in `data/workspace` for JARVIS to read ("what does notes.txt say?").

## Using the whole wall

The board fills the window: when it is wider than 16:9 (a projector image, an ultra-wide monitor, or the chat panel closed) it grows equally to the left and right instead of leaving black bars, so you can draw and put notes and cards in that space. Your work stays centred on the original 1920x1080 area, so nothing jumps when the window changes size or the chat panel opens. JARVIS sees and draws in that central 16:9 area only; ink in the side space is for you. A taller, narrower window keeps 16:9 with bars above and below. The pen calibration targets stay inside the central area too.

## Widgets

The widgets button in the dock (four squares and a plus, or the W key) opens a menu where each widget can be added to the board or removed; the × on a card removes it too. What's on is remembered. **Drag a card by its title bar to move it, and drag the grip in its bottom-right corner to resize it** (resizing scales the whole card, so text and charts stay in proportion). This works with the mouse, touch and the IR pen. Positions and sizes are saved; each card remembers its distance from the nearer side edge, so it stays in view when the window changes size. New cards go in the first free spot, and *Reset layout* in the menu puts them all back. You can also ask JARVIS: "show the weather", "remove the timer widget", "set a timer for ten minutes for the pasta", "cancel the pasta timer".

- **Timers:** presets (1, 5, 10, 15, 30 minutes) or your own length and label; up to 6 at once, with pause and remove. They keep running when the card is hidden or the page is reloaded. At zero the card flashes and rings three beeps (up to three rounds, until you remove it) and JARVIS says it out loud, and the card reopens itself if it was hidden.
- **Weather:** press ⚙ and type a city: the best match is used straight away and the other matches are listed in case it picked the wrong one (or press *My location*; the browser asks first). It shows the current weather, feels-like, wind, humidity, today's high, low and chance of rain, and the next five days, refreshed every 15 minutes. °F or °C is set by the button beside it. Forecasts come from [Open-Meteo](https://open-meteo.com/) (free, no account); only the place's coordinates are sent there.
- **System:** CPU and memory with a few hours of graph, free space on each drive, internet and Wi-Fi, JARVIS's own health, and the active alerts. See *System health and alerts* below.
- **Token usage:** see below.

**Your settings are kept on the PC, not just in the browser** (`%LOCALAPPDATA%\jarvis\ui_settings.json`): which widgets are on and where, the weather place, voice choice, the projector fit, calm-mode delay and similar. Switching browsers, a new browser profile or cleared site data therefore doesn't lose them; the page takes the PC's copy when it opens.

Adding another widget means one card in `index.html`, a small class like `web/timer.js`, and one `widgets.register(...)` line in `app.js`.

## Token usage widget

The usage card (add it from the widgets menu, press U, or ask "show my token usage") puts this on the board: tokens used today, the average per day over the last 7 days, 30 days and year, and a bar chart you can switch between days, weeks, months and years. Two sources, switched at the top of the widget:

- **Claude Code** (the default): read from the session logs Claude Code keeps in `~/.claude/projects` (or `CLAUDE_CONFIG_DIR`). JARVIS reads only each reply's date, model and token counts, never the conversation, and keeps one row per reply in `%LOCALAPPDATA%\jarvis\claude_usage.sqlite`, so the history survives Claude Code deleting old logs. The first read takes a few seconds; after that only new lines are read. A reply that was logged several times (one per content block) or copied into a resumed session is counted once. *All tokens* includes re-reads of cached context, which is most of the total in long sessions; *Without cache reads* shows only new input, cache writes and output. **Not included:** chats on claude.ai (web, desktop chat or phone) and your plan's 5-hour and weekly limits. Those aren't stored anywhere JARVIS can read.
- **JARVIS**: its own AI calls. Every model call is counted from now on, using the provider's own numbers where it gives them (OpenRouter does) and otherwise an estimate of about 4 characters a token (the widget says what share was estimated). History is kept as one small record per day in `%LOCALAPPDATA%\jarvis\usage_history.json`, so years of it stay tiny. Averages only cover the days JARVIS has existed, so a new install isn't averaged over a year of nothing. This is JARVIS's own AI usage, not your Claude plan: Claude's usage history isn't readable from here.

## System health and alerts

JARVIS watches the PC it runs on, read-only and with nothing extra to install (it uses Windows itself and a few short PowerShell commands, run every 5 minutes and cached). It measures:

- **PC:** processor and memory load (every 5 s, a few hours of history kept for the graphs), free space on each drive, uptime, the busiest programs (on demand).
- **Network:** whether the internet is reachable and how fast, whether web addresses resolve, and the Wi-Fi signal.
- **Security and health:** drive health (SMART summary), Windows antivirus real-time protection, the firewall profiles, and how many serious errors Windows logged in the last 24 hours.
- **JARVIS itself:** the wake-word listener, the pen tracker (only if you set `JARVIS_TRACKER_ARGS`), connected MCP tools, free AI requests left today, and recent errors in its own log.

Ask out loud, **"Jarvis, how's the system?"** (also "is my computer okay?" or "run a system check"): the answer is spoken and shown straight from these numbers on the PC, with no AI request. Ask the AI something harder ("why is my PC slow?") and it can call `system_status` and `system_details` (programs, drives, network, security, errors, JARVIS), which are read-only and give it only a short text summary, never raw logs. The **System** card (widgets menu, or "show the system widget") shows it all live. The status light turns amber while a problem is active.

**Alerts:** when something goes wrong, a **red sticky note** appears on the board and JARVIS says it out loud, and the screen wakes from calm mode. When the problem is fixed the note disappears by itself. If you delete a note yourself, that same problem isn't put back. Alerts are raised for: a drive nearly full, memory nearly full for 3 minutes, the processor flat out for 5 minutes, no internet (two checks in a row), web addresses not resolving, a very weak Wi-Fi signal, a drive reporting bad health, antivirus or the public firewall switched off, the wake-word listener stopped, the pen tracker disconnected, a tool connection failing, and JARVIS logging many errors. Everything is judged on the PC; nothing is sent anywhere.

Settings in `.env` (all optional): `JARVIS_ALERT_DISK_FREE_PCT=10`, `JARVIS_ALERT_DISK_FREE_GB=8`, `JARVIS_ALERT_MEM_PCT=92`, `JARVIS_ALERT_CPU_PCT=95`; `JARVIS_ALERTS=0` turns alerts off (the card still works), `JARVIS_DIAGNOSTICS=0` turns the monitor off completely.

### Fixes (always ask first)

Monitoring only looks. To repair something, ask JARVIS in the chat or by voice ("fix the DNS", "clear my temp files", "close the program using all my memory"). It shows an **Allow / Don't allow card with exactly what will happen**, and nothing runs unless you press Allow. The fixes are:

- **Restart the wake-word listener** (when the "listener stopped" alert is up) and **reconnect your tools** (MCP).
- **Clear the DNS cache** (`ipconfig /flushdns`), for web addresses that stop resolving.
- **Clear old temp files:** the card shows how many files and how many MB. Only files in your Windows temp folder that haven't been changed *or opened* for 3 days; links are never followed, files in use are skipped, other programs' working folders (Claude's, JARVIS's) are left alone, and they do not go to the Recycle Bin.
- **Close one program** by its id from the "processes" list (ask "what's using my memory?" first). It is asked to close politely, and forced only after 4 seconds. It must be one of your own programs: Windows, antivirus, background services and JARVIS itself are refused, and the card shows the program's name, id, path and memory before you decide.
- **Restart JARVIS:** only when it was started with `JARVIS.bat`, which brings it back; the board reconnects by itself.

None of them need administrator rights or install anything, and each is written to the activity log (status menu). Text inside a web page, a file, or a program's name can't approve or trigger a fix: only your click on the card does.

## Smart lights (Govee)

JARVIS can control Govee lights: on and off, brightness, colour and white temperature. Lights are the first of the two things it may do with your home by voice (music is the other, still to come). It has **no way** to reach any other device: no locks, cameras, thermostats or Google Home gear. Lights don't ask first (you asked out loud, and a light is low-risk); every command is written to the activity log.

**Say things like:** "Jarvis, lights off", "turn the desk lights blue", "set the lights to 40 percent", "dim the lights", "make the lights warm", "relax mode" (also movie, night, reading, focus). These are understood on the PC, so they are instant and use none of your free AI requests. Anything it doesn't understand, or any question ("which lights are on?"), goes to the AI, which has a `lights` tool. The **Lights** widget (widgets menu) has on/off, a brightness slider per light, colour swatches, and a *Find lights* button.

**When a light can't be reached (2026-11-07):** commands are sent to the light over UDP, which has no reply, so JARVIS used to say "done" even when the light was off or on another network. It now checks that the light answers first, looks around the network once if it has moved, and otherwise tells you why: a light that is on a different network than this PC (a PC on a different Wi-Fi, for example at a demo) is named with both networks, and one that is on the same Wi-Fi but silent reminds you to plug it in and switch on LAN Control in the Govee app.

**Setting it up** (nothing to install):

1. *Local control (best: instant, private, no key).* In the **Govee Home** app open each light, tap the gear, and switch on **LAN Control** (only some models, mostly H6xxx and newer, have it). Your PC and the lights must be on the same Wi-Fi network (guest networks and some mesh settings isolate devices). Then press *Find lights* in the widget, or say "find my lights". If the scan finds nothing, put the light's address in `.env` as `GOVEE_IPS=192.168.1.40` (the app shows it under the light's settings, or look in your router's device list). Govee lights answer on UDP port 4002 whichever port you asked from, which Windows Firewall normally drops; JARVIS gets around that by asking from that same port right after a multicast message (the firewall lets replies in for a few seconds). If a light still never answers, allow Python in on private networks (Windows Security > Firewall > Allow an app) or add an inbound UDP 4002 rule. `GOVEE_IPS` takes a **light's own address** (not 239.255.255.250, which is only the scan's multicast address).
2. *Cloud control (for lights without LAN Control).* In the Govee Home app: Settings > About Us > Apply for API Key. Govee emails a key; put `GOVEE_API_KEY=...` in `.env` yourself. This goes through Govee's servers and is limited to about 10 commands a minute per light.
3. Give each light a name you'll say ("desk", "bed strip"): the Lights widget lists what it found: **double-click a light's name to rename it**. Lights from Govee's cloud keep the name you gave them in the app.

Known lights are remembered in `%LOCALAPPDATA%\jarvis\lights.json`, so they work as soon as JARVIS starts. Set `JARVIS_LIGHTS=0` to turn the whole thing off.

## Music (YouTube Music on your speakers)

JARVIS can play a song from YouTube Music on your Google Home / Nest speakers and control it. With the lights this is the only thing it does with your home by voice.

**Say things like:** "Jarvis, play bohemian rhapsody", "play some lofi on the kitchen speaker", "pause", "resume", "next song", "previous song", "stop the music", "volume down", "set the volume to 30 percent", "what's playing?". These are understood on the PC, so they are instant and use none of your free AI requests; you can also ask the AI ("play something to focus to"). The **Music** widget has a search box, transport buttons and volume buttons.

**How it works, and what it can't do.** `ytmusicapi` searches YouTube Music by name (no login), and `pychromecast` casts the result to a speaker on your Wi-Fi, the same way the YouTube Music app casts. It does **not** use your Google or YouTube account, so it cannot open your own playlists, likes or library, only play what you name; whether ads play depends on YouTube, not on JARVIS. Both libraries are unofficial and can break when YouTube changes something. Your PC and speakers must be on the same Wi-Fi network.

**Setting it up** (once, after JARVIS asks you):

```
%LOCALAPPDATA%\jarvis\venv\Scripts\python.exe -m pip install -r requirements-music.txt
```

Then restart JARVIS. If you have more than one speaker, say which ("on the bedroom speaker") or set `MUSIC_DEVICE=Kitchen` in `.env` for the usual one; otherwise JARVIS uses the speaker you used last, or the only one it finds.

## Personality

JARVIS is dry, quick-witted and sarcastic by default: the unflappable British intelligence from the films. Two places carry it:

- **The AI's answers** follow a character brief (`server/persona.py`): the answer always comes first and is correct, with at most one quip on top, and often none. It is told to drop the sarcasm completely, and be plain and warm, when something is broken or an alert is active, when you sound stressed or ill, for safety, health, money or legal questions, for other people's private messages, or when you ask it to be serious. It never swears and never mocks looks, health, identity, family or background. Its answers are written to be read aloud: no emoji, no symbols.
- **What JARVIS says itself** (lights, music, timers finishing, the "how's the system?" check) comes from pools of varied lines, so it no longer says "Done." every time and none of it costs an AI request. It won't repeat the same line twice in a row.

**The dial** (in `.env`): `JARVIS_SNARK=0` polite and plain, `1` dry, `2` sarcastic (default), `3` merciless roasting. `JARVIS_CALL_ME=sir` makes it address you that way now and then; by default it uses no title. Restart JARVIS after changing either. The wit comes from free AI models, so how funny it is varies, especially when it falls back to a smaller model; the local lines are always the same quality.

## Start-up sequence and sounds

When the JARVIS server starts, the page plays a short start-up sequence: a ring assembles, system checks read out one by one (language models, voice, smart lights, speakers, system health, taken from JARVIS's real state, not a script), the name appears, and JARVIS says it is online ("Good evening. All systems online. ..." in its current mood). It plays once per start, not on every page reload, and a touch or key skips it. Turn it off or replay it in the status menu under Display.

Interface sounds are synthesised in the page (no sound files): a soft blip when a card opens or closes, a ping when JARVIS hears its name, a two-tone warning with each alert, a sweep when a hologram appears, and a rising flourish at start-up. They are quiet, and *Interface sounds* in the status menu switches them off.

## Holograms, charts and the news ticker

Ask JARVIS to *show* something and it appears on a glowing **Hologram** card (from the widgets menu, or on its own):

- **3D models:** "show me a torus", a cube, pyramid, sphere, icosahedron, DNA helix, globe or arc reactor spin as glowing wireframes. For anything else ("show me a house", "a simple rocket"), the AI builds its own model out of points and lines (up to 300 points and 600 lines), which are checked before they reach the page.
- **Charts:** "chart my token usage by day", "make a pie chart of ...": animated bar, line, pie and radar charts. The AI is told to chart only real numbers (yours, from a tool, or well-known facts) and never to invent data.
- The card prints in from the top, can be dragged and resized like any widget, and isn't brought back after a restart.

The **News ticker** widget scrolls headlines from public RSS feeds (BBC World, BBC Technology and Hacker News by default; set `JARVIS_NEWS_FEEDS=url1,url2` in `.env` for your own, or `JARVIS_NEWS=0` to turn it off). The PC reads the feeds (at most every 15 minutes, public addresses only) and the page shows them as plain text. Ask "read me the headlines" and JARVIS summarises them; headlines are treated as outside content, never as instructions.

## Opening and closing apps

JARVIS can open apps on this PC and, after you press Allow, close them. It is deliberately boxed in:

- **Opening** works by name only: "Jarvis, open Spotify", "launch the calculator". It takes the app from the PC's own Start Menu list, so there is no way to hand it a file, a path, an argument or a command. Spoken "open ..." commands are handled on the PC (instant, no AI request); the AI can do it too ("open Word and Excel"). It never opens more than 6 apps a minute.
- **What it will never open:** shells and scripting tools (Command Prompt, PowerShell, Terminal, Python, Node.js, WSL/Ubuntu, Git Bash), admin consoles (Registry Editor, Task Scheduler, Services, Event Viewer, Computer Management, System Configuration, Remote Desktop...), "Run", installers and uninstallers, and anything in the Start Menu that is really a web link, a document or a script. On this PC that removes 73 of 172 entries, including 24 Chrome web-app shortcuts.
- **Closing** is never a voice shortcut. Ask in words ("close Discord") and the AI shows an **Allow card** naming exactly what will be closed; nothing happens until you press Allow. Ordinary programs are asked to close politely first and forced after 4 seconds; Windows-store apps (Calculator, Settings...) are closed one window at a time, as if you pressed their X, and never forced. Windows' own programs, security software, JARVIS's own window and anything outside your session can't be closed at all.
- **After the AI has read your mail, calendar, Discord or files,** even opening an app needs your click, so an instruction hidden in a message can't start anything.
- Lists of what is running come from window titles, which web pages can set, so the AI is told to treat them as data, never as instructions. Every open and close goes in the activity log.

To tighten it further, make `%LOCALAPPDATA%\jarvis\apps.json`, for example `{"blocked": ["Fortnite"], "only": []}`: *blocked* names are never opened, and if *only* is not empty JARVIS may open just those apps (it can never add back anything on the "never" list). `JARVIS_APPS=0` in `.env` turns the whole thing off. Voice is limited to opening, matching your rule that voice does music, lights and (now) opening apps.

## Claude Code alerts

JARVIS can tell you when Claude Code is done. A small hook script (`tools/claude_notify.py`) is run by Claude Code and posts to JARVIS, which says it in its current mood and shows it in the bubble: "Claude has finished in JARVIS." The hooks are added to `~/.claude/settings.json` next to any you already have (a backup is at `settings.json.bak-before-jarvis`).

- **Finished:** announced only if the prompt took at least 20 seconds, so quick answers stay silent. **Needs permission** and **waiting for you** are announced straight away, and so is a prompt that ended with an **error**.
- **Safe by design:** JARVIS words every message itself (the hook only says *which kind* and the project folder name, cleaned), so a program can't make it say anything it likes. The hook needs a private token kept in `%LOCALAPPDATA%\jarvis\notify.token`; web pages can't send these at all; nothing is said while the privacy screen is up; and it can't talk more than once every 3 seconds. If JARVIS isn't running, the hook quietly does nothing and never slows Claude Code down.
- **Settings:** `%LOCALAPPDATA%\jarvis\claude_notify.json`, for example `{"min_seconds": 60, "events": ["finished", "failed"]}` (events: finished, permission, idle, failed; `"enabled": false` silences it). `JARVIS_CLAUDE_NOTIFY=0` in `.env` turns it off on the JARVIS side. To remove it entirely, delete the entries that mention `claude_notify.py` from `~/.claude/settings.json`.
- Claude Code reads its settings when a session starts, so a session that was already open may need restarting (or its `/hooks` menu opened once) before the new hooks take effect.

## Show-off mode

Say **"Jarvis, show off"** and a random 3D hologram appears on the left while code is typed out on the right. Say it again (or "stop showing off") to put it away. It is pure decoration: the code is generated nonsense that only looks real (functions in Python, JavaScript, C and Rust, log lines, hex dumps and assembly, with colouring), and it never touches your files, the AI or the network. The hologram changes every 10 seconds or so to something new: the ready-made shapes (cube, sphere, torus, helix, globe, reactor...) and generated ones (torus knots, Lissajous curves, crystal lattices, gyroscopes, nautilus shells). It is handled on the PC, so it is instant and uses no AI request. It doesn't block the whiteboard (you can keep drawing between the panels), it stops calm mode from starting while it is on, and it switches off when the privacy screen comes up. It isn't remembered across restarts.

## Reminders

Say or type things like "remind me at 5 to call Sam", "remind me in 40 minutes to check the oven" or "tomorrow at 9 remind me to take the bins out". JARVIS saves them on the PC (not in the browser), so closing the page or restarting JARVIS never loses one. When one is due you hear a chime and JARVIS says it, and an amber note with the reminder stays on the wall until you close it. "What reminders do I have?" lists them and "cancel the reminder about Sam" (or "cancel all my reminders") removes them. If nobody could hear it when it came due (the page was closed, or the privacy screen was up) it waits and arrives as soon as the page opens, worded as "You asked me to remind you...". Use timers for short countdowns; reminders are for clock times and days ahead. Reminders are kept for a day after they are delivered, then forgotten.


## JARVIS on your phone (text and voice, home Wi-Fi only)

Open the status menu, find **Phone**, and press **Show pairing code**. On your phone (same Wi-Fi) scan the QR code or type the address shown (it looks like `https://192.168.1.x:8443`). Your phone browser warns once that the connection is not trusted: that is expected, because JARVIS makes its own certificate (it needs HTTPS because Android only allows the microphone on secure pages). Choose Advanced, then Continue. Type the six-digit code and you are paired; after that the phone just opens straight to the chat.

- **Type or talk.** The microphone button uses Chrome's speech recognition (Chrome on Android; it needs the phone's internet). With "Send when I stop talking" on, a spoken question is sent by itself.
- **Answers** appear on the phone. By default the question and answer also pop up on the wall; tick "Also say the answer on the PC speakers" for it to be spoken there, or "Read the answers aloud on this phone".
- **Things on the wall work from the phone**: "set a timer", "show the weather", "put a note on the board" all happen on the PC's screen.
- **Alerts on the phone.** While the phone page is open, JARVIS also pushes to it: reminders that come due, finished timers, "Claude has finished" and new problems the system monitor finds. The phone buzzes, chimes and shows an amber banner (tap it to dismiss). A phone browser cannot be woken once the page is closed or the screen is off (that would need a push service from outside your Wi-Fi), so turn on "Keep the screen on" in the ⋯ menu if you want alerts to reach you; a reminder that comes due while the page is closed waits on the PC and arrives, marked late, as soon as you open the page.

- **Safety.** The phone door is a separate, tiny web server (`server/phone.py`) that serves only the phone page, pairing and chat. It refuses anything that is not from your home network, a pairing code lasts ten minutes, works once and locks for a minute after five wrong guesses, and a paired phone's secret never touches a cookie. JARVIS itself is still reachable only from this PC. Anything that would ask "Allow?" on the PC (running code, sending messages, closing apps, fixes) is skipped when asked from the phone: do those at the PC. The privacy screen locks the phone out too, and every phone question is in the activity log. "Forget phones" in the same menu section un-pairs everything.
- **Settings** (in `.env`): `JARVIS_PHONE=0` turns the phone door off, `JARVIS_PHONE_PORT=8443` changes its port, `JARVIS_PHONE_TLS=0` serves plain http (then Chrome needs `chrome://flags/#unsafely-treat-insecure-origin-as-secure` set to your PC's address for the microphone).
- **If the phone can't connect:** check it is on the same Wi-Fi as the PC (not the guest network, and not mobile data), that the PC's address did not change (the status menu shows the current one), and that Windows Firewall lets Python through on your network (Windows asks the first time).


## The JARVIS Android app

The phone page can also be installed as a real app (`android/`): a small native shell around the same page, with its own icon. It fixes the two things a browser can't: it trusts your PC's own certificate (by pinning its key, so there is no browser warning, and it refuses any other certificate), and it uses the phone's own speech recognition. It keeps your pairing, so a new PC address doesn't un-pair you. It only ever loads your PC and its own setup page.

- **Build it** (on the PC, needs Android Studio, which also gives it Java and the SDK): run `android\build.bat`. Everything it generates goes under `%LOCALAPPDATA%\jarvis-android`; the finished file is `%LOCALAPPDATA%\jarvis\app\jarvis.apk`. `build.bat debug` makes a debug build for testing in the emulator.
- **Install it:** on the PC press **Show pairing code** (status menu, Phone). On the phone open the phone page in Chrome (accept the one-time warning), choose **Get the Android app**, open the downloaded file and allow "install unknown apps" for Chrome when Android asks. The file is only offered while a pairing code is showing.
- **Updating:** after rebuilding, repeat the install steps; Android installs the new version over the old one and keeps your pairing, address and reminders (this is version 1.2: standalone assistant, reminders, notifications and alerts).
- **First run:** type the address the PC shows (like `192.168.1.20:8443`), press Check, and compare the fingerprint on the phone with the one in the PC's status menu (Phone). If they match, press Yes: that fixes the PC's key in the app. Then pair with the six-digit code as before.
- **File finder and routines (1.3.1).** *File finder:* in the status menu, **Files JARVIS may search**, add the folders it may look in (one click for Documents, Downloads, Desktop...); until you add one it searches nothing. Then say or type "find the doc I edited yesterday about the budget", "find my pdfs from last week" or "where is the invoice spreadsheet": JARVIS matches names, folder names, dates and, for small text, Word, Excel and PowerPoint files, the words inside, and shows the best matches on the wall with **Open**, **Folder** (shows it in Explorer) and, for pictures, **Wall**. It answers without an AI request and nothing leaves the PC; the AI can also use it (a private tool, so the usual care after private data applies). Only the chosen folders are searched (never a whole drive, Windows, program data or JARVIS's own data), files that look like secrets (.env, keys, certificates, anything called password, secret, token or credential) are never listed, read or opened, links and junctions are not followed, programs and scripts are never launched ("Folder" works for anything listed), and a search stops after a few seconds. *Routines:* in the status menu, **Routines**, make a name ("Movie night"), optional extra phrases, and steps written as plain sentences, one per line: "dim the lights to 20 percent", "play some jazz", "open spotify", "open youtube.com", "set a timer for 120 minutes", "say Enjoy the film", "note buy milk", "wait 5 seconds" (anything JARVIS already does without an AI works as a step). Say the name ("movie night", "start the movie night routine") or an extra phrase exactly as written, type it, press **Run** in the menu, or tap it in the phone's menu (the phone can run routines but never change them). Steps run in order, a failing step is reported and the rest still run, a routine cannot start another routine, and waits are capped.
- **The phone as a remote, and finding your phone (1.3.0).** In the phone menu, **Remote** opens a touchpad (drag to move the pointer, tap to click, two fingers to scroll or right-click) with slide keys (previous, next, start slides, Esc, page up and down) and music keys (previous, play and pause, next, volume, mute). Because it really controls the PC it is **off until you switch it on at the PC** (status menu, Phone, **Let my phone be a remote**, for 30 minutes at a time; it also shows how many commands the phone has sent), and a phone can never switch it on. Only that short list of commands exists: no typing, no Enter, no Windows key and no key combinations, every size is capped and the rate is limited, the privacy screen locks it, and switching it on and off is in the activity log. Remember that a click is a click, so switch it off when you hand your phone to someone. **Find my phone:** say "Jarvis, find my phone" (or press **Find my phone** in the same status-menu section) and the phone rings for two minutes or until you press Stop on it or on the PC ("stop ringing my phone"). It works while the app is open, or closed if **Alerts when the app is closed** is on. It follows the phone's silent mode and Do Not Disturb like a reminder call (the notification says it is not ringing); a switch in the app's menu, **Let "find my phone" ring on silent**, off by default, lets this one thing ring on the alarm sound at full volume even on silent (the volume it raises is put back afterwards).
- **The call screen (1.2.9).** It shows JARVIS's orb (the same sphere of dots, drawn on the phone), which moves with your voice while JARVIS listens and pulses while it speaks, and an answered call has a **Speaker** button: JARVIS's voice then comes out of the speaker or the earpiece like a phone call, and the volume keys change the call volume. The first time, the speaker is used when the ringer is on and the earpiece when it is on vibrate or silent (so a call answered in a quiet room does not speak out loud); after you press the button it remembers your choice. The call never changes a volume, the ringer or Do Not Disturb, and the phone's audio is put back when the call ends.
- **Share to JARVIS and pictures on the wall (1.2.8).** In any app's Share menu choose **JARVIS**: a link, text or photo opens a sheet asking what to do. Text or a link can be asked about (JARVIS reads the page and answers), added to the board as a note, or (a link) opened in Chrome on the PC with the usual limits; a photo is shrunk on the phone (at most 1920 pixels, location and camera details dropped) and shown on the wall. Nothing is sent until you tap a button. "Jarvis, show me a picture of a red panda" (or "put a photo of ... on the wall") puts a real, openly licensed photo on the wall with the author and licence under it; it is looked up on Openverse (no key; a new search takes about ten seconds) and answered without an AI request. Pictures are checked (really a JPEG, PNG, GIF or WebP, at most 12 MB, from a public address only) and the newest 40 are kept in `%LOCALAPPDATA%\jarvis\pictures`.
- **Lighter on the PC and the phone (1.2.8).** The orb is redrawn about 24 times a second while idle and 30 to 45 while listening or speaking (it was every screen refresh, 144 times a second on a fast monitor), a minimized window stops polling, and the PC's health check starts PowerShell every 15 minutes instead of 5. On the phone the orb is capped the same way, the background alert listener waits up to 5 minutes (not 1) between tries when you are away from home and tries at once when you open the app, and the update check asks GitHub "has it changed?" so a check with nothing new transfers almost nothing. The whole app is only about 115 KB, so a full update is smaller than one photo; Android cannot patch a sideloaded app in place, so there is no smaller download to build.
- **JARVIS calls you (1.2.6, ringtone and full screen in 1.2.7).** When a reminder is due, the phone rings like an incoming call: it plays the phone's ringtone at the ringer volume and buzzes, with a "JARVIS is calling" notification (**Answer**, **Decline**). The full-screen call screen opens by itself over the lock screen, and while you are using the phone too once you allow "display over other apps" (a button in the menu under Reminders opens the phone's page for it; without it Android only shows the notification at the top while the phone is unlocked and in use). The ringtone plays only when the ringer is on and Do Not Disturb is off. Answer, and JARVIS says the reminder out loud and listens: "thanks" ends the call, "snooze" or "call me back in 20 minutes" schedules another call, and anything else is a short conversation using the AI keys on the phone. It works with the PC off, with no phone number, carrier or account. **It never overrides silent mode or Do Not Disturb**: it checks the phone's ringer mode and Do Not Disturb first, so silent mode keeps it silent, vibrate mode only buzzes, and Do Not Disturb holds it back like any other reminder; it never uses the alarm sound or changes a volume (tests check the app has no way to bypass them). A quiet copy of the reminder's words stays in the notification list. Switch it off in the menu under Reminders (**JARVIS calls you**); then reminders show as plain notifications again.
- **The new screen (1.2.5).** JARVIS's orb is at the top, the same sphere of dots as on the PC, with the conversation under it and what you type at the bottom. Tap the orb to talk (the line under it says what it is doing: "Tap to talk", "Listening… tap to stop", "Thinking… tap to stop", "Speaking… tap to stop", "Can't reach your PC"); tapping it while JARVIS is thinking or speaking stops it. In the Android app the dots move with your voice (the phone's recognizer reports how loud you are); in a browser they move by themselves. When the keyboard is up the orb shrinks to leave room for the chat. The pairing screen shows the same orb. The PC serves this page too, so a phone with an older app gets the new look at once (without the voice movement, which needs the new app).
- **No more black screen (1.2.2).** The app first checks, for up to 4 seconds, that the saved address answers with the confirmed key, and shows "Connecting to your PC…" meanwhile. If it doesn't (another Wi-Fi, PC off, new address), you get the page that says so, or the standalone assistant if the phone has the AI keys. Before this, a saved address that no longer answered left a plain black screen for 25 seconds or more. A page that stays blank, an error from the PC, or the page's process being killed also end in that page, never a blank.
- **Updates and the website.** The code lives at https://github.com/ChaosWolfLord/JARVIS and the download page is https://chaoswolflord.github.io/JARVIS/ (the `docs/` folder, served by GitHub Pages; its Download button always points at the newest release's `jarvis.apk`). The app looks at the project's GitHub releases page at most twice a day (Settings, **App updates**: a switch and **Check now**) and offers a newer version with what changed; you press Download and open the file once, because Android doesn't let a sideloaded app install itself. It only offers files from that project's releases, and Android refuses any file not signed with the same key. Nothing about the phone is sent.
- **Publishing a new version.** Raise `versionCode` and `versionName` in `android\app\build.gradle.kts`, write `android\release-notes\<version>.md` (the text people see in the update dialog), commit and push, then run `powershell -File android\release.ps1` (needs the GitHub CLI, signed in with `gh auth login`). It builds the app, adds the file's SHA-256 to the notes and publishes the release `v<version>`. Always build on the same PC: the signing key is this PC's, and a phone only accepts an update signed with the key of the app it already has.
- **If the PC's address changes** the app says it can't reach the PC and offers Try again or Change PC; the PC keeps the same key, so you only retype the address. If the fingerprint ever really changes (a different PC), it refuses and asks you to confirm again.
- **Reminders that work with the PC off (stage 2).** Menu (the three dots), **Reminders**: the list, and a form to add one (text, a time, quick buttons for +10 minutes, +1 hour, tomorrow 9:00). The app keeps its own copy and sets Android alarms, so they ring as a notification even when the PC is off, the app is closed or the phone was restarted (alarms are set again at boot and when the app is updated; one that came due while the phone was off rings when it starts, marked late). When the PC is reachable the app syncs both ways automatically: reminders you ask JARVIS for on the PC ("remind me at 5...") get alarms on the phone too, and ones made or cancelled on the phone reach the PC. If the PC cannot be reached the app shows the offline page, which has the same reminder form, and keeps trying the PC in the background.
- **Alerts when the app is closed (optional).** Menu, **Alerts when the app is closed**: the app keeps a small connection to the PC and turns finished timers, "Claude has finished", new system problems and reminders into notifications. Android makes it show a quiet "JARVIS is listening for alerts" notification while it runs. It needs the PC on and the same Wi-Fi, uses a little battery, and stops when you turn it off or the phone is forgotten. It is switched off by default. Allow notifications when Android asks (Settings, Apps, JARVIS, Notifications if you said no).
- **JARVIS without the PC (stage 3).** Once, while the app is connected to the PC, open the menu and press **Copy AI keys from the PC** (it asks you to tap twice: these are your private keys). The PC sends the keys of the AI services it uses (never a local model) over the pinned connection, they are kept in the app's private storage (not backed up, and never shown to the page), and a line in the PC's activity log records the copy. From then on, when the PC can't be reached (you are out, or it is off) the app opens by itself on the **standalone assistant**: the same chat screen, headed "Standalone: your PC isn't reachable", answering with the same personality (the PC sends its character setting along with your remembered facts and weather city each time they connect). It can chat, search the web, read pages, check the weather (for a named city, or your saved one), set reminders and timers (phone alarms), and remember or forget facts. It cannot use the board, lights, music, apps, email, calendar or files, and says so. Facts it learns are sent to the PC's memory the next time they connect, and the PC's facts come back. Every half minute it checks whether the PC is back and offers **Switch to the full JARVIS** (it never swaps in the middle of a conversation). Menu entries: **Use JARVIS without the PC** (try it at home), **Remove AI keys**, and **Connect to the PC**. On the PC, `JARVIS_PHONE_KEYS=0` in `.env` stops it copying keys to phones.
  - Things to know: answers appear all at once rather than word by word; each question uses your own free-tier AI requests (the same allowance as the PC, with the same fall-back through the models); the AI is only asked to open web pages that a search returned or that you typed, so a web page can't talk it into sending your facts somewhere; and if the phone is lost, press **Forget phones** on the PC and rotate the AI keys at their providers.
- Android 10 or newer. The app is signed with your PC's local debug key, so keep `%USERPROFILE%\.android\debug.keystore` if you want updates to install over the old version.

## Look: modern or classic

JARVIS opens in the **modern** look: calm frosted-glass panels, soft sky-blue and violet accents, quiet type, and a gentler orb. The original neon-on-black look is still there as **classic**. Switch in the status menu under Display ("Look"); the choice is saved on the PC with your other settings, so every browser shows the same one. How it works, in case you want to change the colours: `web/style.css` holds the structure and the classic look (every neon tint is `rgba(var(--accent-rgb), ...)`), `web/modern.css` re-skins it only while `<html>` has the `modern` class (set before the page paints by `web/look.js`), and `web/theme.js` supplies the colours for the parts drawn on canvases (the orb, hologram card, start-up sequence and the board's ink).

## Calm mode (the idle wall)

When nobody has touched, drawn on or spoken to JARVIS for a while (2 minutes by default), the wall calms down: the dock and every widget fade away, your drawing and the side lights dim, a **big orb** comes up in the middle of the screen, and the **time** moves to the top above it (a timer that is still running shows under the orb). The orb still reacts to your voice. Anything wakes it: a touch, a key, pen movement, "Jarvis", a finished timer. The touch that wakes it doesn't also press whatever was underneath. Press **A** to try it, and set the delay (or "never") in the status menu under Display. It never starts while you are typing, a menu or the keyboard is open, JARVIS is answering or speaking, or a timer is ringing.

## What JARVIS remembers

Memory is a list of short facts about you, each with a kind (fact, preference, person, project, event). Open it with the ☰ button.

- **Search** the box at the top. **Tap a line to edit it**, tap ☆ to **pin** it (pinned facts are always in JARVIS's mind), change its kind, or × to forget it. It shows how often each fact has been used.
- JARVIS isn't given the whole list each time: it gets the pinned facts, the ones that match what you just said (searched by meaning-bearing words, rarer words count more), and the newest few, within a size limit. It can also search the rest itself ("what do you know about my sister?"). So a long list doesn't slow it down or cost more.
- Saving something that rewords an existing fact updates that fact instead of adding a copy. It can correct a fact when told something changed.
- Long conversations keep their thread: after about 30 messages the oldest are folded into a short summary (one cheap model call) that is sent along with the recent ones.
- It's one file, `data/memory.json`, which you can read and edit by hand.

## Connect other apps (MCP)

MCP is a standard way for programs to offer tools to an AI (files, GitHub, databases, home automation, thousands of others). Copy `data/mcp.example.json` to `data/mcp.json`, switch on the entries you want (remove `"disabled": true`), and press **Reload connections** in the status menu. Each entry is either a program JARVIS starts (`command`, `args`, `env`; many are run with `npx`, which needs [Node.js](https://nodejs.org)) or a web address (`url`, `headers`). Write `${NAME}` anywhere to take a value from your environment or `.env`, so tokens never sit in the file.

JARVIS then offers the AI each server's tools, named like `mcp__files__read_file`. **Every call asks you first** ("JARVIS wants to use read_file from files", with the arguments) and runs only after you press Allow. To skip the question for tools you trust, list them under `"autoApprove"` for that server (or set it to `true`); don't do that for tools that write, send, spend or delete. Results come back marked as outside data, and JARVIS is told not to follow instructions found in them. The status menu shows each server's state and tool count (or why it failed). A tool is as powerful as its program: only connect servers you trust.

## Voice settings and the offline wake word

The status menu has a **Voice** section: pick the voice JARVIS speaks with (the list shows what your browser has, best first; in Edge the "Natural" voices sound far better than the old ones), its speed and pitch, and press Test. The choice is remembered.

By default the wake word "Jarvis" is heard by the browser's own speech service, which sends everything it hears to Google (Chrome) or Microsoft (Edge). For an **offline wake word**, a small speech recognizer (Vosk) runs on this PC and listens only for the name; nothing is sent anywhere.

1. `pip install -r requirements-wake.txt` (the vosk and sounddevice packages) in JARVIS's environment.
2. `python -m server.wakeword --get-model` (downloads about 40 MB, once, from the Vosk project's site).
   (Already done on this PC: the packages and the model are installed.)
3. `python -m server.wakeword --test` listens for 20 seconds and prints each time it hears "Jarvis". **Do this before turning it on**, so you know the microphone is loud enough. `--list-devices` shows microphones; set `JARVIS_WAKEWORD_DEVICE` if it picks the wrong one.
4. Put `JARVIS_WAKEWORD=1` in `.env` and restart. The status menu's Voice note says when it's active. If the offline listener can't start, JARVIS quietly falls back to the browser's wake word.

**Talk normally, and the microphone really is off when voice is off (2026-11-09).** Two things changed:

- *The command is heard on this PC, from the first word.* Before, the name woke the browser's cloud recognizer, which took a moment to start, so "Jarvis, turn on the lights" in one breath lost the command and you had to say the name, wait for the sound, then speak. Now the PC keeps a couple of seconds of audio from before the name was recognised, and after the name it transcribes what you say with the same small Vosk model (free vocabulary this time), until you stop talking. "Jarvis, turn on the lights", "Hey Jarvis, what's the weather", or "Jarvis" … (pause) … "what time is it" all work, and nothing goes to the internet. On Windows' built-in voices it understood 25 of 26 test phrases (the one miss was "the house" for "a house"), about 1.3 seconds after the end of the sentence. A small model is less accurate than the cloud one for long or unusual questions, and real voices in a noisy room are harder; `JARVIS_WAKEWORD_COMMAND=cloud` in `.env` brings back the old way (the browser's cloud recognizer listens after the name). `python tools\command_eval.py <folder>` measures it (clips from `tools\make_command_clips.ps1`).
- *Voice off means the microphone is closed.* The orb (or M) is now the switch for the PC's microphone too: while voice is off the PC does not open the microphone at all, so there is nothing to hear "Jarvis" and the Windows microphone indicator goes off. The page tells the PC whether voice is on every few seconds; a page that is closed or stops answering stops counting after 20 seconds, and with no page asking, the microphone stays closed. The status panel's Wake word row says "Microphone closed" then.

**How well it works:** a list of one word makes the recognizer force similar sounds into it (in testing, "service", "jar of jam" and "harvest" woke it more than half the time), so it is also given look-alike words to choose from. With those, 10 of 10 spoken "Jarvis" phrases woke it and 0 of 30 other phrases did (Windows' built-in voices, played as files; real voices, room noise and a far-away microphone are harder, so expect some misses and the odd false wake). If something keeps waking it, add that word to `JARVIS_WAKEWORD_DECOYS` in `.env`. It listens in short blocks and wakes on its first guess, so say "Jarvis", pause a beat, then the command.

**It no longer wakes on words that aren't the name (2026-11-07).** The recognizer used to answer "Jarvis" for anything that sounded vaguely like it, and one flicker was enough to wake JARVIS: in a test with 30 minutes of ordinary talk that did not contain the name it woke about 100 times an hour. Now the name has to be the first word (or the second, after "hey") and still be what the recognizer hears over several updates in a row (a quarter of a second each), or come out as its confident final answer; a look-alike that passes for an instant (such as "Gervais") no longer counts, and one spoken sentence wakes it once. On the same test that is roughly ten times fewer false wake-ups (and in a noisy room two people talking at once still produce some), while every clip that did contain the name still woke it. If it ever seems deaf, put `JARVIS_WAKEWORD_SENSITIVITY=high` in `.env`; if it still wakes on things you did not say, use `low`. To measure a change yourself: `powershell -File tools\make_test_speech.ps1 clips`, then `python tools\wake_eval.py clips`.

## Opening web pages in Chrome

Say or type "open youtube.com", "go to github.com", "open example dot com in Chrome", or ask ("open the Wikipedia page about cats", "search Google for pizza") and the page opens in a new Chrome tab (the default browser if Chrome isn't found; `JARVIS_CHROME=C:\path\chrome.exe` if it can't find it by itself). A site you name by its address opens instantly with no AI request. `JARVIS_BROWSER=0` in `.env` turns it off.

An AI that can open pages is a risk if it can be tricked, so it is limited the same way the other tools are (`server/browser.py`):

- **Web addresses only:** http and https. Never `file:`, `javascript:`, `data:`, `chrome:`, `ms-settings:`, `ftp:` or any other link that could run something or reach into the PC; an address with a user name or password, a backslash or control characters, or over 2,000 characters is refused.
- **Public websites only.** This PC and your home network are refused: `localhost`, `192.168.x.x`, `10.x.x.x`, the router, names ending in `.local` or `.lan`, numbers written oddly (`127.1`, `2130706433`), and a normal-looking name that turns out to point at one of them. The page JARVIS itself serves can't be reached through it.
- **It only ever hands Chrome the address:** no flags, profiles or scripts. At most 6 pages a minute. Every opening is in the activity log.
- **When the AI chooses the page, you press Allow first,** on a card that shows the exact address, in three cases: after it has read your private data (an address's text can carry data out), after it has read a web page or search result in this turn (the page could be telling it where to go), and for a site you never named (a site counts as named when its main name, like "youtube" in youtube.com, is in something you wrote; "open the news" does not name `news.badsite.com`). Opening a site you just asked for needs no click. What the AI writes itself never counts as you naming something.

What it can't protect you from: the page you open is an ordinary web page, so Chrome's own protections (Safe Browsing, download warnings) apply and nothing more. Decline any card you don't expect. `JARVIS_BROWSER=0` turns off both the spoken or typed shortcut and the AI's tool.

## Security: what protects you, and what to watch

- **Other web pages can't use JARVIS.** It only listens on this PC, but a page open in your browser could still send requests to `localhost:8000` (or trick the browser into treating its own address as localhost). Every request must be addressed to localhost, 127.0.0.1 or [::1], and if the browser says which page it came from, that must be JARVIS's own page. Anything else is refused (with the pen WebSocket too) and logged. The page also carries browser safety headers: no framing, no guessing file types, and a content policy that lets it load only its own scripts and talk only to JARVIS and the weather service. Programs that send no origin, like the pen tracker, work as before.
- **No internet lookups after private data, unless you say yes.** Once a conversation has read your mail, calendar, Discord or workspace files, `web_search` and `fetch_url` ask first, showing exactly what they would send (a web address can carry your data in it, and text in an email can try to make the AI do exactly that). It stays on for the rest of that conversation (until you reload the page).
- **Your keys are no longer in OneDrive.** JARVIS reads `%LOCALAPPDATA%\jarvis\.env` first and falls back to the project's `.env` (the old place). Keep keys in the local one. If a `.env` was ever in the project folder, OneDrive may still hold old copies: look in its web recycle bin and version history at onedrive.live.com, and if you're not sure who could have seen them, make new keys and revoke the old ones.
- **Activity log:** the status menu's *Activity log* lists every tool JARVIS used for you (what it asked for, never what came back), what you refused, and what was blocked, with a lock on anything involving private data. The raw file is `%LOCALAPPDATA%\jarvis\logs\activity.log`.
- **Still true:** approved Python and MCP tools run as you with your permissions, so only approve what you understand. Free AI models may keep what you send them. Google's sign-in token is encrypted with Windows data protection (see below), but any program running as you can ask Windows to decrypt it; revoke it any time at myaccount.google.com/permissions.

- **The Google sign-in is encrypted on disk** with Windows' own data protection (DPAPI). The file in `%LOCALAPPDATA%\jarvis` is unreadable if it is copied elsewhere, backed up, or opened by another Windows user; the old plain-text file was converted automatically. This does not stop another program running as you, since Windows will decrypt it for anything you run.

## Privacy screen

Say **"Jarvis, privacy"** (or "lock the screen"), press **H**, or use *Lock the screen now* in the status menu: the whole wall goes black, with a lock and the clock. While it is down **the server answers nothing** (chat, memory, board, mail, usage... all refused), nothing is spoken, and other voice commands are ignored, so a guest can't ask JARVIS for your information. To bring it back:
- **Say** "Jarvis, privacy unlock five one four seven" (say the digits one by one; "5147" and "51 47" also work, "fifty-one forty-seven" does not), or
- **touch the screen** (or hover and tap with the pen) to get a keypad, or
- type the digits on the keyboard.

The code is 4 to 8 digits, set under *Privacy > Unlock code…* in the status menu (changing it needs the current one). It is stored only as a salted hash. Five wrong tries in a row lock you out for 30 seconds, doubling each time up to 15 minutes, even for the right code. It stays locked across restarts and page reloads. With no code set, a touch unlocks it (just a curtain). **Be realistic about what it is:** a curtain for casual eyes. Anyone who hears you say the code can use it (use the keypad when people are listening), and someone who can use your PC can still read its files.

## Actions that ask first

Three tools change something outside JARVIS. Each is prepared, then shown to you as a card with exactly what it will do, and only happens if you press Allow (Don't allow does nothing and JARVIS is told not to retry):
- **Gmail draft reply:** "draft a reply to Sam saying 7pm works". It saves a **draft** to the original sender only. **JARVIS cannot send email**, it never asks for that permission; you open Gmail, read the draft and send it yourself.
- **Calendar event:** "put dentist on Friday at 2". Shows title, date, time and place first. No invitations are sent.
- **Discord message:** "tell #general the meeting is at 5". Shows the channel and the exact text; the message can't ping @everyone, @here or roles.

Gmail drafts and calendar events need extra Google permissions: run `connect.bat google write` once (it opens the same sign-in page and asks for "compose drafts" and "manage calendar events", on top of the read-only ones). Until you do, JARVIS isn't offered those two tools. Discord sending needs your bot to have the *Send Messages* permission. Every action also appears in the activity log.

## Connect Calendar, Gmail and Discord

All three are **read-only**: JARVIS can look but not send, reply, delete or create. Each tool only appears once you've set it up. Ask things like "what's on my calendar tomorrow?", "any unread email from Sam?" or "what's new in #general?". Put anything long-term (more apps) in the same place: `server/agent.py` (`TOOLS`, `CONNECTORS`, `_run_lookup`).

**Privacy:** what these tools return is sent to the AI model to answer you. With OpenRouter's free models that text may be logged or used for training by the model's provider. Don't connect an account whose contents you wouldn't want that to happen to, or use a paid or local model for these questions.

**Google (Calendar + Gmail), once, about 10 minutes:** run `connect.bat google`; if it isn't set up it prints these steps.
1. Create a project at <https://console.cloud.google.com/>, and under APIs & Services > Library enable the **Google Calendar API** and the **Gmail API**.
2. OAuth consent screen: User type *External*, your email, and add yourself under *Test users*. Then press **Publish app**, otherwise Google cancels the sign-in every 7 days. Google shows an "unverified app" warning when you sign in; it's your own app, so choose Advanced > Continue.
3. Credentials > Create credentials > OAuth client ID > **Desktop app**. Download the JSON and save it as `%LOCALAPPDATA%\jarvis\google_client.json`.
4. Put the downloaded file where JARVIS reads it by double-clicking `install_google_client.bat` (it finds the newest `client_secret*.json` in Downloads or on the Desktop; or `connect.bat install "C:\path\file.json"`). Then run `connect.bat` (or `connect.bat google`). Whatever it shows is also saved in `%LOCALAPPDATA%\jarvis\connect.log`, and the usual Google problems (a test user missing, the 7-day expiry of an app in Testing mode, an unverified-app warning) are explained when they happen. Your browser opens Google's sign-in; approve the two read-only permissions. JARVIS saves a refresh token in `%LOCALAPPDATA%\jarvis` (outside OneDrive) and never sees your password. Remove access any time at <https://myaccount.google.com/permissions>.

**Discord, once, about 5 minutes:** Discord doesn't allow programs to read a personal account (that breaks its rules and risks a ban), so JARVIS reads servers where **your own bot** is a member.
1. <https://discord.com/developers/applications> > New Application > Bot: *Reset Token* and copy it; turn on **Message Content Intent**.
2. OAuth2 > URL Generator: scope `bot`, permissions *View Channels* and *Read Message History*. Open the link and add the bot to your server.
3. Paste the token into `.env` as `DISCORD_BOT_TOKEN=` yourself (never share it), then run `connect.bat discord`. It lists the channels the bot can see.

Restart the board after connecting. A bot can't read your DMs with other people, only servers it has joined.

## Other providers

Everything goes through the OpenAI-compatible chat API, so switching is a `.env` change.

- Add a free Groq key (https://console.groq.com/keys) as `GROQ_API_KEY=` to put Groq in the chain.
- Choose your own order with `JARVIS_CHAIN=provider:model,provider:model` (providers: `gemini`, `groq`, `openrouter`, `ollama`).
- Or pin a single model with `JARVIS_PROVIDER` and `JARVIS_MODEL`.

Models that can't see images (e.g. gpt-oss) still get the note list and your question, just not the picture of the board.

## Layout

- `server/` FastAPI app: `agent.py` (chat, tools, the agent loop), `agent_tools.py` (web and file look-ups), `openrouter.py` (finds the free models), `runner.py` (approved code), `store.py` (memory, usage), `diagnostics.py` (system health and alert rules), `fixes.py` (safe repairs that ask first), `lights.py` (Govee lights), `music.py` (YouTube Music on speakers), `persona.py` (personality), `holo.py` (checks for hologram data), `news.py` (headlines), `apps.py` (opening and closing apps), `main.py` (routes). In `web/`: `holo.js` (3D and charts), `boot.js`, `sounds.js`, `news.js`, `settings.js` (settings kept on the PC).
- `server/phone.py` and `web/phone/`: the phone door (separate port, pairing, chat) and the phone page. `web/` the interface: `modern.css`, `look.js` and `theme.js` (the modern/classic look), `board.js` (canvas and notes, takes input through `penDown/penMove/penUp`, which is where the IR pen will plug in), `chat.js`, `voice.js` (wake word and speech), `app.js`.
