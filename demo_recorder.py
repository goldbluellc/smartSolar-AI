"""
demo_recorder.py — Records the full SmartSolar AI pipeline to a demo video.

Runs the complete vision + HUD pipeline on a video file (or webcam) and writes
the annotated output to demo_output.avi (XVID codec).  On the first frame that
shows each threat level it also saves a PNG screenshot.

Usage:
    python demo_recorder.py --video test_sky.mp4
    python demo_recorder.py --video 0          # webcam
    python demo_recorder.py --video sky.mp4 --out recording.avi --fps 25

Outputs:
    demo_output.avi    — full annotated video (or --out path)
    demo_safe.png      — first SAFE frame
    demo_warning.png   — first WARNING frame
    demo_danger.png    — first DANGER frame
"""

import argparse
import sys
import time

import cv2
import numpy as np

from config import FRAME_WIDTH, FRAME_HEIGHT
from sun_detector import detect_sun
from cloud_detector import detect_clouds
from cloud_tracker import CloudTracker
from shadow_analyzer import analyze_shadow_threat
from servo_mapper import map_to_servo_angles
from hud_overlay import draw_hud

# ── Constants ──────────────────────────────────────────────────────────────────
_PROC_SCALE  = 2       # run detection at half resolution
_SCREENSHOTS = {
    "SAFE":    "demo_safe.png",
    "WARNING": "demo_warning.png",
    "DANGER":  "demo_danger.png",
}


# ─────────────────────────────────────────────────────────────────────────────
# Arg parsing
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="SmartSolar AI — demo recorder"
    )
    p.add_argument("--video", default="test_sky.mp4",
                   help="Video source: file path or '0' for webcam (default: test_sky.mp4)")
    p.add_argument("--out",   default="demo_output.avi",
                   help="Output video file (default: demo_output.avi)")
    p.add_argument("--fps",   type=float, default=20.0,
                   help="Output video FPS (default: 20)")
    return p.parse_args()


# ─────────────────────────────────────────────────────────────────────────────
# Vector scaling (same as main.py)
# ─────────────────────────────────────────────────────────────────────────────

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

def main() -> None:
    args = _parse_args()

    src = int(args.video) if args.video.isdigit() else args.video
    cap = cv2.VideoCapture(src)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    if not cap.isOpened():
        print(f"[ERROR] Cannot open video source: {args.video}")
        sys.exit(1)

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    is_file      = not args.video.isdigit()

    # Output writer
    fourcc = cv2.VideoWriter_fourcc(*"XVID")
    writer = cv2.VideoWriter(args.out, fourcc, args.fps,
                              (FRAME_WIDTH, FRAME_HEIGHT))
    if not writer.isOpened():
        print(f"[ERROR] Cannot create output writer: {args.out}")
        print("        Ensure OpenCV was built with XVID / ffmpeg support.")
        sys.exit(1)

    tracker = CloudTracker()
    proc_w  = FRAME_WIDTH  // _PROC_SCALE
    proc_h  = FRAME_HEIGHT // _PROC_SCALE

    saved: dict[str, bool] = {k: False for k in _SCREENSHOTS}
    frame_idx = 0
    prev_time = time.time()

    print(f"[INFO] Recording → {args.out}   (source: {args.video})")
    print("[INFO] Press Ctrl-C to stop early.\n")

    try:
        while True:
            ret, raw = cap.read()
            if not ret:
                break   # end of file; demo recorder does NOT loop

            display    = cv2.resize(raw, (FRAME_WIDTH, FRAME_HEIGHT))
            small      = cv2.resize(display, (proc_w, proc_h))
            gray_small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            dummy      = small.copy()

            # ── AI pipeline ───────────────────────────────────────────────
            sun_proc, _, _ = detect_sun(gray_small, dummy)
            sun_pos = (sun_proc[0] * _PROC_SCALE, sun_proc[1] * _PROC_SCALE) \
                      if sun_proc else None

            clouds_proc  = detect_clouds(gray_small, dummy)
            vectors_proc = tracker.update(clouds_proc)
            vectors      = _scale_vectors(vectors_proc, _PROC_SCALE)

            if sun_pos:
                threat, direction = analyze_shadow_threat(
                    sun_pos,
                    [{"center": v["cloud"]["center"],
                      "area":   v["cloud"]["area"],
                      "contour": None}
                     for v in vectors],
                    vectors, display,
                )
                servo_x, servo_y = map_to_servo_angles(sun_pos)
            else:
                threat, direction = "SAFE", "HOLD"
                servo_x = servo_y = None

            # ── FPS ────────────────────────────────────────────────────────
            now       = time.time()
            fps_val   = 1.0 / max(now - prev_time, 1e-9)
            prev_time = now

            # ── HUD ────────────────────────────────────────────────────────
            output = draw_hud(
                display, sun_pos, servo_x, servo_y,
                threat, direction, fps_val, "",
                vectors=vectors,
            )

            writer.write(output)

            # ── Screenshots ────────────────────────────────────────────────
            if not saved.get(threat, True):
                fname = _SCREENSHOTS[threat]
                cv2.imwrite(fname, output)
                saved[threat] = True
                print(f"[SCREENSHOT] {fname}  (threat={threat}, frame={frame_idx})")

            # ── Progress ───────────────────────────────────────────────────
            frame_idx += 1
            if is_file and total_frames > 0 and frame_idx % 15 == 0:
                pct = min(100, int(100 * frame_idx / total_frames))
                bar_fill = "#" * (pct // 5)
                bar_empty = "." * (20 - len(bar_fill))
                print(f"\r[{bar_fill}{bar_empty}] {pct:3d}%  "
                      f"frame {frame_idx}/{total_frames}  "
                      f"fps={fps_val:.1f}    ",
                      end="", flush=True)

    except KeyboardInterrupt:
        print("\n\n[INFO] Stopped early by user.")

    cap.release()
    writer.release()

    print(f"\n\n[INFO] Saved {frame_idx} frames → {args.out}")

    for threat_name, fname in _SCREENSHOTS.items():
        status = "saved" if saved.get(threat_name) else "not seen"
        print(f"  {threat_name:8s} screenshot: {fname}  [{status}]")


if __name__ == "__main__":
    main()
