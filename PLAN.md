# JARVIS Projected AI Whiteboard: Build Plan

Last updated: 2026-11-05

## 1. Goal

A wall-projected interactive whiteboard with an AI assistant named JARVIS. You write on the wall with an infrared pen (or, as a free fallback, point with a finger) to draw and press buttons, and JARVIS reads the board, answers questions, cleans up sketches, and runs code. It is also a room assistant: voice, lights, music, reminders, system health, and a phone companion. The LLM runs in the cloud on free tiers.

**Scope (updated 2026-11-05):** the projector, an IR camera with a small filter, and an IR pen, within a $150 budget for the remaining hardware (section 4). The mini PC is optional and later; everything runs on the current laptop. The light-curtain laser (4A) was designed and then parked as too costly; the pen plan came back once a pen with three fanned LEDs solved the "LED faces away from the camera" problem (4B).

**Status:** the software side is far ahead of the hardware. Almost everything in section 10 works today with a mouse, a webcam finger tracker or a simulated pen; the pen, camera and filter still have to be bought and tested on the wall (section 8).

## 2. Fixed constraints

| Item | Decision |
|---|---|
| Budget | **$150 or less for all remaining hardware, not counting the projector** (decided 2026-11-01; replaces the earlier $200/$250 that included a mini PC) |
| Mode | Wall whiteboard (desk mode kept as a later config option) |
| Projector | GooDee LED projector (likely 720p) on top of the display cabinet |
| Throw | 8 ft 6 in to the opposite wall, about 70-80 in wide image (estimate; measure it) |
| Orientation | Mounted upside down with "Front Ceiling" mode, so the image sits at standing height (about 2 ft 9 in to 6 ft 3 in) |
| Mounting | **No drilling.** Everything sits on the cabinet top |
| Vibration | A train line nearby shakes the room, so the image and camera can move |
| Mini PC | Not bought and not in the budget. Everything is developed and runs on the current Windows laptop; a mini PC is a later option (Test 4) |
| LLM | Free tiers only: a chain of Gemini models and Groq models (Gemini allows about 20 requests/day per model) |
| Borrowed gear | Friend's IR webcam (Logitech BRIO) was for testing only and cannot be kept; the Arducam replaces it |

## 3. Stability and calibration strategy (your priority order)

Calibration is a stored map from camera pixels to projector pixels. If the camera or projector moves, the map is wrong and the ink lands away from the pen tip.

Your ranking: **#5 drift check (best), then #4 quick recalibration and #1 rigid base (tied second).** The plan builds all three in that order, because they cost little.

### 3.1 Drift check (#5, primary)

- The software periodically checks that the camera, the projected image and the wall still line up.
- If it sees a shift, it corrects the calibration in the background. If the shift is too large, it shows a "recalibrate" prompt.
- Small fixed marks near the edges of the image act as reference points. A mark is only useful if the camera can see it.

**Open issue to settle in Test 2/3:** an 850 nm bandpass filter blocks all visible light, so the camera can't see the projected marks through it. Options, in the order I'd try them:

1. **Removable filter:** the filter slides or clips on and off the camera. The drift check flips to visible light for a second when you're idle.
2. **No filter, low exposure:** the IR pen is far brighter than the projected image, so a short exposure shows only the pen. The check raises exposure briefly to see the marks. Works best with a dark UI (black background).
3. **Second visible-light webcam** that only does the drift check. Costs about $10-15 used.

Decide after testing with the borrowed webcam.

### 3.2 Quick recalibration (#4)

- One button or voice command ("JARVIS, recalibrate").
- The projector shows 4 targets, you touch each with the pen, and it recalculates in about 10 seconds.
- Saved to disk so it also works as the starting point on reboot.

### 3.3 Rigid base (#1)

- Projector and camera bolted or clamped to one plywood or 3D-printed plate, so they move together.
- Plate sits on museum putty or non-slip pads so it can't creep.
- Strap the cabinet to the wall with an anti-tip strap. If no screw into a stud is allowed, use a tension strap or a wedge instead.
- Because the camera and projector share one base, the camera-to-projector relationship stays fixed even when the base moves, which removes most of the error.

