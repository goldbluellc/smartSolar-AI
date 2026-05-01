"""
wokwi_test.py — Serial test sender for the Wokwi (or physical) Arduino.

Sends a fixed test sequence to verify serial communication before running the
full AI pipeline. Reads and prints all Arduino responses.

Test sequence:
    Pan  sweep: P0  P45  P90  P135  P180
    Tilt sweep: T0  T45  T90  T135  T180
    Error test: E1  (wait 2 s)  E0

Expected Arduino responses (your teammate's firmware):
    "Moved Pan to: <angle>"
    "Moved Tilt to: <angle>"
    "ALERT: Overcurrent detected! (850mA)."
    "PREDICTION: High friction in Pan Gear. Failure likely in 14 days."
    "SYSTEM RESET: Motors healthy."

Usage:
    python wokwi_test.py --dry-run              # no hardware needed
    python wokwi_test.py --port COM3
    python wokwi_test.py --port /dev/ttyUSB0 --baud 9600
"""

import argparse
import sys
import time


# ─────────────────────────────────────────────────────────────────────────────
# Fixed test sequence
# ─────────────────────────────────────────────────────────────────────────────

PAN_SWEEP  = ["P0", "P45", "P90", "P135", "P180"]
TILT_SWEEP = ["T0", "T45", "T90", "T135", "T180"]
ERROR_TEST = [("E1", 2.0), ("E0", 0.5)]   # (command, pause_after_seconds)

STEP_DELAY = 0.5   # seconds between normal commands


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _read_responses(ser, wait_s: float = 0.1) -> list[str]:
    """Wait briefly then drain all available lines from the serial buffer."""
    time.sleep(wait_s)
    lines = []
    while ser.in_waiting:
        try:
            line = ser.readline().decode("ascii", errors="ignore").strip()
            if line:
                lines.append(line)
        except Exception:
            break
    return lines


def _send(ser, cmd: str, dry_run: bool, pause: float = STEP_DELAY) -> None:
    """Send one command and print the Arduino's response."""
    if dry_run:
        print(f"  [DRY-RUN] → {cmd}")
    else:
        ser.write((cmd + "\n").encode("ascii"))
        responses = _read_responses(ser, wait_s=min(pause, 0.3))
        if responses:
            for r in responses:
                print(f"  SENT: {cmd:<10}  Arduino: {r}")
        else:
            print(f"  SENT: {cmd:<10}  (no response)")
    time.sleep(pause)


# ─────────────────────────────────────────────────────────────────────────────
# Test runner
# ─────────────────────────────────────────────────────────────────────────────

def run_test(ser, dry_run: bool) -> None:

    # ── 1. Pan sweep ──────────────────────────────────────────────────────
    print("\n── Pan servo sweep ──────────────────────────────────")
    for cmd in PAN_SWEEP:
        _send(ser, cmd, dry_run)
    print("  Pan sweep complete.")

    # ── 2. Tilt sweep ─────────────────────────────────────────────────────
    print("\n── Tilt servo sweep ─────────────────────────────────")
    for cmd in TILT_SWEEP:
        _send(ser, cmd, dry_run)
    print("  Tilt sweep complete.")

    # ── 3. Error / reset test ─────────────────────────────────────────────
    print("\n── Error state test ─────────────────────────────────")
    for cmd, pause in ERROR_TEST:
        if cmd == "E1":
            print("  Sending E1 — expecting ALERT/PREDICTION messages …")
        elif cmd == "E0":
            print("  Sending E0 — expecting SYSTEM RESET message …")
        _send(ser, cmd, dry_run, pause=pause)

    print("\n  \u2713 All sequences complete.")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SmartSolar AI — Wokwi test sender")
    p.add_argument("--port",    default=None,
                   help="Serial port (e.g. COM3 or /dev/ttyUSB0)")
    p.add_argument("--baud",    type=int, default=9600,
                   help="Baud rate (default 9600)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print commands without opening a serial port")
    return p.parse_args()


def main():
    args = _parse_args()

    if args.dry_run or args.port is None:
        print("SmartSolar AI — Wokwi Test Sender  [DRY-RUN MODE]")
        print("(Pass --port COM3 to send to real/Wokwi hardware)\n")
        run_test(None, dry_run=True)
        return

    try:
        import serial
    except ImportError:
        print("[ERROR] pyserial not installed. Run: pip install pyserial")
        sys.exit(1)

    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
        print(f"SmartSolar AI — Wokwi Test Sender  [PORT: {args.port} @ {args.baud}]")
        print("Waiting for Arduino boot …")
        time.sleep(2.0)
        # Print startup messages
        for line in _read_responses(ser, wait_s=0):
            print(f"  Arduino: {line}")
    except serial.SerialException as e:
        print(f"[ERROR] Cannot open {args.port}: {e}")
        sys.exit(1)

    try:
        run_test(ser, dry_run=False)
    finally:
        ser.close()
        print("\n[INFO] Serial port closed.")


if __name__ == "__main__":
    main()
