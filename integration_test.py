"""
integration_test.py — End-to-end pipeline test without real hardware.

Runs the full SmartSolar AI pipeline on a video file, simulates the serial
command stream, and logs every individual command to a CSV.

Wire protocol simulated:
    "P<pan>\\n"   — pan  servo angle
    "T<tilt>\\n"  — tilt servo angle
    "E1\\n"       — error LED on  (sent once on DANGER edge)
    "E0\\n"       — error LED off (sent once on SAFE   edge)

CSV output (one row per command, not per frame):
    timestamp, command, servo_x, servo_y, threat

Usage:
    python integration_test.py
    python integration_test.py --video my_sky.mp4
    python integration_test.py --video test_sky.mp4 --max-frames 500

Output:
    integration_test_log.csv  — one row per serial command
    Console                   — live command stream + summary
"""

import argparse
import csv
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from config import FRAME_WIDTH, FRAME_HEIGHT
from sun_detector import detect_sun
from cloud_detector import detect_clouds
from cloud_tracker import CloudTracker
from shadow_analyzer import analyze_shadow_threat
from servo_mapper import map_to_servo_angles

LOG_PATH   = Path("integration_test_log.csv")
LOG_FIELDS = ["timestamp", "command", "servo_x", "servo_y", "threat"]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SmartSolar AI integration test")
    p.add_argument("--video", default="test_sky.mp4",
                   help="Video file to process (default: test_sky.mp4)")
    p.add_argument("--max-frames", type=int, default=0,
                   help="Stop after N frames (0 = entire video)")
    p.add_argument("--show", action="store_true",
                   help="Show annotated frames in a window (optional)")
    return p.parse_args()


def _open_video(path: str) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        print(f"[ERROR] Cannot open video: {path}")
        sys.exit(1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    return cap


def main():
    args  = _parse_args()
    cap   = _open_video(args.video)
    tracker = CloudTracker()

    threat_counts: dict[str, int] = {"SAFE": 0, "WARNING": 0, "DANGER": 0}
    frame_idx   = 0
    cmd_count   = 0
    fps_samples: list[float] = []
    t_start     = time.time()
    prev_threat: str | None = None

    print(f"[INFO] Running pipeline on : {args.video}")
    print(f"[INFO] Logging commands to : {LOG_PATH}")
    print(f"[INFO] Max frames          : {'unlimited' if not args.max_frames else args.max_frames}")
    print()

    with LOG_PATH.open("w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=LOG_FIELDS)
        writer.writeheader()

        prev_t = time.time()

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if args.max_frames and frame_idx >= args.max_frames:
                break

            frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            now   = time.time()
            fps   = 1.0 / max(now - prev_t, 1e-9)
            prev_t = now
            fps_samples.append(fps)
            ts = f"{now - t_start:.3f}"

            # ── Pipeline ──────────────────────────────────────────────────
            sun_pos, _, _ = detect_sun(gray, frame)
            clouds        = detect_clouds(gray, frame)
            vectors       = tracker.update(clouds)

            if sun_pos:
                threat, _direction = analyze_shadow_threat(sun_pos, clouds, vectors, frame)
                servo_x, servo_y   = map_to_servo_angles(sun_pos)
            else:
                threat   = "SAFE"
                servo_x  = servo_y = None

            threat_counts[threat] = threat_counts.get(threat, 0) + 1

            # ── Build & log individual commands ───────────────────────────
            def log_cmd(cmd: str) -> None:
                nonlocal cmd_count
                cmd_count += 1
                print(f"  [SIMULATED] {cmd:<12}  threat={threat}  frame={frame_idx}")
                writer.writerow({
                    "timestamp": ts,
                    "command":   cmd,
                    "servo_x":   servo_x if servo_x is not None else "",
                    "servo_y":   servo_y if servo_y is not None else "",
                    "threat":    threat,
                })

            if servo_x is not None:
                log_cmd(f"P{servo_x}")
                log_cmd(f"T{servo_y}")

            # E1/E0 only on threat state change
            if threat != prev_threat:
                if threat == "DANGER":
                    log_cmd("E1")
                elif threat == "SAFE":
                    log_cmd("E0")
            prev_threat = threat

            # ── Optional display ──────────────────────────────────────────
            if args.show:
                label = f"F{frame_idx} {threat}"
                cv2.putText(frame, label, (8, 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                cv2.imshow("Integration Test", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            frame_idx += 1

    cap.release()
    if args.show:
        cv2.destroyAllWindows()

    # ── Summary ───────────────────────────────────────────────────────────
    total_time  = time.time() - t_start
    avg_fps     = float(np.mean(fps_samples)) if fps_samples else 0.0
    total_frames = sum(threat_counts.values())
    safe_pct    = 100 * threat_counts["SAFE"]    / max(total_frames, 1)
    warn_pct    = 100 * threat_counts["WARNING"] / max(total_frames, 1)
    danger_pct  = 100 * threat_counts["DANGER"]  / max(total_frames, 1)

    print()
    print("=" * 54)
    print("  SmartSolar AI — Integration Test Summary")
    print("=" * 54)
    print(f"  Video           : {args.video}")
    print(f"  Total frames    : {frame_idx}")
    print(f"  Commands logged : {cmd_count}")
    print(f"  Total time      : {total_time:.1f}s")
    print(f"  Average FPS     : {avg_fps:.1f}")
    print()
    print(f"  Threat SAFE     : {threat_counts['SAFE']:5d}  ({safe_pct:.1f}%)")
    print(f"  Threat WARNING  : {threat_counts['WARNING']:5d}  ({warn_pct:.1f}%)")
    print(f"  Threat DANGER   : {threat_counts['DANGER']:5d}  ({danger_pct:.1f}%)")
    print()
    print(f"  Log saved to    : {LOG_PATH.resolve()}")
    print("=" * 54)


if __name__ == "__main__":
    main()
