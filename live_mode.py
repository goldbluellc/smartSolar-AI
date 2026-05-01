"""
live_mode.py — Live-camera mode for SmartSolar AI.

Features:
  - Adaptive calibration: samples 15 sky frames to auto-set sun / cloud thresholds
  - Interactive ROI: crop to sky-only region (R key)
  - Real-time threshold adjustment via keyboard
  - Camera-disconnect auto-fallback to first .mp4 in project folder

Keyboard shortcuts:
  Q / ESC       Quit
  C             Recalibrate thresholds
  R             Select sky ROI region
  =  / -        Sun brightness threshold  +5 / -5
  ]  / [        Cloud darkness threshold  +5 / -5
  F             Toggle fullscreen
  S             Save screenshot

Run directly:
    python live_mode.py
    python live_mode.py --camera 1 --serial /dev/ttyUSB0 --fullscreen --demo
"""

import argparse
import glob
import os
import sys
import time

import cv2
import numpy as np

import sun_detector as _sd
import cloud_detector as _cd
from config import FRAME_WIDTH, FRAME_HEIGHT, DEFAULT_BAUD_RATE, MIN_CLOUD_AREA
from cloud_tracker import CloudTracker
from shadow_analyzer import analyze_shadow_threat
from servo_mapper import map_to_servo_angles
from hud_overlay import draw_hud

# ── Calibration parameters ─────────────────────────────────────────────────────
_CALIB_FRAMES  = 15     # frames sampled during adaptive calibration
_SUN_HEADROOM  = 15     # sun_threshold = peak_brightness_p90 − headroom
_CLOUD_MARGIN  = 40     # cloud_threshold = mean_brightness − margin

# ── Pipeline parameters ────────────────────────────────────────────────────────
_PROC_SCALE    = 2
_ROI_PX        = 150    # half-width of ROI window in proc-space
_ROI_TTL       = 30     # frames to reuse ROI before a full scan
_SKIP          = 2      # run pipeline every N frames

_WIN           = "SmartSolar AI — Live"


# ─────────────────────────────────────────────────────────────────────────────
# Adaptive calibration
# ─────────────────────────────────────────────────────────────────────────────

def calibrate(cap: cv2.VideoCapture, roi=None) -> tuple:
    """
    Sample _CALIB_FRAMES live frames and return (sun_threshold, cloud_threshold).

        sun_threshold   = 90th-percentile peak brightness − _SUN_HEADROOM
        cloud_threshold = mean sky brightness − _CLOUD_MARGIN  (clamped 60–200)
    """
    print("[CAL] Sampling sky for adaptive calibration ", end="", flush=True)
    peaks, means = [], []

    for _ in range(_CALIB_FRAMES):
        ret, frame = cap.read()
        if not ret:
            continue
        frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))
        if roi:
            rx, ry, rw, rh = roi
            crop = frame[ry:ry + rh, rx:rx + rw]
            if crop.size > 0:
                frame = crop
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, max_val, _, _ = cv2.minMaxLoc(gray)
        peaks.append(int(max_val))
        means.append(float(np.mean(gray)))
        print(".", end="", flush=True)
        cv2.waitKey(50)

    print(" done.")

    peak        = int(np.percentile(peaks, 90)) if peaks else 240
    mean        = int(np.mean(means))           if means else 130
    sun_thresh  = max(180, min(250, peak - _SUN_HEADROOM))
    cloud_thresh= max(60,  min(200, mean - _CLOUD_MARGIN))

    print(f"[CAL] Sun threshold={sun_thresh}  Cloud threshold={cloud_thresh}")
    return sun_thresh, cloud_thresh


# ─────────────────────────────────────────────────────────────────────────────
# Main live loop
# ─────────────────────────────────────────────────────────────────────────────

