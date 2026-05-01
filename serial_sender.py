"""
serial_sender.py — Sends servo commands to an Arduino/ESP32 via USB serial.

Wire protocol (matches hardware teammate's Arduino firmware):
    "P{angle}\\n"   — set pan  servo (horizontal X), e.g. "P90\\n"
    "T{angle}\\n"   — set tilt servo (vertical   Y), e.g. "T45\\n"
    "E1\\n"         — enable  error LED (sent once when threat → DANGER)
    "E0\\n"         — disable error LED (sent once when threat → SAFE)

E1/E0 are sent only on threat-level STATE CHANGE, not every frame.
"""

import time
from config import DEFAULT_BAUD_RATE

try:
    import serial as _serial
    _SERIAL_AVAILABLE = True
except ImportError:
    _serial = None
    _SERIAL_AVAILABLE = False

# Module-level state: track previous threat so E1/E0 fire on edge only
_prev_threat: str | None = None

# Consecutive write-error counter — after 5 failures treat port as dead
_write_error_count: int = 0


def init_serial(port: str, baud: int = DEFAULT_BAUD_RATE):
    """
    Open a serial connection to the Arduino/ESP32.

    Args:
        port: Serial port name (e.g. "COM3", "/dev/ttyUSB0") or an RFC2217
              URL for virtual/network serial ports, e.g.
              "rfc2217://localhost:4000" (Wokwi VS Code extension).
        baud: Baud rate to match the Arduino firmware (default 9600).

    Returns:
        An open serial.Serial object, or None on failure.
    """
    global _write_error_count
    _write_error_count = 0  # fresh start for every new connection
    if not _SERIAL_AVAILABLE:
        print("[serial] pyserial not installed — serial output disabled.")
        return None
    try:
        if port.startswith("rfc2217://"):
            ser = _serial.serial_for_url(port, baudrate=baud,
                                         timeout=0.05)
        else:
            ser = _serial.Serial(port, baud, timeout=0.05, write_timeout=2.0)
        print(f"[serial] Connected to {port} at {baud} baud — waiting for Arduino reset …")
        time.sleep(5)
        print("[serial] Ready.")
        return ser
    except Exception as e:
        print(f"[serial] Failed to open {port}: {e}")
        return None


def send_command(ser, servo_x: int, servo_y: int, threat_level: str) -> bool:
    """
    Send servo angle and (edge-triggered) LED commands to the Arduino.

    Always sends:
        "P{servo_x}\\n"   — pan  angle
        "T{servo_y}\\n"   — tilt angle

    On threat STATE CHANGE only:
        → DANGER : sends "E1\\n" (error LED on)
        → SAFE   : sends "E0\\n" (error LED off)
        WARNING does not change the LED state.

    Args:
        ser:          Open serial.Serial (or None — silently skipped).
        servo_x:      Pan  servo angle 0-180.
        servo_y:      Tilt servo angle 0-180.
        threat_level: "SAFE" | "WARNING" | "DANGER".

    Returns:
        True if all writes succeeded, False otherwise.
    """
    global _prev_threat, _write_error_count
    if ser is None:
        return False
    try:
        ser.write(f"P{servo_x}\n".encode("ascii"))
        ser.write(f"T{servo_y}\n".encode("ascii"))

        # Edge-only E1/E0
        if threat_level != _prev_threat:
            if threat_level == "DANGER":
                ser.write(b"E1\n")
            elif threat_level == "SAFE":
                ser.write(b"E0\n")
            _prev_threat = threat_level

        _write_error_count = 0  # reset on success
        return True
    except Exception as e:
        _write_error_count += 1
        if _write_error_count == 1:
            print(f"[serial] Write error: {e}")
        elif _write_error_count % 20 == 0:
            print(f"[serial] Write errors ({_write_error_count}) — still retrying…")
        return False  # never raise — connection stays alive


def reset_threat_state() -> None:
    """Reset the module-level threat tracker (call between test runs)."""
    global _prev_threat
    _prev_threat = None


def close_serial(ser) -> None:
    """Close the serial port if it is open."""
    if ser is not None:
        try:
            ser.close()
            print("[serial] Port closed.")
        except Exception:
            pass


# ── Class-based API (retained for backward compatibility) ──────────────────

class SerialSender:
    def __init__(self, port: str, baud: int = DEFAULT_BAUD_RATE):
        self.port = port
        self.baud = baud
        self._ser = None
        self._prev_threat: str | None = None

    def connect(self) -> bool:
        self._ser = init_serial(self.port, self.baud)
        return self._ser is not None

    def send_angles(self, angle_x: int, angle_y: int, threat: str = "SAFE") -> bool:
        if self._ser is None:
            return False
        try:
            self._ser.write(f"P{angle_x}\n".encode("ascii"))
            self._ser.write(f"T{angle_y}\n".encode("ascii"))
            if threat != self._prev_threat:
                if threat == "DANGER":
                    self._ser.write(b"E1\n")
                elif threat == "SAFE":
                    self._ser.write(b"E0\n")
                self._prev_threat = threat
            return True
        except _serial.SerialTimeoutException:
            return False
        except Exception as e:
            print(f"[serial] Write error: {e}")
            return False

    def disconnect(self) -> None:
        close_serial(self._ser)
        self._ser = None
