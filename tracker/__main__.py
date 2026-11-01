"""Runs the pointer tracker: python -m tracker [--mode pen|finger] [--source brio|cv:NAME|sim|simhand] ...

Reads camera frames, finds either the pen's light (--mode pen, default) or your fingertip (--mode finger), and
sends pointer events to the whiteboard server over a WebSocket. The whiteboard can also ask it to run the
calibration (touch the targets).
"""
from __future__ import annotations

import argparse
import json
import queue
import threading
import time

import cv2
import numpy as np

from . import calib
from . import hands as handmod
from .detect import PenTracker, find_blob
from .finger import FingerDetector, FingerPointer
from .sources import BrioIR, CvCamera, Simulated, SimulatedHand, demo_hand, demo_path, list_cameras

CAL_FALLBACK_NOTE = "uncalibrated: camera image stretched over the board"


class Link:
    """WebSocket to the whiteboard server. Reconnects by itself; messages sent while it's down are dropped."""

    def __init__(self, url: str) -> None:
        self.url, self.ws = url, None
        self.inbox: queue.Queue[dict] = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        from websockets.sync.client import connect

        announced = False
        while True:
            try:
                with connect(self.url, open_timeout=3) as ws:
                    self.ws = ws
                    print("connected to the whiteboard", flush=True)
                    announced = False
                    for text in ws:
                        try:
                            self.inbox.put(json.loads(text))
                        except ValueError:
                            pass
            except Exception:  # noqa: BLE001 - server down or restarting: keep trying
                if not announced:
                    print("waiting for the whiteboard server...", flush=True)
                    announced = True
            self.ws = None
            time.sleep(2)

    def send(self, message: dict) -> None:
        ws = self.ws
        if ws is not None:
            try:
                ws.send(json.dumps(message))
            except Exception:  # noqa: BLE001
                pass


