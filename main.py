"""
main.py — SmartSolar AI entry point.

Speed optimisations (Phase 4):
  - Frame skipping: full pipeline every --skip frames; display every frame
  - Half-resolution detection: detect at 320×240, display at 640×480
  - Performance ROI: after finding the sun, only scan a 300 px window for
    the next 30 frames before doing a full scan again
  - Dual FPS readout: processing FPS vs display FPS

Video files loop automatically. Press Q to quit.
"""

import argparse
import glob
import os
import sys
import time

import cv2

from config import FRAME_WIDTH, FRAME_HEIGHT, DEFAULT_BAUD_RATE
from sun_detector import detect_sun
from cloud_detector import detect_clouds
from cloud_tracker import CloudTracker
from shadow_analyzer import analyze_shadow_threat
from servo_mapper import map_to_servo_angles, get_smoothed_servo_command, reset_servo_state
from serial_sender import reset_threat_state
from hud_overlay import draw_hud

# ── Speed-optimisation constants ──────────────────────────────────────────────
_PROC_SCALE  = 2      # process at 1/_PROC_SCALE resolution
_ROI_PX      = 150    # half-width of ROI window in proc-space (= 300 px full-res)
_ROI_TTL     = 30     # frames to reuse ROI before a full scan


# ─────────────────────────────────────────────────────────────────────────────
# Argument parsing
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="SmartSolar AI — cloud-aware solar panel tracker"
    )
    p.add_argument("--video",  default="0",
                   help="Video file path, or '0' for webcam (default: 0)")
    p.add_argument("--serial", default=None, metavar="PORT",
                   help="Serial port (e.g. COM3 or /dev/ttyUSB0)")
    p.add_argument("--mqtt",   default=None, metavar="BROKER_IP",
                   help="MQTT broker IP for WiFi mode")
    p.add_argument("--baud",   type=int, default=DEFAULT_BAUD_RATE,
                   help=f"Serial baud rate (default: {DEFAULT_BAUD_RATE})")
    p.add_argument("--skip",       type=int, default=2,
                   help="Run pipeline every N frames; display every frame (default: 2)")
    p.add_argument("--fullscreen", action="store_true",
                   help="Open display window fullscreen")
    p.add_argument("--demo",       action="store_true",
                   help="Add 'SmartSolar AI | Hackathon Demo' watermark")
    return p.parse_args()


# ─────────────────────────────────────────────────────────────────────────────
# Video-source helpers
# ─────────────────────────────────────────────────────────────────────────────

def _open_cap(source: str) -> cv2.VideoCapture:
    """Open VideoCapture and return it. Caller checks .isOpened()."""
    src = int(source) if source.isdigit() else source
    cap = cv2.VideoCapture(src)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    return cap


def _fail_video(source: str) -> None:
    """Print a helpful error message and exit."""
    if source.isdigit():
        print(f"[ERROR] Cannot open camera index {source}.")
        print("        Suggestions:")
        print("          • Try --video 0  or  --video 1")
        print("          • On macOS: System Settings → Privacy → Camera → allow Terminal")
        print("          • Unplug and replug the USB camera")
    else:
        if not os.path.exists(source):
            print(f"[ERROR] Video file not found: '{source}'")
            print("        Download a sky/cloud timelapse and pass its path with --video")
        else:
            print(f"[ERROR] Cannot decode video: '{source}'")
            print("        Ensure the file is a valid MP4 / AVI / MOV.")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Coordinate-scaling helpers
# ─────────────────────────────────────────────────────────────────────────────

_WIN = "SmartSolar AI"


def _find_video_fallback() -> str:
    """Return first .mp4/.avi in current directory, or empty string."""
    for pattern in ("*.mp4", "*.avi", "*.mov"):
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[0]
    return ""


