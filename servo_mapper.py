"""
servo_mapper.py — Maps sun pixel coordinates to servo X/Y angles with smoothing.
"""

import time
import numpy as np
from config import FRAME_WIDTH, FRAME_HEIGHT, SERVO_X_RANGE, SERVO_Y_RANGE


# ── Rate limiting & smoothing state ───────────────────────────────────────
_last_send_time: float = 0.0
_last_servo_x: int | None = None
_last_servo_y: int | None = None
_command_count: int = 0

# Configuration
SERVO_RATE_MS = 400      # Only send commands every 400ms (limits to ~2.5 cmd/sec)
SERVO_MAX_STEP = 2       # Max degrees per command to prevent sudden jerks


def map_to_servo_angles(
    sun_pos: tuple[int, int],
    frame_w: int = FRAME_WIDTH,
    frame_h: int = FRAME_HEIGHT,
) -> tuple[int, int]:
    """
    Convert sun pixel position to servo angle commands.

    X maps left→right to SERVO_X_RANGE (0-180).
    Y is inverted: top (y=0) → 180°, bottom (y=frame_h) → 0°, so the
    panel tilts upward when the sun is high in the frame.

    Args:
        sun_pos: (x, y) pixel coordinates of the sun.
        frame_w: Frame width in pixels.
        frame_h: Frame height in pixels.

    Returns:
        (servo_x, servo_y) as ints clamped to [0, 180].
    """
    x, y = sun_pos
    servo_x = int(np.interp(x, [0, frame_w], [SERVO_X_RANGE[0], SERVO_X_RANGE[1]]))
    # Y axis is inverted for natural panel tilt behaviour
    servo_y = int(np.interp(y, [0, frame_h], [SERVO_Y_RANGE[1], SERVO_Y_RANGE[0]]))
    servo_x = int(np.clip(servo_x, SERVO_X_RANGE[0], SERVO_X_RANGE[1]))
    servo_y = int(np.clip(servo_y, SERVO_Y_RANGE[0], SERVO_Y_RANGE[1]))
    return servo_x, servo_y


def get_smoothed_servo_command(
    target_x: int, target_y: int
) -> tuple[int, int] | None:
    """
    Apply smoothing and rate limiting to servo commands.
    
    - Only returns a command every SERVO_RATE_MS milliseconds
    - Limits angle changes to SERVO_MAX_STEP per command
    
    Args:
        target_x: Target pan servo angle (0-180).
        target_y: Target tilt servo angle (0-180).
    
    Returns:
        (smoothed_x, smoothed_y) if rate limit elapsed, else None.
    """
    global _last_send_time, _last_servo_x, _last_servo_y
    
    now = time.time() * 1000.0  # Convert to milliseconds
    
    # Rate limiting: only send if enough time has elapsed
    if now - _last_send_time < SERVO_RATE_MS:
        return None
    
    _last_send_time = now
    
    # Initialize on first call
    if _last_servo_x is None:
        _last_servo_x = target_x
        _last_servo_y = target_y
        return target_x, target_y
    
    # Smooth: cap the change per command
    dx = target_x - _last_servo_x
    dy = target_y - _last_servo_y
    
    smooth_x = _last_servo_x + max(-SERVO_MAX_STEP, min(SERVO_MAX_STEP, dx))
    smooth_y = _last_servo_y + max(-SERVO_MAX_STEP, min(SERVO_MAX_STEP, dy))
    
    _last_servo_x = smooth_x
    _last_servo_y = smooth_y
    
    return smooth_x, smooth_y


def reset_servo_state() -> None:
    """Reset smoothing state (call between test runs)."""
    global _last_send_time, _last_servo_x, _last_servo_y
    _last_send_time = 0.0
    _last_servo_x = None
    _last_servo_y = None


# Legacy alias kept for any code that uses the old name
def pixel_to_servo_angles(
    sun_pos: tuple[int, int],
    dead_band_px: int = 5,
) -> tuple[int, int] | None:
    if sun_pos is None:
        return None
    return map_to_servo_angles(sun_pos)
