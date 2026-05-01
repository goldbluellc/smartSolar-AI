"""
cloud_detector.py — Detects dark cloud regions in a video frame.
"""

import cv2
import numpy as np
from config import CLOUD_DARKNESS_THRESHOLD, MIN_CLOUD_AREA


def detect_clouds(gray: np.ndarray, color: np.ndarray) -> list[dict]:
    """
    Detect cloud blobs in a frame.

    Args:
        gray:  Grayscale image (H x W).
        color: BGR image to annotate in-place.

    Returns:
        List of dicts: [{"center": (cx, cy), "area": int, "contour": np.ndarray}]
    """
    blurred = cv2.GaussianBlur(gray, (15, 15), 0)

    # Dark regions = clouds (inverse threshold)
    _, mask = cv2.threshold(
        blurred, CLOUD_DARKNESS_THRESHOLD, 255, cv2.THRESH_BINARY_INV
    )

    # Close small holes, then open to remove speckle
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    clouds = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < MIN_CLOUD_AREA:
            continue

        M = cv2.moments(contour)
        if M["m00"] == 0:
            continue
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])

        clouds.append({"center": (cx, cy), "area": int(area), "contour": contour})

        x, y, w, h = cv2.boundingRect(contour)
        cv2.rectangle(color, (x, y), (x + w, y + h), (180, 180, 180), 1)
        cv2.putText(
            color, "CLOUD",
            (x, max(y - 4, 12)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 180, 180), 1, cv2.LINE_AA,
        )

    return clouds