### 3.4 Measure the problem first (free)

Before spending anything on stability, run the test pattern for a day. Log how much the image moves when a train passes. If it barely moves, the drift check might be all you need.

## 4. Hardware and budget

**Budget (2026-11-01): $150 or less for everything still to buy, not counting the projector.** Exact parts, links, wiring and the budget table are in **PEN_PARTS.md**; this is the summary.

| Part | Cost (estimate) | Notes |
|---|---|---|
| Arducam B0332 camera (OV9281, 1280x800, global shutter, 100 fps in MJPG, UVC, M12 lens, no IR-cut filter). Amazon ASIN B096M5DKY6 | $50-63 | The biggest single cost. Pick MJPG (only 10 fps in YUY2) |
| Small 850 nm-passing filter: an HWB830 / RG830 black-glass disc, about 12 mm, **cut-on 830 nm or lower**, glued over the lens | $5-12 | **Not** the 850 nm one: its cut-on equals the LED's wavelength, so it would absorb much of the pen's light. Not the $72 filter either |
| Pen parts: 3 x 850 nm 5 mm LEDs (60 degrees, 20 mA), 3 x 68 ohm resistors, normally-open push button, 2 x AAA holder (no switch), pen body | $20-30 | LED packs and kits cover far more than needed |
| **Touch system total** | **about $75-105** | |
| Microphone (optional): EMEET M0 / M0 Plus conference mic | about $50 | The laptop's own speakers and microphone already work, so this can wait |
| Mini PC | not in the budget | Only if the laptop can't stay on the wall; develop on the laptop first |
| Rigid base plate, putty, anti-tip strap | $10-15 | Likely from things already owned; counts toward the $150 if bought |

Everything: about $125-155, so only the top end could pass $150. If it creeps over, skip the microphone. The cloud LLM costs $0 on free tiers. The projector, keyboard and mouse are already owned.

Prices are estimates and were not all checked (Amazon blocks automated readers). Check each page for 4.3 stars or more and read the 1-2 star reviews before buying.

## 4B. Touch method, rethought (2026-10-26)

The laser turned out costlier and fiddlier than first thought (4A), so the touch method was reconsidered. Options, cheapest first:

| Option | Hardware beyond the PC | Accuracy | Status |
|---|---|---|---|
| 1. **Camera-only finger pointing**: find the hand by skin colour and motion, take the point farthest from the arm as the fingertip, hold still about 0.8 s to tap | An ordinary colour webcam (the BRIO now; Windows also lists an old Logitech C922, which may still be owned) | A few cm; no contact sensing, shifts if the hand is held in front of the wall | **Built** (`--mode finger`) |
| 2. Option 1 plus **knock detection**: a microphone hears the tap on the wall and fires the click exactly when the finger touches, at the position the camera shows | A microphone (the BRIO has one; a $2 contact piezo is another option) | Click timing exact; position still a few cm | Idea, not built |
| 3. Option 1 with **hand landmarks (MediaPipe)** for a steadier fingertip and a pinch-to-click gesture | None | Better fingertip; works in the air | **Built and now the default** (`--mode finger`): MediaPipe 1.1.1 installed in the venv (it replaced opencv-python with opencv-contrib-python) and the 7.5 MB hand_landmarker.task model sits in %LOCALAPPDATA%\jarvis\models. About 14 ms per 1280x720 frame |
| 4. **Light curtain** (section 4A): battery-powered 850 nm line laser along the wall | Laser ($40-200), Arducam camera, filter | Millimetres; true touch | Parked: designed, laser never sourced, too costly for the budget |
| 5. **IR pen**: three fanned 850 nm LEDs, a push button, 2 AAA | Pen parts $20-30, Arducam camera, small 830 nm filter | Millimetres at the pen tip | **Chosen.** Software is built (tracker, calibration); parts not bought yet (PEN_PARTS.md) |