def make_source(spec: str, camera: str | None = None, size: str = "640x480", fps: int = 60, color: bool = False,
                zoom: int | None = None, exposure: int | None = None, gain: int | None = None):
    if spec == "brio":
        if color:
            raise SystemExit("--mode finger needs a colour camera: use --source cv:NAME (e.g. cv:brio) or simhand")
        return BrioIR(camera)
    if spec == "sim":
        return Simulated(demo_path, realtime=True)
    if spec == "simhand":
        return SimulatedHand(demo_hand, realtime=True)
    if spec.startswith("cv:"):
        which = spec[3:]
        try:
            width, height = (int(v) for v in size.lower().split("x"))
        except ValueError:
            raise SystemExit(f"--size must look like 1280x800, not {size!r}") from None
        if which.isdigit():
            return CvCamera(int(which), width, height, fps, color, zoom, exposure, gain)
        names = list_cameras()["windows"]  # a part of the camera's name: its place in Windows' list is its index
        hits = [i for i, n in enumerate(names) if which.lower() in n.lower()]
        if not hits:
            raise SystemExit(f"No camera named like {which!r}. Windows lists: {', '.join(names) or 'nothing'}")
        print(f"camera {which!r} matched {names[hits[0]]!r}, index {hits[0]}", flush=True)
        return CvCamera(hits[0], width, height, fps, color, zoom, exposure, gain)
    raise SystemExit(f"unknown source {spec!r}: use brio, sim, simhand, cv:INDEX or cv:NAME")


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m tracker", description=__doc__)
    p.add_argument("--mode", choices=("pen", "finger"), default="pen",
                   help="pen: follow a bright IR spot. finger: follow your fingertip with an ordinary colour camera (rough)")
    p.add_argument("--source", default="brio",
                   help="brio (Windows Hello IR camera), cv:N or cv:NAME (a USB camera by index or part of its name), "
                        "sim (pretend pen) or simhand (pretend hand)")
    p.add_argument("--camera", default=None, help="for --source brio: part of the camera's name, e.g. BRIO")
    p.add_argument("--size", default="640x480", help="for cv sources: frame size, e.g. 1280x800 for the Arducam OV9281")
    p.add_argument("--fps", type=int, default=60, help="for cv sources: frame rate to ask for, e.g. 100 for the Arducam OV9281")
    p.add_argument("--zoom", type=int, default=None,
                   help="for cv sources: the camera's zoom (BRIO: 100 to 500). 200 makes a distant hand twice as big in the picture, "
                        "as long as the projected board still fits in view")
    p.add_argument("--exposure", type=int, default=None,
                   help="for cv sources: manual exposure, -4 (1/16 s) -5 (1/32 s) -6 (1/64 s). Shorter means less blur and a "
                        "higher frame rate, but a darker picture; add --gain to compensate. Default: automatic")
    p.add_argument("--gain", type=int, default=None, help="for cv sources: brightness boost 0 to 255 (with --exposure)")
    p.add_argument("--fast", action="store_true",
                   help="for cv sources: shortcut for --exposure -5 --gain 220: 30 frames a second and less motion blur "
                        "(automatic exposure drops to about 15 fps in a dim room), at the cost of a darker, grainier picture")
    p.add_argument("--list", action="store_true", help="list this PC's cameras and exit")
    p.add_argument("--probe", action="store_true", help="with --list: also open each USB camera briefly to get its size")
    p.add_argument("--frames", choices=("ambient", "illuminated", "all"), default=None,
                   help="for cameras that blink an IR light: which frames to use (default: ambient, IR light off)")
    p.add_argument("--url", default="ws://localhost:8000/ws/pen?role=tracker")
    p.add_argument("--min-peak", type=float, default=None, help="pen mode: how far above the background the spot must be")
    p.add_argument("--max-area", type=int, default=800, help="pen mode: biggest spot, in pixels, still counted as the pen")
    p.add_argument("--down-frames", type=int, default=2)
    p.add_argument("--up-frames", type=int, default=3)
    p.add_argument("--engine", choices=("auto", "mediapipe", "skin"), default="auto",
                   help="finger mode: how to find the hand. auto = MediaPipe if installed (steadier, understands pinching), else skin colour")
    p.add_argument("--behavior", choices=("pinch", "point", "draw"), default=None,
                   help="finger mode: pinch = pinch thumb and index finger to press (MediaPipe only, the default there); "
                        "point = a cursor that taps when you hold still (the default for skin); draw = the finger draws while visible")
    p.add_argument("--get-model", action="store_true", help="download the MediaPipe hand model (about 8 MB) and exit")
    p.add_argument("--roi", default="0,0,1,1",
                   help="finger mode: the part of the picture to search as x0,y0,x1,y1 fractions, e.g. 0.15,0.05,0.85,0.7 "
                        "to cover just the wall and keep your face out (skin engine) or to map just that part onto the board")
    p.add_argument("--dwell", type=float, default=0.8, help="finger mode, point behaviour: seconds to hold still for a tap")
    p.add_argument("--win", type=int, default=480,
                   help="finger mode, MediaPipe: size in camera pixels of the zoomed-in windows used to find a distant hand. "
                        "Smaller finds smaller (farther) hands but searches slower; try 320 if your hand is tiny in the picture")
    p.add_argument("--no-calibration", action="store_true", help="ignore any saved calibration")
    p.add_argument("--flip", default="", choices=("", "x", "y", "xy"),
                   help="only while uncalibrated: mirror left-right (x), up-down (y) or both (xy). Calibrating makes this unnecessary")
    p.add_argument("--view", action="store_true", help="show what the camera sees (press q in the window to quit)")
    p.add_argument("--stats", type=float, metavar="SECONDS", help="no server: run this long, print a summary, exit")
    args = p.parse_args()

    if args.list:
        found = list_cameras(args.probe)
        print("Cameras Windows knows about:")
        for i, name in enumerate(found["windows"]):
            print(f"  {i}: {name}")
        print("Cameras with an infrared sensor (for --source brio):")
        for name in found["ir_groups"] or ["(none found)"]:
            print(f"  {name}")
        if args.probe:
            print("USB cameras OpenCV can open (--source cv:N):")
            for cam in found["opencv"] or [{"index": "-", "width": 0, "height": 0}]:
                print(f"  cv:{cam['index']}  {cam['width']}x{cam['height']}")
        else:
            print("Add --probe to test each USB camera index (its light flashes for a moment).")
        print("Use --source brio --camera NAME to pick an IR camera by name, or --view to see which one you got.")
        return

    if args.get_model:
        handmod.download_model()
        return

    if args.fast:
        args.exposure = -5 if args.exposure is None else args.exposure
        args.gain = 220 if args.gain is None else args.gain
    finger = args.mode == "finger"
    engine = "skin"
    if finger:
        if args.engine == "mediapipe" and not handmod.available():
            raise SystemExit("MediaPipe or its model isn't ready. Install it and run:  run_tracker.bat --get-model")
        engine = "mediapipe" if args.engine == "mediapipe" or (args.engine == "auto" and handmod.available()) else "skin"
        if args.source == "simhand" and args.engine == "auto":
            engine = "skin"          # a drawn pretend hand is no use to MediaPipe, which looks for a real one
        args.behavior = args.behavior or ("pinch" if engine == "mediapipe" else "point")
        if args.behavior == "pinch" and engine != "mediapipe":
            raise SystemExit("--behavior pinch needs the MediaPipe engine; use --behavior point with --engine skin")
    if finger and args.source == "brio":
        args.source = "cv:brio"      # the BRIO's colour camera: its IR sensor can't see a hand any better
    try:
        roi = tuple(float(v) for v in args.roi.split(","))
        assert len(roi) == 4 and 0 <= roi[0] < roi[2] <= 1 and 0 <= roi[1] < roi[3] <= 1
    except (ValueError, AssertionError):
        raise SystemExit(f"--roi must be four fractions x0,y0,x1,y1 with x0<x1 and y0<y1, not {args.roi!r}") from None

    # A hand at the wall is small in the picture, so finger mode asks for more pixels by default.
    size = args.size if args.size != "640x480" or not finger else "1920x1080"
    source = make_source(args.source, args.camera, size, args.fps, color=finger,
                         zoom=args.zoom, exposure=args.exposure, gain=args.gain)
    mode = args.frames or ("ambient" if args.source == "brio" else "all")
    cam_w, cam_h = source.size
    calib_key = source.name + ("-finger" if finger else "")
    H = None if args.no_calibration else calib.load(calib_key)
    camera_name = getattr(source, "camera_name", source.name)
    what = f"finger ({args.behavior}, {engine})" if finger else "pen"
    print(f"USING CAMERA: {camera_name} ({source.name}, {cam_w}x{cam_h}), tracking: {what}, frames: {mode}, "
          f"{'calibrated' if H is not None else CAL_FALLBACK_NOTE}", flush=True)
    if finger and engine == "skin":
        print("Learning the empty scene: keep your hands out of the camera's view for a second or two...", flush=True)

    def to_board(x: float, y: float) -> tuple[float, float]:
        if H is not None:
            return calib.apply(H, x, y)  # a calibration already includes any mirroring the camera does
        if finger:                       # uncalibrated: the region of interest is stretched over the whole board
            bx = (x / cam_w - roi[0]) / (roi[2] - roi[0]) * calib.BOARD_W
            by = (y / cam_h - roi[1]) / (roi[3] - roi[1]) * calib.BOARD_H
        else:
            bx, by = x / cam_w * calib.BOARD_W, y / cam_h * calib.BOARD_H
        return (calib.BOARD_W - bx if "x" in args.flip else bx), (calib.BOARD_H - by if "y" in args.flip else by)

    detector = (handmod.HandTracker(window=args.win, roi=roi) if engine == "mediapipe" else FingerDetector(roi)) if finger else None

    def new_tracker():
        if finger and args.behavior == "pinch":
            return handmod.PinchPointer(to_board)
        if finger and args.behavior == "point":
            return FingerPointer(to_board, dwell_s=args.dwell)
        return PenTracker(to_board, args.down_frames, args.up_frames)

    def new_session(points):
        if finger:   # a finger is a shakier pointer than a pen light: hold longer, allow more wobble
            return calib.CalibrationSession(points, hold=12, max_jitter=10.0, lift=6, max_rms=90.0)
        return calib.CalibrationSession(points)

    tracker, session = new_tracker(), None
    link = None if args.stats else Link(args.url)
    counts = {"frames": 0, "blobs": 0, "down": 0, "move": 0, "up": 0, "hover": 0, "gone": 0}
    xs, ys = [], []
    t_begin = last_status = time.monotonic()
    notified_ready = False

    try:
        for t, frame, illuminated in source.frames():
            if illuminated is not None and mode != "all" and illuminated != (mode == "illuminated"):
                continue
            if finger:
                blob = detector.detect(frame)
                if detector.ready and not notified_ready:
                    notified_ready = True
                    print("ready: move your hand into the picture" + (", pinch thumb and index finger to press" if args.behavior == "pinch" else ""), flush=True)
            else:
                blob = find_blob(frame, args.min_peak, max_area=args.max_area)
            counts["frames"] += 1
            counts["blobs"] += blob is not None

            while link and not link.inbox.empty():
                msg = link.inbox.get()
                if msg.get("type") == "calib_start":
                    session = new_session([tuple(pt) for pt in msg["points"]])
                    tracker = new_tracker()
                    print("calibration started", flush=True)
                elif msg.get("type") == "calib_cancel":
                    session = None
                    print("calibration cancelled", flush=True)

            if session:
                for event in session.update(blob):
                    link and link.send(event)
                    if event["type"] == "calib_done":
                        if event["ok"]:
                            H = session.H
                            calib.save(H, session.rms, session.cam_points, session.board_points, calib_key)
                            print(f"calibrated, error {session.rms:.1f} px", flush=True)
                        session = None
                        tracker = new_tracker()
            else:
                for event in tracker.update(t, blob):
                    counts[event["s"]] += 1
                    if event["s"] != "gone":
                        xs.append(event["x"]); ys.append(event["y"])
                    link and link.send(event)

            now = time.monotonic()
            if link and now - last_status >= 1.0:
                link.send({"type": "status", "fps": round(counts["frames"] / (now - t_begin), 1),
                           "blob": blob is not None, "calibrated": H is not None, "source": source.name,
                           "camera": camera_name, "size": [cam_w, cam_h], "frames": mode, "tracking": what})
                last_status = now

            if args.view:
                if finger:
                    shot = frame.copy()
                    h, w = shot.shape[:2]
                    cv2.rectangle(shot, (int(roi[0] * w), int(roi[1] * h)), (int(roi[2] * w), int(roi[3] * h)), (0, 255, 0), 2)
                    if engine == "mediapipe" and detector.rect is not None and detector.rect[2] - detector.rect[0] < w:
                        x0, y0, x1, y1 = detector.rect       # the zoomed window being searched or followed
                        cv2.rectangle(shot, (x0, y0), (x1, y1), (0, 255, 255) if detector.points is not None else (0, 140, 255), 2)
                    if engine == "mediapipe" and detector.points is not None:
                        pts = detector.points.astype(int)
                        for a, b in handmod.BONES:
                            cv2.line(shot, tuple(pts[a]), tuple(pts[b]), (0, 255, 0), 2)
                        for q in pts:
                            cv2.circle(shot, tuple(q), 4, (255, 255, 0), -1)
                        pressed = blob is not None and blob["pinch"] < 0.32
                        cv2.circle(shot, tuple(pts[handmod.INDEX_TIP]), 16, (0, 0, 255) if pressed else (255, 0, 255), 4)
                        if blob:
                            cv2.putText(shot, f"pinch {blob['pinch']:.2f}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 3)
                    elif blob:
                        cv2.circle(shot, (int(blob["x"]), int(blob["y"])), 14, (255, 0, 255), 3)
                    if getattr(detector, "mask", None) is not None:
                        mask = cv2.resize(detector.mask, (w, h))
                        shot[mask > 0] = (0.5 * shot[mask > 0] + 0.5 * np.array((0, 160, 255))).astype(np.uint8)
                    cv2.imshow("finger tracker (q to quit)", cv2.resize(shot, None, fx=0.6, fy=0.6) if w > 900 else shot)
                else:
                    shot = cv2.cvtColor(cv2.normalize(frame, None, 0, 255, cv2.NORM_MINMAX), cv2.COLOR_GRAY2BGR)
                    if blob:
                        cv2.circle(shot, (int(blob["x"]), int(blob["y"])), 12, (255, 0, 255), 2)
                    cv2.imshow("pen tracker (q to quit)", cv2.resize(shot, None, fx=2, fy=2))
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            if args.stats and now - t_begin >= args.stats:
                break
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
        if engine == "mediapipe" and detector is not None:
            detector.close()
        cv2.destroyAllWindows()

    if args.stats:
        secs = time.monotonic() - t_begin
        summary = {**counts, "seconds": round(secs, 1), "frames_per_second": round(counts["frames"] / secs, 1),
                   "calibrated": H is not None}
        if xs:
            summary["board_x_range"] = [round(min(xs)), round(max(xs))]
            summary["board_y_range"] = [round(min(ys)), round(max(ys))]
        print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