def _draw_watermark(frame) -> None:
    h, w = frame.shape[:2]
    label = "SmartSolar AI  |  Hackathon Demo"
    (tw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    x, y = (w - tw) // 2, h - 38
    cv2.putText(frame, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(frame, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (200, 200, 200), 1, cv2.LINE_AA)


def _draw_camera_lost_banner(frame) -> None:
    h, w = frame.shape[:2]
    label = "CAMERA LOST — SWITCHING TO RECORDED DEMO"
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, 0.8, 2)
    cy      = h // 2
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, cy - th - 16), (w, cy + 16), (0, 60, 200), -1)
    cv2.addWeighted(overlay, 0.80, frame, 0.20, 0, frame)
    cv2.putText(frame, label, ((w - tw) // 2, cy + 4),
                cv2.FONT_HERSHEY_DUPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)


def _scale_vectors(vectors: list, scale: int) -> list:
    """Scale cloud centroids and motion vectors from proc-space to display-space."""
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


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    args = _parse_args()

    # ── Reset servo state for clean start ──────────────────────────────
    reset_servo_state()

    # ── Output channels ───────────────────────────────────────────────────
    ser          = None
    mqtt_client  = None
    serial_status = ""   # "", "OK", "OFFLINE"

    if args.serial:
        from serial_sender import init_serial
        ser = init_serial(args.serial, args.baud)
        if ser is None:
            print(f"[WARN] Serial unavailable on {args.serial} — continuing without it.")
            serial_status = "OFFLINE"
        else:
            serial_status = "OK"

    if args.mqtt:
        try:
            from mqtt_sender import init_mqtt
            mqtt_client = init_mqtt(args.mqtt)
            if mqtt_client is None:
                print(f"[WARN] MQTT broker unreachable ({args.mqtt}) — continuing without MQTT.")
        except Exception as e:
            print(f"[WARN] MQTT init error: {e} — continuing without MQTT.")

    # ── Video source ──────────────────────────────────────────────────────
    cap = _open_cap(args.video)
    if not cap.isOpened():
        _fail_video(args.video)

    is_file  = not args.video.isdigit()
    tracker  = CloudTracker()

    # ── Proc-resolution ───────────────────────────────────────────────────
    proc_w = FRAME_WIDTH  // _PROC_SCALE
    proc_h = FRAME_HEIGHT // _PROC_SCALE

    # ── Window ────────────────────────────────────────────────────────────
    cv2.namedWindow(_WIN, cv2.WINDOW_NORMAL)
    if args.fullscreen:
        cv2.setWindowProperty(_WIN, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    is_fullscreen = args.fullscreen

    # ── State ─────────────────────────────────────────────────────────────
    frame_count       = 0
    last_sun_proc: tuple[int, int] | None = None
    roi_countdown     = 0
    cam_lost_expiry   = 0.0    # banner expiry after camera-lost fallback
    screenshot_n      = 0
    serial_reconnect_time = 0.0  # Track when to attempt serial reconnection

    # Cached pipeline results (reused on skipped frames)
    cached: dict = dict(
        sun_pos=None, threat="SAFE", direction="HOLD",
        servo_x=None, servo_y=None, vectors=[], proc_fps=0.0,
    )

    # Threat hysteresis — hold elevated threat for N processed frames
    _THREAT_RANK   = {"SAFE": 0, "WARNING": 1, "DANGER": 2}
    _HOLD_FRAMES   = {"DANGER": 45, "WARNING": 30, "SAFE": 75}  # 3 s / 2 s / 5 s
    held_threat    = "SAFE"
    held_direction = "HOLD"
    threat_hold_counter = 0

    # Maintenance / alert banner
    maint_alert  = ""
    maint_expiry = 0.0

    # FPS
    disp_prev = time.time()

    print(f"[INFO] SmartSolar AI running | skip={args.skip} | "
          f"proc={proc_w}×{proc_h} display={FRAME_WIDTH}×{FRAME_HEIGHT}")
    print("[INFO] Press 'q' to quit.")

    while True:
        ret, raw = cap.read()

        # ── Loop / end handling ───────────────────────────────────────────
        if not ret:
            if is_file:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, raw = cap.read()
                if not ret:
                    print("[ERROR] Cannot loop video — exiting.")
                    break
            else:
                fallback = _find_video_fallback()
                if fallback:
                    print(f"[WARN] Camera lost — switching to {fallback}")
                    cap.release()
                    cap = _open_cap(fallback)
                    is_file         = True
                    cam_lost_expiry = time.time() + 5.0
                    continue
                print("[INFO] Camera stream ended.")
                break

        display = cv2.resize(raw, (FRAME_WIDTH, FRAME_HEIGHT))

        # Display FPS (every frame)
        now      = time.time()
        disp_fps = 1.0 / max(now - disp_prev, 1e-9)
        disp_prev = now

        # ── Full pipeline (every --skip frames) ───────────────────────────
        if frame_count % args.skip == 0:
            proc_start = time.time()

            small      = cv2.resize(display, (proc_w, proc_h))
            gray_small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            dummy_col  = small.copy()   # detectors draw here; we don't display it

            # Sun detection with ROI optimisation
            if last_sun_proc is not None and roi_countdown > 0:
                lx, ly = last_sun_proc
                x1 = max(0, lx - _ROI_PX)
                y1 = max(0, ly - _ROI_PX)
                x2 = min(proc_w, lx + _ROI_PX)
                y2 = min(proc_h, ly + _ROI_PX)
                sp, _, _ = detect_sun(gray_small[y1:y2, x1:x2],
                                      dummy_col[y1:y2, x1:x2])
                sun_proc = (sp[0] + x1, sp[1] + y1) if sp else None
                roi_countdown -= 1
            else:
                sun_proc, _, _ = detect_sun(gray_small, dummy_col)
                roi_countdown = _ROI_TTL

            if sun_proc:
                last_sun_proc = sun_proc

            sun_pos = (sun_proc[0] * _PROC_SCALE, sun_proc[1] * _PROC_SCALE) \
                      if sun_proc else None

            # Cloud detection & tracking (proc-space)
            clouds_proc  = detect_clouds(gray_small, dummy_col)
            vectors_proc = tracker.update(clouds_proc)

            # Scale to display-space for HUD & analysis
            vectors = _scale_vectors(vectors_proc, _PROC_SCALE)

            # Threat analysis — draw on display frame at full-res coords
            if sun_pos:
                threat, direction = analyze_shadow_threat(
                    sun_pos, [{"center": v["cloud"]["center"],
                               "area":   v["cloud"]["area"],
                               "contour": None}
                              for v in vectors],
                    vectors, display,
                )
                servo_x, servo_y = map_to_servo_angles(sun_pos)
            else:
                threat, direction = "SAFE", "HOLD"
                servo_x = servo_y = None

            # Hysteresis: upgrade immediately, downgrade only after hold expires
            if _THREAT_RANK[threat] > _THREAT_RANK[held_threat]:
                # Immediate upgrade (SAFE→WARNING, SAFE→DANGER, WARNING→DANGER)
                held_threat    = threat
                held_direction = direction
                threat_hold_counter = _HOLD_FRAMES[threat]
            elif _THREAT_RANK[threat] == _THREAT_RANK[held_threat]:
                # Same level: keep refreshing the hold so timer starts fresh on drop
                threat_hold_counter = _HOLD_FRAMES[threat]
            else:
                # Downgrade: count down from full hold before dropping
                threat_hold_counter -= 1
                if threat_hold_counter <= 0:
                    held_threat    = threat
                    held_direction = direction
                    threat_hold_counter = _HOLD_FRAMES[threat]
            threat    = held_threat
            direction = held_direction

            proc_fps = 1.0 / max(time.time() - proc_start, 1e-9)

            cached.update(dict(
                sun_pos=sun_pos, threat=threat, direction=direction,
                servo_x=servo_x, servo_y=servo_y, vectors=vectors,
                proc_fps=proc_fps,
            ))

        # Use cached values on skipped frames
        sun_pos   = cached["sun_pos"]
        threat    = cached["threat"]
        direction = cached["direction"]
        servo_x   = cached["servo_x"]
        servo_y   = cached["servo_y"]
        vectors   = cached["vectors"]
        proc_fps  = cached["proc_fps"]

        # ── Send commands (processing frames only) ────────────────────────
        # Attempt serial reconnection if offline (every 3 seconds)
        if args.serial and serial_status == "OFFLINE" and time.time() > serial_reconnect_time:
            serial_reconnect_time = time.time() + 3.0
            print("[INFO] Attempting serial reconnection…")
            from serial_sender import init_serial
            ser = init_serial(args.serial, args.baud)
            if ser is not None:
                serial_status = "OK"
                print("[INFO] Reconnected to serial port.")
                reset_servo_state()           # Reset smoothing on reconnect
                reset_threat_state()          # Clear prev threat tracking
                held_threat    = "SAFE"       # LED starts off — Arduino just rebooted
                held_direction = "HOLD"
                threat_hold_counter = 0
            else:
                serial_status = "OFFLINE"
        
        if frame_count % args.skip == 0 and servo_x is not None:
            # Apply rate limiting & smoothing before sending
            smoothed = get_smoothed_servo_command(servo_x, servo_y)
            
            if smoothed is not None:  # Only send if rate limit allows
                smooth_x, smooth_y = smoothed
                
                if ser is not None:
                    from serial_sender import send_command
                    send_command(ser, smooth_x, smooth_y, threat)  # never raises

                if mqtt_client is not None:
                    try:
                        from mqtt_sender import send_command_mqtt
                        send_command_mqtt(mqtt_client, smooth_x, smooth_y, threat)
                    except Exception as e:
                        print(f"[WARN] MQTT error: {e} — running without MQTT.")
                        mqtt_client = None

        # ── Read back from Arduino ─────────────────────────────────────────
        if ser is not None:
            try:
                waiting = ser.in_waiting
            except OSError as e:
                if e.errno == 2:  # port physically removed
                    ser = None
                    serial_status = "OFFLINE"
                waiting = 0
            except Exception:
                waiting = 0  # transient — skip this frame's reads
            for _ in range(min(waiting, 6)):
                try:
                    line = ser.readline().decode("ascii", errors="ignore").strip()
                except Exception:
                    break       # transient — skip this frame's reads
                if not line:
                    continue
                if "ALERT:" in line or "PREDICTION:" in line:
                    maint_alert  = line
                    maint_expiry = time.time() + 6.0
                    print(f"[ARDUINO] {line}")
                elif "SYSTEM RESET:" in line:
                    maint_alert  = ""
                    maint_expiry = 0.0
                    print(f"[ARDUINO] {line}")

        if maint_alert and time.time() > maint_expiry:
            maint_alert = ""

        # ── HUD + display ─────────────────────────────────────────────────
        output = draw_hud(
            display, sun_pos, servo_x, servo_y,
            threat, direction, disp_fps, maint_alert,
            vectors=vectors, proc_fps=proc_fps,
            serial_status=serial_status,
        )

        if time.time() < cam_lost_expiry:
            _draw_camera_lost_banner(output)

        if args.demo:
            _draw_watermark(output)

        cv2.imshow(_WIN, output)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
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

    # ── Cleanup ───────────────────────────────────────────────────────────
    cap.release()

    if ser is not None:
        try:
            from serial_sender import close_serial
            close_serial(ser)
        except Exception:
            pass

    if mqtt_client is not None:
        try:
            from mqtt_sender import close_mqtt
            close_mqtt(mqtt_client)
        except Exception:
            pass

    cv2.destroyAllWindows()
    print("[INFO] Shutdown complete.")


if __name__ == "__main__":
    main()