**Current choice (2026-11-02): option 5, the IR pen, on a $150 budget.** The earlier worry (an LED pointing at the wall, away from a camera behind you) is handled by fanning three 60 degree LEDs on the pen (about 130 degrees) and mounting the camera beside the projector. Finger mode (options 1 and 3) stays available for free with any colour webcam and is the fallback while the parts ship. The light curtain (option 4, section 4A) is parked: the laser alone would eat the budget.

## 4A. Light curtain design (parked alternative: not in the current plan)

*Status 2026-11-05: the plan went back to a pen (section 4B), so none of this is being bought. It stays here in case precise bare-finger touch is wanted later; the laser budget would not fit inside $150.*

A fan of invisible 850 nm light is spread into a flat sheet a few millimetres in front of the wall. Nothing glows until something enters the sheet. A fingertip that touches the wall (or comes within a few mm) scatters the light, and the camera sees a small bright spot at exactly that place. The camera can sit anywhere that sees the wall, so it stays on the cabinet with the projector.

### 4A.1 Geometry
- Put the laser at the top-left corner of the board area (above the top edge), aimed along the wall. A 90 degree fan from the corner covers the whole rectangle; use a 100-120 degree fan or a slight margin so the far edges are covered.
- Light intensity in the sheet falls off with distance, so touches far from the laser are dimmer. A second laser at the top-right corner evens this out and covers the shadow a hand casts, but start with one.
- The sheet must be 3-5 mm from the wall: closer catches the wall's texture and bumps (false touches), farther means touches register before contact.

### 4A.2 Mounting (no drilling, no wires)
- The laser and its battery form one small self-contained unit on the wall: **there is no cable from the laser to the PC or to an outlet**, and nothing on the floor. The camera, projector and mini PC all sit together on the cabinet with short cables.
- Fix the unit at the top corner with removable adhesive strips (two medium strips hold far more than the roughly 100-150 g of laser plus two AA cells). Use a small bracket or foam/putty shims to tilt the sheet parallel to the wall. The adjustment is the hard part: expect to shim it.

### 4A.3 Power: batteries on the laser unit
- Choose a laser module that runs on **3 V** and power it from **2 x AA cells in a holder with an on/off switch** (red wire to +, black to -; no electronics knowledge needed). Use fresh alkaline or lithium AAs, not rechargeable NiMH (two NiMH cells give about 2.4 V, below a typical 2.7 V minimum). A 3-5 V module can use 3 AA cells instead; check the listing and never give a 3 V-only module 4.5 V or more.
- Estimated run time: a 5 mW module typically draws 20-55 mA, so two alkaline AAs (about 2000 mAh) last roughly 40-90 hours of switched-on time, which is weeks at a couple of hours a day. Verify against your module's datasheet.
- The switch has to be flipped by hand at the wall (put it where you can reach it, e.g. on the holder at the lower edge of the unit) or with a cheap 433 MHz remote-controlled relay later. Software can't switch it, so the tracker should show whether the sheet is on (see 4A.4).
- Not chosen: running a cable from an outlet or the PC (a wire across the floor or up the wall), a wall outlet adapter plus smart plug (works, but leaves a cable up the wall).

### 4A.4 Software to add (after the hardware works)
- Learn the wall's static glints: average some frames with nothing touching and subtract them, so texture and bumps don't register.
- Palm rejection: ignore blobs larger than a fingertip; keep the existing "pen down = light seen" logic for taps and drags.
- "Sheet on/off" indicator: when the laser is on, the wall's bumps scatter it as a faint pattern of static glints; when it is off they vanish. The tracker can watch for that and show "light sheet: on/off" in the UI, so you can tell if the battery is flat or the switch is off. It also helps with alignment.
- Optional later: two simultaneous touches (pinch to zoom the board).
- Camera: use a short exposure so the room's ambient IR disappears and only the laser scatter remains.

