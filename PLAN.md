# JARVIS Projected AI Whiteboard: Build Plan

Last updated: 2026-10-26

## 1. Goal

A wall-projected interactive whiteboard with an AI assistant named JARVIS. You touch the wall with a finger (or any pen or stick) to draw and press buttons, and JARVIS reads the board, answers questions, cleans up sketches, and runs code. The LLM runs in the cloud. Widgets and a holographic keyboard come after the whiteboard works.

**Scope (updated 2026-10-26): the projector, an IR camera with a filter, an invisible IR "light curtain" (a line laser along the wall), and a mini PC.** The earlier IR-pen plan was dropped: a pen's LED points at the wall, away from a camera behind the user, so it was hard to see. Touch is now detected by the light curtain instead (section 4A). No pen is needed, though one could be added later as an extra. No ESP32. Improving the projector setup is a separate discussion for later.

**Built so far (all free software, $0 spent):** the whiteboard app (pen, eraser, notes, undo, glowing UI), JARVIS chat with a free-model fallback chain, JARVIS drawing and editing the board, browser voice ("Jarvis ..."), and the fit-to-wall tool (test pattern and corner-pin). Also built (2026-10-26): the pen tracker prototype (`python -m tracker`, `run_tracker.bat`): finds the pen's light, smooths it, sends pen down/move/up to the board, and runs the 9-target calibration from the ◎ button; 14 unit tests pass and a simulated pen draws correctly end to end. Also built: the tracked point works as a pointer across the whole UI (taps, note drags, slider), a holographic on-screen keyboard (⌨ / B), and touch mode with bigger controls (☝ / T). All checked with simulated events, including under a strong corner-pin. The tracker finds any small bright spot, so a fingertip glowing in the light curtain will be tracked by the same code. Not yet built: finger-specific handling (learning and ignoring the wall's static glints, rejecting palms, optional two-finger touch), and the drift check.

## 2. Fixed constraints

| Item | Decision |
|---|---|
| Budget | $200 target, $250 hard max (includes the mini PC) |
| Mode | Wall whiteboard (desk mode kept as a later config option) |
| Projector | GooDee LED projector (likely 720p) on top of the display cabinet |
| Throw | 8 ft 6 in to the opposite wall, about 70-80 in wide image (estimate; measure it) |
| Orientation | Mounted upside down with "Front Ceiling" mode, so the image sits at standing height (about 2 ft 9 in to 6 ft 3 in) |
| Mounting | **No drilling.** Everything sits on the cabinet top |
| Vibration | A train line nearby shakes the room, so the image and camera can move |
| Mini PC | Not bought yet. Develop on the current Windows PC first |
| LLM | Free tiers only: a chain of Gemini models and Groq models (Gemini allows about 20 requests/day per model) |
| Borrowed gear | Friend's IR webcam for testing only, cannot be kept |

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