def run(
    camera_idx: int = 0,
    serial_port: str = None,
    baud: int = DEFAULT_BAUD_RATE,
    fullscreen: bool = False,
    demo_watermark: bool = False,
) -> None:
    """Open camera, calibrate, and run the full pipeline. Returns on Q/ESC."""

    # ── Serial ─────────────────────────────────────────────────────────────
    ser           = None
    serial_status = ""
    if serial_port:
        from serial_sender import init_serial
        ser           = init_serial(serial_port, baud)
        serial_status = "OK" if ser else "OFFLINE"

    # ── Camera ─────────────────────────────────────────────────────────────
    cap = cv2.VideoCapture(camera_idx)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    if not cap.isOpened():
        print(f"[ERROR] Cannot open camera {camera_idx}.")
        return

    # ── Window ─────────────────────────────────────────────────────────────
    cv2.namedWindow(_WIN, cv2.WINDOW_NORMAL)
    if fullscreen:
        cv2.setWindowProperty(_WIN, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    is_fullscreen = fullscreen

    # ── Initial calibration ────────────────────────────────────────────────
    roi = None
    sun_thresh, cloud_thresh = calibrate(cap, roi)
    _sd.SUN_BRIGHTNESS_THRESHOLD = sun_thresh
    _cd.CLOUD_DARKNESS_THRESHOLD = cloud_thresh
    _cd.MIN_CLOUD_AREA           = MIN_CLOUD_AREA

    # ── Pipeline state ──────────────────────────────────────────────────────
    tracker       = CloudTracker()
    proc_w        = FRAME_WIDTH  // _PROC_SCALE
    proc_h        = FRAME_HEIGHT // _PROC_SCALE
    frame_count   = 0
    last_sun_proc = None
    roi_countdown = 0
    cached        = dict(sun_pos=None, threat="SAFE", direction="HOLD",
                         servo_x=None, servo_y=None, vectors=[], proc_fps=0.0)
    maint_alert   = ""
    maint_expiry  = 0.0
    prev_time     = time.time()
    screenshot_n  = 0
    cam_lost_exp  = 0.0     # banner expiry for camera-lost event
    is_live       = True    # False after falling back to video

    _print_shortcuts()

    while True:
        ret, raw = cap.read()

        # ── Camera-lost / video-end handling ────────────────────────────────
        if not ret:
            if not is_live:
                # Video file looping
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, raw = cap.read()
                if not ret:
                    break
            else:
                # Camera disconnected — try to fall back to a video file
                fallback = _find_video_fallback()
                if fallback:
                    print(f"[WARN] Camera lost — switching to {fallback}")
                    cap.release()
                    cap = cv2.VideoCapture(fallback)
                    is_live      = False
                    cam_lost_exp = time.time() + 5.0
                    continue
                else:
                    print("[INFO] Camera stream ended.")
                    break

        display = cv2.resize(raw, (FRAME_WIDTH, FRAME_HEIGHT))

        # Apply ROI crop for processing only (display stays full-frame)
        proc_src = display
        if roi and is_live:
            rx, ry, rw, rh = roi
            crop = display[ry:ry + rh, rx:rx + rw]
            if crop.size > 0:
                proc_src = cv2.resize(crop, (FRAME_WIDTH, FRAME_HEIGHT))

        now      = time.time()
        disp_fps = 1.0 / max(now - prev_time, 1e-9)
        prev_time = now

        # ── Pipeline every _SKIP frames ─────────────────────────────────────
        if frame_count % _SKIP == 0:
            proc_start = time.time()
            small      = cv2.resize(proc_src, (proc_w, proc_h))
            gray_small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            dummy      = small.copy()

            if last_sun_proc is not None and roi_countdown > 0:
                lx, ly = last_sun_proc
                x1 = max(0, lx - _ROI_PX);  y1 = max(0, ly - _ROI_PX)
                x2 = min(proc_w, lx + _ROI_PX); y2 = min(proc_h, ly + _ROI_PX)
                sp, _, _ = _sd.detect_sun(gray_small[y1:y2, x1:x2],
                                          dummy[y1:y2, x1:x2])
                sun_proc = (sp[0] + x1, sp[1] + y1) if sp else None
                roi_countdown -= 1
            else:
                sun_proc, _, _ = _sd.detect_sun(gray_small, dummy)
                roi_countdown  = _ROI_TTL

            if sun_proc:
                last_sun_proc = sun_proc

            sun_pos = (sun_proc[0] * _PROC_SCALE, sun_proc[1] * _PROC_SCALE) \
                      if sun_proc else None

            clouds_proc  = _cd.detect_clouds(gray_small, dummy)
            vectors_proc = tracker.update(clouds_proc)
            vectors      = _scale_vectors(vectors_proc, _PROC_SCALE)

            if sun_pos:
                threat, direction = analyze_shadow_threat(
                    sun_pos,
                    [{"center": v["cloud"]["center"], "area": v["cloud"]["area"],
                      "contour": None} for v in vectors],
                    vectors, display,
                )
                servo_x, servo_y = map_to_servo_angles(sun_pos)
            else:
                threat, direction = "SAFE", "HOLD"
                servo_x = servo_y = None

            proc_fps = 1.0 / max(time.time() - proc_start, 1e-9)
            cached.update(dict(sun_pos=sun_pos, threat=threat, direction=direction,
                               servo_x=servo_x, servo_y=servo_y, vectors=vectors,
                               proc_fps=proc_fps))

        sun_pos   = cached["sun_pos"]
        threat    = cached["threat"]
        direction = cached["direction"]
        servo_x   = cached["servo_x"]
        servo_y   = cached["servo_y"]
        vectors   = cached["vectors"]
        proc_fps  = cached["proc_fps"]

        # ── Serial commands ─────────────────────────────────────────────────
        if frame_count % _SKIP == 0 and servo_x is not None and ser is not None:
            try:
                from serial_sender import send_command
                send_command(ser, servo_x, servo_y, threat)
            except Exception as e:
                print(f"[WARN] Serial: {e}")
                ser = None
                serial_status = "OFFLINE"

        if ser is not None:
            try:
                while ser.in_waiting:
                    line = ser.readline().decode("ascii", errors="ignore").strip()
                    if not line:
                        continue
                    if "ALERT:" in line or "PREDICTION:" in line:
                        maint_alert  = line
                        maint_expiry = time.time() + 6.0
                    elif "SYSTEM RESET:" in line:
                        maint_alert  = ""
                        maint_expiry = 0.0
            except Exception:
                ser = None
                serial_status = "OFFLINE"

        if maint_alert and time.time() > maint_expiry:
            maint_alert = ""

        # ── HUD ─────────────────────────────────────────────────────────────
        output = draw_hud(display, sun_pos, servo_x, servo_y,
                          threat, direction, disp_fps, maint_alert,
                          vectors=vectors, proc_fps=proc_fps,
                          serial_status=serial_status)

        # LIVE badge
        if is_live:
            cv2.putText(output, "LIVE", (output.shape[1] - 58, 72),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 200), 2, cv2.LINE_AA)

        # Camera-lost recovery banner
        if time.time() < cam_lost_exp:
            _draw_camera_lost_banner(output)

        # ROI boundary
        if roi and is_live:
            rx, ry, rw, rh = roi
            cv2.rectangle(output, (rx, ry), (rx + rw, ry + rh), (0, 220, 180), 1)

        # Threshold info (bottom-right, above FPS)
        h_o = output.shape[0]
        cv2.putText(output,
                    f"SUN:{_sd.SUN_BRIGHTNESS_THRESHOLD}  "
                    f"CLD:{_cd.CLOUD_DARKNESS_THRESHOLD}",
                    (output.shape[1] - 210, h_o - 62),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (120, 120, 120), 1, cv2.LINE_AA)

        if demo_watermark:
            _draw_watermark(output)

        cv2.imshow(_WIN, output)

        # ── Keyboard ────────────────────────────────────────────────────────
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):       # Q / ESC
            break
        elif key == ord("c") and is_live:
            print("[KEY] Recalibrating …")
            sun_thresh, cloud_thresh = calibrate(cap, roi)
            _sd.SUN_BRIGHTNESS_THRESHOLD = sun_thresh
            _cd.CLOUD_DARKNESS_THRESHOLD = cloud_thresh
            tracker = CloudTracker()
        elif key == ord("r") and is_live:
            print("[KEY] Draw sky ROI — drag and press ENTER/SPACE")
            rr = cv2.selectROI(_WIN, display, showCrosshair=True, fromCenter=False)
            roi = rr if (rr[2] > 0 and rr[3] > 0) else None
            print(f"[KEY] ROI {'set: ' + str(roi) if roi else 'cleared'}")
        elif key == ord("="):           # = → sun +5
            _sd.SUN_BRIGHTNESS_THRESHOLD = min(254, _sd.SUN_BRIGHTNESS_THRESHOLD + 5)
            print(f"[KEY] Sun threshold → {_sd.SUN_BRIGHTNESS_THRESHOLD}")
        elif key == ord("-"):           # - → sun -5
            _sd.SUN_BRIGHTNESS_THRESHOLD = max(100, _sd.SUN_BRIGHTNESS_THRESHOLD - 5)
            print(f"[KEY] Sun threshold → {_sd.SUN_BRIGHTNESS_THRESHOLD}")
        elif key == ord("]"):           # ] → cloud +5
            _cd.CLOUD_DARKNESS_THRESHOLD = min(220, _cd.CLOUD_DARKNESS_THRESHOLD + 5)
            print(f"[KEY] Cloud threshold → {_cd.CLOUD_DARKNESS_THRESHOLD}")
        elif key == ord("["):           # [ → cloud -5
            _cd.CLOUD_DARKNESS_THRESHOLD = max(30, _cd.CLOUD_DARKNESS_THRESHOLD - 5)
            print(f"[KEY] Cloud threshold → {_cd.CLOUD_DARKNESS_THRESHOLD}")
        elif key == ord("f"):
            is_fullscreen = not is_fullscreen
            prop = cv2.WINDOW_FULLSCREEN if is_fullscreen else cv2.WINDOW_NORMAL
            cv2.setWindowProperty(_WIN, cv2.WND_PROP_FULLSCREEN, prop)
        elif key == ord("s"):
            screenshot_n += 1
            fname = f"screenshot_{screenshot_n:03d}.png"
            cv2.imwrite(fname, output)
            print(f"[KEY] Screenshot → {fname}")

        frame_count += 1

    # ── Cleanup ─────────────────────────────────────────────────────────────
    cap.release()
    if ser is not None:
        try:
            from serial_sender import close_serial
            close_serial(ser)
        except Exception:
            pass
    cv2.destroyAllWindows()
    print("[INFO] Live mode ended.")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _scale_vectors(vectors: list, scale: int) -> list:
    out = []
    for v in vectors:
        c = v["cloud"]
        cx, cy = c["center"]
        out.append({
            "cloud": {**c, "center": (cx * scale, cy * scale),
                      "area": c["area"] * scale * scale},
            "dx":    v["dx"]    * scale,
            "dy":    v["dy"]    * scale,
            "speed": v["speed"] * scale,
        })
    return out