### 4A.5 Safety (important)
- The laser is **invisible**, so the eye does not blink away from it. 5 mW class 3R modules can injure an eye at close range. Use the lowest power that works (5 mW or less), mount it so the sheet runs along the wall and never points out into the room, never look into the aperture (even when "off", assume it could be on), unplug it when not in use, and keep it away from children and pets.
- Check the module's label for wavelength, power and class when it arrives. Buy a reputable listing; mislabelled wavelength and power are common on cheap listings.
- A phone's front camera or the BRIO can show the line (as a purple-white glow) for alignment, so you never need to look at it directly. IR-rated laser safety glasses are a sensible extra for alignment.

### 4A.6 First test, before buying the camera
The loaned BRIO's IR sensor is probably tuned to about 850 nm (the 940 nm remote was barely visible to it), so it is a fair first test of whether a fingertip glows visibly in the sheet. It is a weak camera for this (340x340 pixels, and its own IR light and short "ambient" frames get in the way), so a pass is a good sign and a fail is inconclusive. The Arducam would see far more.

## 5. Test phases

Each phase has a pass condition. Don't buy the next group of parts until the current phase passes.

### Test 0: Whiteboard app on a monitor ($0-10)
- Fullscreen app with pen drawing (mouse for now), sticky notes, and a JARVIS chat panel.
- AI features: clean up sketches, read handwriting, solve written problems, turn sketches into code and run it, sort notes into a to-do list.
- **Pass:** it works on a regular monitor.

### Test 1: Projector placement and stability ($10-15)
- Put the projector upside down on the cabinet and use ceiling mode.
- Measure image width, the top and bottom edge heights, focus and brightness with the blinds open and closed.
- Build the rigid base. Run the test pattern through a day of trains.
- **Pass:** the image fits on the clear wall (left of the bed) and moves less than about 1 cm during a train pass.

### Test 2: Pen and camera first look ($50-85: camera, small filter, pen parts)
- Buy the Arducam, the small 830 nm filter and the pen parts (PEN_PARTS.md). Build the pen and check it on a phone's front camera. Fit the filter over the lens.
- Run `run_tracker.bat --view` with the pen's button held, near the middle of the board, then run the 9-target calibration.
- **Pass:** the pen shows as a clear bright dot at 8.5 ft, with the projector on and the blinds open, and the room's window and lamp light don't create false points. If the dot is too dim, add a fourth and fifth LED before changing anything else.

### Test 3: Write on the wall
- Mount the camera on the rigid base next to the projector, set a short exposure, set MJPG at 1280x800 100 fps, and calibrate.
- Add the drift check and (if the room needs it) static-glint learning.
- **Pass:** the pen draws smooth lines with no visible lag, edges and corners of the board work, and the drift check catches a deliberate nudge of the base.

### Test 4: Buy the mini PC (optional, ~$90, only if the laptop can't stay on the wall)
- The $150 budget does not include one, so this is only after everything works on the laptop. Move the app over and set it to start on boot.
- **Pass:** the whole setup works with no laptop attached.

### Test 5: Make it robust (optional)
- If a laser light curtain (4A) is wanted later, add the line laser here; or add a second pen, a pen holder, and a quicker "recalibrate" voice command.
- **Pass:** touches across the whole board are equally reliable.

### Test 6: Voice (about $0-50)
- Browser voice ("Jarvis, ...") and the offline wake word already work with the laptop's microphone and speakers. A USB conference mic (EMEET M0, about $50) is optional and should be set as both the Windows speaker and microphone so echo cancellation removes JARVIS's own voice.
- **Pass:** it hears you from where you sit and doesn't wake on its own speech.