| Part | Cost (estimate) | When to buy |
|---|---|---|
| IR line laser: **850 nm, 5 mW or less, 90-120 degree fan, 3 V, adjustable focus**, x1 (a second for the other top corner later). **Not yet sourced: the earlier $10-20 guess was wrong.** Found so far: certified modules cost far more (Picotronic LC850-5-3-F, 850 nm, 5 mW, 3 V, 90 degree, about EUR 176 plus VAT; Edmund Optics 850 nm 30 degree line head $174), and the cheap eBay listings found (about $38-40) were spot lasers, not line generators. A hobby-grade spot laser plus a separate line-generator lens may be the budget route | about $40-70 hobby-grade (unverified), $150-200 certified | First: it decides whether the idea works, but find a verified listing before buying |
| Battery power and mounting for the laser: 2xAA holder with on/off switch, 2 fresh AA cells (lithium or alkaline), removable adhesive strips, foam or putty shims. No cable to the PC. Pick a laser that runs on 3 V | $8-15 | With the laser |
| Arducam B0332 camera (OV9281, 1280x800, global shutter, 100 fps in MJPG, UVC, M12 lens, no IR-cut filter, no microphone). Also sold on Amazon as "Arducam 100fps Mono Global Shutter USB Camera, 720P OV9281 UVC", ASIN B096M5DKY6 | ~$50 (Arducam's own store, before shipping and tax) to ~$63 (RobotShop, tariffs included); Newegg resellers $99-142, avoid. Amazon price not checked | After the laser passes its first test |
| 850 nm bandpass filter, round, about 12-25 mm, held in front of the lens | $8-20 | With the camera |
| Rigid base plate, putty, anti-tip strap | $10-15 | With the projector setup |
| Used mini PC (8th-gen i5, 8 GB or more, SSD, adapter included, HDMI) | $70-110 | Last |
| **Total (one hobby-grade laser)** | **~$185-295** | Over the $250 hard max at the high end. Without the mini PC (use the current PC for now) it is about $115-185. A second laser adds $40-70 |

Not included: a microphone. Voice commands need one, so use a headset or webcam mic you own, or budget $10-20. The cloud LLM costs $0 on free tiers. The projector, keyboard and mouse are already owned. The IR pen is no longer needed; cancel it if it hasn't shipped.

Prices are estimates and were not all checked. The Arducam price is from the retailer page above; the laser and filter ranges are guesses because no verified cheap 850 nm line-laser listing was found (the lab-grade ones found cost EUR 140-250, far above budget). Buy a laser only from a listing that states 850 nm and the power, and check it on arrival (see 4A.5).

## 4B. Touch method, rethought (2026-10-26)

The laser turned out costlier and fiddlier than first thought (4A), so the touch method was reconsidered. Options, cheapest first:

| Option | Hardware beyond the PC | Accuracy | Status |
|---|---|---|---|
| 1. **Camera-only finger pointing**: find the hand by skin colour and motion, take the point farthest from the arm as the fingertip, hold still about 0.8 s to tap | An ordinary colour webcam (the BRIO now; Windows also lists an old Logitech C922, which may still be owned) | A few cm; no contact sensing, shifts if the hand is held in front of the wall | **Built** (`--mode finger`) |
| 2. Option 1 plus **knock detection**: a microphone hears the tap on the wall and fires the click exactly when the finger touches, at the position the camera shows | A microphone (the BRIO has one; a $2 contact piezo is another option) | Click timing exact; position still a few cm | Idea, not built |
| 3. Option 1 with **hand landmarks (MediaPipe)** for a steadier fingertip and a pinch-to-click gesture | None | Better fingertip; works in the air | **Built and now the default** (`--mode finger`): MediaPipe 1.1.1 installed in the venv (it replaced opencv-python with opencv-contrib-python) and the 7.5 MB hand_landmarker.task model sits in %LOCALAPPDATA%\jarvis\models. About 14 ms per 1280x720 frame |
| 4. **Light curtain** (section 4A): battery-powered 850 nm line laser along the wall | Laser ($40-200), Arducam camera, filter | Millimetres; true touch | Designed; laser not yet sourced |
| 5. IR pen or retroreflective stylus | Pen, camera, filter | Millimetres | Dropped: an LED faces away from a camera behind you |

Recommended path: start with 1 (free), add 2 for real click timing, and only buy into 4 if precise writing matters. For finger pointing any colour webcam works, so the Arducam, filter and laser are not needed unless option 4 is chosen.

## 4A. Light curtain design

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

### Test 2: Light curtain first look, with the borrowed BRIO (~$20-35)
- Buy the line laser and its power and mount (the cheapest parts). Mount it at the top-left corner, align the sheet along the wall (section 4A), check its wavelength with the BRIO or a phone's front camera.
- Run `run_tracker.bat --frames all --view` with a bare fingertip touching the wall near the middle of the board.
- **Pass:** a touching fingertip shows as a clear bright dot, and a finger held 2 cm away does not. (A fail here is inconclusive because the BRIO is a weak camera; see 4A.6.)

### Test 3: Own IR camera and filter (~$70-85)
- Buy the Arducam and the 850 nm filter. Mount the camera on the rigid base next to the projector, set a short exposure, and run the 9-target calibration with a finger.
- Add the static-glint learning and palm rejection (4A.4) and the drift check.
- **Pass:** a finger draws smooth lines with no visible lag, edges and corners of the board work, a resting palm or sleeve doesn't register, and the drift check catches a deliberate nudge of the base.

### Test 4: Buy the mini PC (~$90)
- Move the app over and set it to start on boot.
- **Pass:** the whole setup works with no laptop attached.

### Test 5: Make it robust (optional, ~$10-20)
- Add a second laser at the top-right corner if one corner's shadow or distance falloff is a problem, and two-finger touch if wanted.
- **Pass:** a hand resting on the wall doesn't block the other hand's touches, and touches across the whole board are equally reliable.

### Test 6: Voice (~$0-20)
- Browser voice ("Jarvis, ...") is already built. It needs a microphone on the mini PC. An offline version (wake word, Whisper, Piper) is a later upgrade for privacy.
- **Pass:** it hears you from where you sit.

### Later
- Widgets, holographic keyboard, gestures, split layout (writing area on the left, display-only panels above the bed).

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

## 8. Next steps

1. Order the line laser (850 nm, 5 mW or less, 90-120 degree fan), its power and mounting parts (section 4).
2. While it ships: put the projector upside down on the cabinet in ceiling mode, set the corners with Fit to wall (J), and measure the image.
3. When the laser arrives: Test 2 with the BRIO.
4. If it looks promising, order the Arducam and the 850 nm filter, then do Test 3.

## 9. Open questions

- Exact projector model (sticker on the underside)
- Cabinet height and ceiling height
- ~~Borrowed webcam model~~: Logitech BRIO (the 4K model with a separate IR sensor and IR light for Windows Hello). **Tested 2026-10-26.** Its IR stream is hidden from normal apps and OpenCV, and Windows only offers it when the camera is opened with *exclusive control* (shared read-only shows colour only). The `whircam` package reads it once its sharing mode is switched. Findings: 340x340 pixels, 8-bit grey, 30 fps; frames alternate between "IR light on" (wall lit, mean brightness ~80) and "IR light off" (ambient, nearly black, peak ~5 of 255). A TV remote (940 nm) was bright only in the lit frames, from reflecting the camera's own IR light, and almost invisible in the dark frames. Conclusion: the BRIO proves the software path works, but it is too low-resolution and slow and its own IR light confuses tracking, so still buy a dedicated camera. An 850 nm pen was not tested. The BRIO also has a microphone, useful for voice while it's on loan.
- Which electronics parts you already have
- Whether a stud is available for an anti-tip strap behind the cabinet
