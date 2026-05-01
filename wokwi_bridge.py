"""
wokwi_bridge.py — Connects SmartSolar AI to a Wokwi cloud Arduino simulation.

Uploads diagram.json + arduino_receiver/sketch.ino to Wokwi, starts the
simulation, then runs the full AI pipeline. Servo commands are sent to the
virtual Arduino via its serial port. Arduino responses (ALERT, PREDICTION,
SYSTEM RESET, Moved Pan/Tilt) are printed and shown as HUD banners.

Prerequisites:
    pip install wokwi-client
    export WOKWI_CLI_TOKEN=your_token_here   # https://wokwi.com/dashboard/ci

Run:
    python wokwi_bridge.py --video test_sky.mp4
    python wokwi_bridge.py --video 0              # webcam
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

import cv2

try:
    from wokwi_client import WokwiClient
except ImportError:
    print("[ERROR] wokwi-client not installed.")
    print("        Run: pip install wokwi-client")
    sys.exit(1)

# ── SmartSolar AI modules — all logic lives there, nothing recreated here ──
from config import FRAME_WIDTH, FRAME_HEIGHT
from sun_detector import detect_sun
from cloud_detector import detect_clouds
from cloud_tracker import CloudTracker
from shadow_analyzer import analyze_shadow_threat
from servo_mapper import map_to_servo_angles
from hud_overlay import draw_hud

# ── File paths (relative to project root, where this script lives) ─────────
_ROOT         = Path(__file__).parent
_DIAGRAM_FILE = _ROOT / "diagram.json"                      # project root
_SKETCH_FILE  = _ROOT / "arduino_receiver" / "sketch.ino"  # arduino_receiver/

# How long (s) to keep an ALERT/PREDICTION banner visible on the HUD
_BANNER_TTL = 6.0


# ─────────────────────────────────────────────────────────────────────────────
# Serial callback factory
# ─────────────────────────────────────────────────────────────────────────────

def _make_serial_callback(state: dict):
    """
    Returns a callback suitable for client.serial_monitor().
    Updates the shared state dict so the video loop can show banners.

    Recognised Arduino messages:
        "ALERT: ..."          → amber HUD banner for _BANNER_TTL seconds
        "PREDICTION: ..."     → amber HUD banner for _BANNER_TTL seconds
        "SYSTEM RESET: ..."   → clears HUD banner immediately
        "Moved Pan to: ..."   → printed to console only
        "Moved Tilt to: ..."  → printed to console only
    """
    def callback(line: bytes) -> None:
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            return
        print(f"  [Arduino] {text}")
        if "ALERT:" in text or "PREDICTION:" in text:
            state["banner"] = text
            state["expiry"] = time.monotonic() + _BANNER_TTL
        elif "SYSTEM RESET:" in text:
            state["banner"] = ""
            state["expiry"] = 0.0
    return callback


# ─────────────────────────────────────────────────────────────────────────────
# Video + pipeline loop
# ─────────────────────────────────────────────────────────────────────────────

async def _video_loop(client: WokwiClient, args: argparse.Namespace, state: dict) -> None:
    """
    Main pipeline loop. Mirrors main.py but sends commands to the Wokwi
    virtual Arduino instead of a physical serial port.
    """
    is_file = not args.video.isdigit()
    src     = int(args.video) if args.video.isdigit() else args.video
    cap     = cv2.VideoCapture(src)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    if not cap.isOpened():
        print(f"[ERROR] Cannot open video source: {args.video}")
        return

    tracker     = CloudTracker()
    prev_threat: str | None = None
    prev_time   = time.time()

    print("[INFO] Pipeline running. Press Q to quit.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                if is_file:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    await asyncio.sleep(0)
                    continue
                break

            frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            now       = time.time()
            fps       = 1.0 / max(now - prev_time, 1e-9)
            prev_time = now

            # ── AI pipeline ───────────────────────────────────────────────
            sun_pos, _, _ = detect_sun(gray, frame)
            clouds        = detect_clouds(gray, frame)
            vectors       = tracker.update(clouds)

            if sun_pos:
                threat, direction = analyze_shadow_threat(sun_pos, clouds, vectors, frame)
                servo_x, servo_y  = map_to_servo_angles(sun_pos)
            else:
                threat, direction = "SAFE", "HOLD"
                servo_x = servo_y = None

            # ── Send to Wokwi virtual Arduino serial ──────────────────────
            if servo_x is not None:
                await client.serial_write(f"P{servo_x}\n".encode("ascii"))
                await client.serial_write(f"T{servo_y}\n".encode("ascii"))

                # E1/E0 on threat state edge only
                if threat != prev_threat:
                    if threat == "DANGER":
                        await client.serial_write(b"E1\n")
                    elif threat == "SAFE":
                        await client.serial_write(b"E0\n")
                prev_threat = threat

            # ── Expire old banner ─────────────────────────────────────────
            if state["banner"] and time.monotonic() > state["expiry"]:
                state["banner"] = ""

            # ── HUD + display ─────────────────────────────────────────────
            output = draw_hud(
                frame, sun_pos, servo_x, servo_y,
                threat, direction, fps,
                state["banner"],
            )
            cv2.imshow("SmartSolar AI + Wokwi", output)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

            # Yield to event loop so serial_monitor callback can fire
            await asyncio.sleep(0)

    finally:
        cap.release()
        cv2.destroyAllWindows()


# ─────────────────────────────────────────────────────────────────────────────
# Wokwi setup
# ─────────────────────────────────────────────────────────────────────────────

def _check_files() -> None:
    for path in (_DIAGRAM_FILE, _SKETCH_FILE):
        if not path.exists():
            print(f"[ERROR] Required file not found: {path}")
            sys.exit(1)


async def _setup_wokwi(token: str) -> WokwiClient:
    """Connect to Wokwi, upload both files, and start the simulation."""
    print("[wokwi] Connecting …")
    client = WokwiClient(token)
    await client.connect()
    print("[wokwi] Connected.")

    print("[wokwi] Uploading diagram.json …")
    await client.upload_file("diagram.json")

    print("[wokwi] Uploading sketch.ino …")
    await client.upload_file("sketch.ino")

    print("[wokwi] Starting simulation …")
    await client.start_simulation(firmware="sketch.ino")

    print("[wokwi] Waiting for Arduino boot (2 s) …")
    await asyncio.sleep(2.0)
    print("[wokwi] Simulation ready.")
    return client


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SmartSolar AI — Wokwi cloud bridge")
    p.add_argument(
        "--video", default="test_sky.mp4",
        help="Video file path, or '0' for webcam (default: test_sky.mp4)",
    )
    return p.parse_args()


async def _run(args: argparse.Namespace) -> None:
    token = os.environ.get("WOKWI_CLI_TOKEN")
    if not token:
        print("[ERROR] WOKWI_CLI_TOKEN environment variable is not set.")
        print("        Get your token at: https://wokwi.com/dashboard/ci")
        sys.exit(1)

    _check_files()
    client = await _setup_wokwi(token)

    # Shared state between serial callback and video loop
    state: dict = {"banner": "", "expiry": 0.0}

    # Register serial monitor — creates its own background Task internally
    client.serial_monitor(_make_serial_callback(state))

    try:
        await _video_loop(client, args, state)
    finally:
        await client.disconnect()
        print("[INFO] Shutdown complete.")


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