### Later
- Widgets, holographic keyboard, gestures, split layout (writing area on the left, display-only panels above the bed).
- **Optional, only after the pen and camera work (decided 2026-11-02): Makeblock CyberPi as a desk status light.** The user already owns one (ESP32, 128x128 screen, 5 RGB LEDs, buttons/joystick, motion sensor; USB-C and Wi-Fi/Bluetooth; MicroPython or the `cyberpi` library, whose documentation is thin). Keep it tiny: it only shows listening / thinking / alert and has one button to interrupt JARVIS, one-way status from the PC plus button presses back, any action still going through the confirm-first rules. Off by default so it adds nothing unless plugged in. Skipped for now because the projected wall already shows the same status and it is one more thing that can break; not a purchase ($0, so no effect on the $150 budget).

## 6. Software architecture

```
Mini PC
  Camera service (Python + OpenCV)
    camera frames -> find pen/finger blobs -> map to projector coords
    drift check + calibration store
          | local WebSocket
  Whiteboard UI (browser or Electron, fullscreen on the projector)
    canvas, sticky notes, JARVIS chat, widgets
          |
  JARVIS core (Python)
    LLM client (cloud) with spending cap
    memory: facts about you (SQLite)
    tools: sandboxed code runner, files, web
    voice: wake word -> speech-to-text -> LLM -> text-to-speech
```

- UI uses a black background with glowing lines, because projectors can't show black, so UI elements appear to float on the wall.
- Code execution runs in a sandbox, and destructive actions need a confirmation.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Image too dim in daylight | Close the blinds, dark UI, test at different times |
| Cabinet rocks from trains | Strap it, rigid base, putty, drift check |
| Camera can't see projected marks through the filter | Section 3.1 options |
| Shadow and arm blocking the camera | Camera on the side away from the writing hand |
| Image partly over the bed | Split layout, keep writing area on the left |
| Invisible laser is an eye hazard | Section 4A.5: 5 mW or less, mounted along the wall, never looked into, unplugged when idle |
| Cheap laser listings mislabel wavelength or power | Buy from a listing that states 850 nm and mW; verify with the BRIO or a phone camera on arrival |
| Wall texture or bumps cause false touches | 3-5 mm sheet gap, learn and subtract static glints (4A.4) |
| User's hand or body blocks the laser sheet (shadows) | Second laser at the other top corner (Test 5) |
| Fingertips too small or dim for the camera 8.5 ft away | The Arducam's 70 degree lens at 8.5 ft covers about 3.6 m, so about 2.8 mm per pixel: a 15 mm fingertip is about 5 pixels. Use a short exposure and the 850 nm filter; a narrower lens would help if needed |
| Laser sheet moves when a train shakes the wall | Re-aim after big shakes; the drift check will notice missed touches |
| Battery goes flat, or the laser is left switched off | "Sheet on/off" indicator (4A.4), fresh lithium or alkaline AAs, switch within reach |
| Free-tier request limits (about 20 a day per Gemini model) | Model fallback chain across Gemini and Groq |

## 8. Next steps (2026-11-05)

Software is ahead of hardware now, so the next real progress needs parts. In order:

1. **Order the touch parts** from PEN_PARTS.md (camera about $50, small 830 nm filter, pen parts $20-30). Check each Amazon page for 4.3 stars or more before buying. The microphone is optional.
2. **While they ship:** put the projector upside down on the cabinet in ceiling mode, set the corners with Fit to wall (J), measure the image, and run the test pattern through a day of trains (section 3.4).
3. **Build the pen** (three 850 nm LEDs fanned out, 68 ohm each, push button, 2 AAA) and check it glows on a phone's front camera.
4. **When the camera arrives:** run Test 3 below: calibrate, write on the wall, add the drift check.
5. **Meanwhile, pick from the ideas backlog (section 11)**: the morning briefing and scenes are the best value for the least work.

## 9. Open questions

