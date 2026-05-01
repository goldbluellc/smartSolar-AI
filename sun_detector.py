"""
sun_detector.py — Detects the brightest region (the sun) in a video frame.
"""

import cv2
import numpy as np
from config import SUN_BRIGHTNESS_THRESHOLD


def detect_sun(
    gray: np.ndarray,
    color: np.ndarray,
) -> tuple[tuple[int, int] | None, int, int]:
    """
    Detect the sun's position in a frame.

    Args:
        gray:  Grayscale image (H x W).
        color: BGR image to annotate in-place.

    Returns:
        (sun_center_xy, sun_radius, max_brightness)
        sun_center_xy is None if detection failed entirely.
    """
    blurred = cv2.GaussianBlur(gray, (31, 31), 0)

    _, max_val, _, max_loc = cv2.minMaxLoc(blurred)

    _, mask = cv2.threshold(blurred, SUN_BRIGHTNESS_THRESHOLD, 255, cv2.THRESH_BINARY)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    sun_center: tuple[int, int] | None = None
    sun_radius = 20

    if contours:
        largest = max(contours, key=cv2.contourArea)
        (cx, cy), radius = cv2.minEnclosingCircle(largest)
        sun_center = (int(cx), int(cy))
        sun_radius = max(int(radius), 10)
    else:
        # Fallback: trust the single brightest pixel
        sun_center = max_loc
        sun_radius = 20

    _draw_sun_annotation(color, sun_center, sun_radius)
    return sun_center, sun_radius, int(max_val)


def _draw_sun_annotation(
    frame: np.ndarray,
    center: tuple[int, int],
    radius: int,
) -> None:
    """Draw yellow circle, crosshair, and SUN label on frame (in-place)."""
    YELLOW = (0, 255, 255)
    cx, cy = center
    r = radius

    cv2.circle(frame, center, r, YELLOW, 2)
    cv2.circle(frame, center, 3, YELLOW, -1)

    # Crosshair lines (gap in the middle)
    cv2.line(frame, (cx - r - 8, cy), (cx - 6, cy), YELLOW, 1)
    cv2.line(frame, (cx + 6, cy), (cx + r + 8, cy), YELLOW, 1)
    cv2.line(frame, (cx, cy - r - 8), (cx, cy - 6), YELLOW, 1)
    cv2.line(frame, (cx, cy + 6), (cx, cy + r + 8), YELLOW, 1)

    cv2.putText(
        frame, "SUN",
        (cx + r + 6, cy - 4),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, YELLOW, 1, cv2.LINE_AA,
    )
