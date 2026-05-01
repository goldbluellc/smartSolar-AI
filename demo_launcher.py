"""
demo_launcher.py — One-click SmartSolar AI demo launcher.

Run:
    python demo_launcher.py

Detects cameras, serial ports, and .mp4 files automatically.
Launches live_mode.py (camera) or main.py (video) with the right flags.
"""

import glob
import os
import subprocess
import sys


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _box(lines: list[str], width: int = 44) -> None:
    """Print a simple ASCII box around a list of strings."""
    border = "+" + "-" * (width - 2) + "+"
    print(border)
    for line in lines:
        pad = width - 4 - len(line)
        print(f"|  {line}{' ' * max(pad, 0)}  |")
    print(border)


def detect_cameras() -> list[int]:
    """Return indices (0-2) of cameras that successfully open."""
    import cv2
    found = []
    for i in range(3):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            found.append(i)
        cap.release()
    return found


def detect_serial() -> str:
    """Return first accessible serial port, or empty string."""
    candidates = (
        [f"COM{n}" for n in range(3, 11)]
        + [f"/dev/ttyUSB{n}" for n in range(4)]
        + [f"/dev/ttyACM{n}" for n in range(4)]
    )
    try:
        import serial
        for port in candidates:
            try:
                s = serial.Serial(port, timeout=0.2)
                s.close()
                return port
            except Exception:
                continue
    except ImportError:
        pass
    return ""


def find_videos() -> list[str]:
    """Return sorted list of video files in the current directory."""
    videos = []
    for pattern in ("*.mp4", "*.avi", "*.mov", "*.MP4"):
        videos.extend(glob.glob(pattern))
    return sorted(set(videos))


def _launch(script: str, extra_args: list[str]) -> None:
    cmd = [sys.executable, script] + extra_args
    print(f"\n[LAUNCH]  {' '.join(cmd)}\n")
    subprocess.run(cmd)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    _clear()

    print()
    _box([
        "SmartSolar AI  -  Live Demo",
        "Shadow Prediction System  v1.0",
        "",
        "[1]  LIVE MODE   -- Real camera feed",
        "[2]  VIDEO MODE  -- Pre-recorded demo",
    ])
    print()

    choice = input("Choose mode [1 / 2]: ").strip()

    # ── LIVE MODE ─────────────────────────────────────────────────────────────
    if choice == "1":
        print("\n[INFO] Detecting cameras …")
        cameras = detect_cameras()

        if not cameras:
            print("[ERROR] No cameras detected.")
            print("        Check USB connections and camera permissions, then retry.")
            sys.exit(1)

        cam_idx = cameras[0]
        if len(cameras) > 1:
            print(f"[INFO] Found cameras: {cameras}")
            pick = input(f"  Select camera index [{'/'.join(str(c) for c in cameras)}]: ").strip()
            if pick.isdigit() and int(pick) in cameras:
                cam_idx = int(pick)

        print(f"[INFO] Using camera index {cam_idx}.")

        ser          = detect_serial()
        mode_label   = "LIVE CAMERA"
        source_label = f"USB Webcam  (index {cam_idx})"

    # ── VIDEO MODE ────────────────────────────────────────────────────────────
    elif choice == "2":
        videos = find_videos()
        if not videos:
            print("[ERROR] No video files found in this directory.")
            print("        Copy a .mp4 timelapse here, or run:  demo_recorder.py")
            sys.exit(1)

        print("\nAvailable videos:")
        for i, v in enumerate(videos, 1):
            print(f"  [{i}]  {v}")
        pick = input(f"  Select video [1-{len(videos)}]: ").strip()
        try:
            video_file = videos[int(pick) - 1]
        except (ValueError, IndexError):
            video_file = videos[0]
            print(f"  (defaulting to {video_file})")

        ser          = detect_serial()
        mode_label   = "VIDEO"
        source_label = video_file

    else:
        print("[ERROR] Invalid choice — enter 1 or 2.")
        sys.exit(1)

    # ── Status table ──────────────────────────────────────────────────────────
    ser_line = f"{ser}  (Connected)" if ser else "Not found  --  SIMULATION mode"
    print()
    _box([
        f"Mode:    {mode_label}",
        f"Source:  {source_label}",
        f"Serial:  {ser_line}",
        "MQTT:    Not detected",
        "Status:  READY   Press Enter to start",
    ])

    input()   # wait for Enter

    # ── Launch ────────────────────────────────────────────────────────────────
    if choice == "1":
        args = ["--camera", str(cam_idx), "--demo"]
        if ser:
            args += ["--serial", ser]
        _launch("live_mode.py", args)

    else:
        args = ["--video", video_file, "--demo"]
        if ser:
            args += ["--serial", ser]
        _launch("main.py", args)


if __name__ == "__main__":
    main()