- Exact projector model (sticker on the underside)
- Cabinet height and ceiling height
- Whether the $150 budget includes shipping and tax (not stated)
- ~~Borrowed webcam model~~: Logitech BRIO (the 4K model with a separate IR sensor and IR light for Windows Hello). **Tested 2026-10-26.** Its IR stream is hidden from normal apps and OpenCV, and Windows only offers it when the camera is opened with *exclusive control* (shared read-only shows colour only). The `whircam` package reads it once its sharing mode is switched. Findings: 340x340 pixels, 8-bit grey, 30 fps; frames alternate between "IR light on" (wall lit, mean brightness ~80) and "IR light off" (ambient, nearly black, peak ~5 of 255). A TV remote (940 nm) was bright only in the lit frames, from reflecting the camera's own IR light, and almost invisible in the dark frames. Conclusion: the BRIO proves the software path works, but it is too low-resolution and slow and its own IR light confuses tracking, so still buy a dedicated camera. An 850 nm pen was not tested. The BRIO also has a microphone.
- Which electronics parts you already have (battery holders, resistors, wire, a marker for the pen body)
- Whether a stud is available for an anti-tip strap behind the cabinet
- Phone: whether Android Chrome's speech recognition works well over the self-signed HTTPS page (built and tested in a desktop browser only, not yet on the real phone)

## 10. Software built so far (2026-11-05)

Everything below runs on the current Windows PC; the README has the how-to for each. 522 automated tests pass. All of it is committed to git (no remote yet).

- **Board and AI:** whiteboard (pen, eraser, notes, undo, saved on the PC), chat with a free-model fallback chain, AI that reads and edits the board, long-term memory, spending/request counters, agent mode with confirm-first actions (an Allow card before anything that changes the outside world), an activity log, Calendar and Gmail drafts (Google), Discord, and MCP tool connections.
- **Voice and personality:** browser voice with natural Edge voices, optional offline wake word, interrupting an answer, a witty personality (sarcasm level adjustable), a privacy screen with an unlock code, and typed chat commands that work like spoken ones.
- **The room:** Govee lights (local network), YouTube Music on the Nest Hub, opening and closing apps with limits (never Settings or Control Panel), system health with safe one-click fixes, Claude Code "finished" alerts, weather, timers, news ticker, holograms and charts, show-off mode, a start-up sequence with sounds.
- **Looks (2026-11-05):** a modern calm-glass look (default) and the original neon look as "Classic", switchable in the status menu; slow-cycling side lights; a screen saver that shows only the orb and the time.
- **Phone (2026-11-04):** a separate small HTTPS server on the home Wi-Fi for text and voice from an Android phone: pairing with a code, no "Allow" actions from the phone, privacy screen locks it out. Phone alerts for reminders, finished timers, Claude finishing and new system problems arrive while the phone page is open (no background push: that would need an outside service).
- **Reminders (2026-11-05):** saved on the PC, spoken with a wall note, delivered late if nobody could hear them, listed and cancelled by voice.
- **Touch software:** the pen tracker (finds a bright IR point, smooths, calibrates with 9 targets), finger mode with MediaPipe hands, the tracked point used as a pointer across the whole interface, the holographic keyboard, touch mode, and Fit to wall. Not built yet: the drift check, wall-glint learning, palm rejection.
- **Start with Windows:** `install_autostart.bat` / `remove_autostart.bat`; `JARVIS.bat` keeps the server running and opens the board window.

## 11. Ideas backlog (nothing here is started)

In rough order of value for effort:

1. **Morning briefing:** the first time the screen wakes, JARVIS gives weather, today's calendar, headlines and any system alerts. All the pieces exist.
2. **Scenes:** "movie mode" (dim the lights, calm mode, pause music), "focus mode", and so on, defined once and called by name.
3. **To-do list on the wall:** "add milk to my list" and "what's on my list", kept as a saved checklist note.
4. **Follow-up without repeating "Jarvis":** keep listening about ten seconds after an answer.
5. **Real background phone notifications** through the free ntfy app. Skipped so far because reminder text would pass through an outside server; the in-page alerts already work.
6. **CyberPi desk status light** (see "Later" in section 5). Parked until the pen works.
7. Hands-free conversation, presence detection and gestures (need the camera), and an offline wake word plus Whisper and Piper for privacy.
8. **Housekeeping:** add a remote for the git repo (backup off this PC), and move any remaining keys out of the project folder.
