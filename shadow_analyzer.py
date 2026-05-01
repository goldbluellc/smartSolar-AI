"""
shadow_analyzer.py — Predicts whether a tracked cloud will block the sun.
"""

import math
import cv2
import numpy as np
from config import SHADOW_DANGER_ZONE_PX

# Threat levels (ordered by severity)
THREAT_SAFE    = "SAFE"
THREAT_WARNING = "WARNING"
THREAT_DANGER  = "DANGER"

# Keep legacy aliases so hud_overlay colour map still works
THREAT_NONE     = THREAT_SAFE
THREAT_LOW      = THREAT_WARNING
THREAT_HIGH     = THREAT_DANGER
THREAT_CRITICAL = THREAT_DANGER

_SEVERITY = {THREAT_SAFE: 0, THREAT_WARNING: 1, THREAT_DANGER: 2}

# Lookahead in frames used for trajectory prediction
_LOOKAHEAD = 10


def analyze_shadow_threat(
    sun_center: tuple[int, int],
    clouds: list[dict],
    vectors: list[dict],
    color: np.ndarray,
) -> tuple[str, str]:
    """
    Analyse shadow threat from all tracked cloud vectors.

    Args:
        sun_center: (x, y) pixel coords of the sun.
        clouds:     Cloud dicts from detect_clouds() (unused directly; kept for
                    API symmetry — the cloud data lives inside vectors).
        vectors:    Motion-vector dicts from CloudTracker.update().
        color:      BGR frame to annotate in-place.

    Returns:
        (threat_level, direction_hint)
        threat_level:   "SAFE" | "WARNING" | "DANGER"
        direction_hint: "HOLD" | "ROTATE_LEFT" | "ROTATE_RIGHT" |
                        "PREPARE_LEFT" | "PREPARE_RIGHT"
    """
    worst_threat = THREAT_SAFE
    worst_direction = "HOLD"

    sx, sy = sun_center

    for vec in vectors:
        cloud  = vec["cloud"]
        dx, dy = vec["dx"], vec["dy"]
        cx, cy = cloud["center"]

        dist_now = _dist((cx, cy), (sx, sy))

        # Predicted position N frames ahead
        fx = cx + dx * _LOOKAHEAD
        fy = cy + dy * _LOOKAHEAD
        dist_future = _dist((fx, fy), (sx, sy))
        approaching = dist_future < dist_now

        # --- Draw motion vector arrow (orange) ---
        if dx != 0 or dy != 0:
            scale = 5
            ex = int(cx + dx * scale)
            ey = int(cy + dy * scale)
            cv2.arrowedLine(color, (cx, cy), (ex, ey), (0, 165, 255), 2,
                            tipLength=0.4, line_type=cv2.LINE_AA)

        # --- Classify threat ---
        if dist_now < SHADOW_DANGER_ZONE_PX:
            level = THREAT_DANGER
            direction = "ROTATE_RIGHT" if cx < sx else "ROTATE_LEFT"
            cv2.line(color, (cx, cy), (sx, sy), (0, 0, 255), 2, cv2.LINE_AA)
            cv2.putText(color, "DANGER", (cx, cy - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)

        elif approaching and dist_future < SHADOW_DANGER_ZONE_PX * 2:
            level = THREAT_WARNING
            direction = "PREPARE_RIGHT" if cx < sx else "PREPARE_LEFT"
            cv2.line(color, (cx, cy), (sx, sy), (0, 165, 255), 1, cv2.LINE_AA)
            cv2.putText(color, "WARNING", (cx, cy - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 165, 255), 1, cv2.LINE_AA)

        else:
            level = THREAT_SAFE
            direction = "HOLD"

        # Keep the worst
        if _SEVERITY[level] > _SEVERITY[worst_threat]:
            worst_threat = level
            worst_direction = direction

    return worst_threat, worst_direction


def _dist(p1: tuple[int, int], p2: tuple[int, int]) -> float:
    """Euclidean pixel distance between two points."""
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])