def _find_video_fallback() -> str:
    """Return path to first .mp4/.avi in the project directory, or empty string."""
    for pattern in ("*.mp4", "*.avi", "*.mov"):
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[0]
    return ""


def _draw_watermark(frame: np.ndarray) -> None:
    h, w = frame.shape[:2]
    label = "SmartSolar AI  |  Hackathon Demo"
    (tw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    x, y = (w - tw) // 2, h - 38
    cv2.putText(frame, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(frame, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (200, 200, 200), 1, cv2.LINE_AA)


def _draw_camera_lost_banner(frame: np.ndarray) -> None:
    h, w = frame.shape[:2]
    label = "CAMERA LOST — SWITCHING TO RECORDED DEMO"
    cy    = h // 2
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, 0.8, 2)
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, cy - th - 16), (w, cy + 16), (0, 60, 200), -1)
    cv2.addWeighted(overlay, 0.80, frame, 0.20, 0, frame)
    cv2.putText(frame, label, ((w - tw) // 2, cy + 4),
                cv2.FONT_HERSHEY_DUPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)


def _print_shortcuts() -> None:
    print(
        "\n  Keyboard shortcuts:\n"
        "    Q / ESC   Quit\n"
        "    C         Recalibrate thresholds\n"
        "    R         Select sky ROI\n"
        "    = / -     Sun threshold  +5 / -5\n"
        "    ] / [     Cloud threshold +5 / -5\n"
        "    F         Toggle fullscreen\n"
        "    S         Save screenshot\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SmartSolar AI — live camera mode")
    p.add_argument("--camera",     type=int, default=0,
                   help="Camera index (default: 0)")
    p.add_argument("--serial",     default=None, metavar="PORT",
                   help="Serial port (e.g. COM3 or /dev/ttyUSB0)")
    p.add_argument("--baud",       type=int, default=DEFAULT_BAUD_RATE)
    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--demo",       action="store_true",
                   help="Add hackathon demo watermark")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(camera_idx    = args.camera,
        serial_port   = args.serial,
        baud          = args.baud,
        fullscreen    = args.fullscreen,
        demo_watermark= args.demo)
