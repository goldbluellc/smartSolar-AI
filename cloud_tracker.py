"""
cloud_tracker.py — Tracks clouds across frames and computes motion vectors.
"""

import numpy as np


class CloudTracker:
    """
    Simple nearest-neighbour centroid tracker for cloud blobs.

    Each frame, call update() with the list of cloud dicts returned by
    cloud_detector.detect_clouds(). Returns a list of motion-vector dicts.
    """

    MAX_MATCH_DISTANCE = 150  # px — beyond this, treat as a new cloud

    def __init__(self):
        self._prev_clouds: list[dict] = []

    def update(self, current_clouds: list[dict]) -> list[dict]:
        """
        Match current detections to previous-frame clouds and compute dx/dy.

        Args:
            current_clouds: List from detect_clouds() —
                            [{"center": (cx,cy), "area": int, "contour": array}]

        Returns:
            List of dicts:
            [{"cloud": dict, "dx": int, "dy": int, "speed": float}]
        """
        vectors: list[dict] = []

        for cloud in current_clouds:
            cx, cy = cloud["center"]
            best_match = None
            best_dist = self.MAX_MATCH_DISTANCE

            for prev in self._prev_clouds:
                px, py = prev["center"]
                dist = float(np.hypot(cx - px, cy - py))
                if dist < best_dist:
                    best_dist = dist
                    best_match = prev

            if best_match is not None:
                dx = cx - best_match["center"][0]
                dy = cy - best_match["center"][1]
                speed = float(np.hypot(dx, dy))
            else:
                dx, dy, speed = 0, 0, 0.0

            vectors.append({
                "cloud": cloud,
                "dx": int(dx),
                "dy": int(dy),
                "speed": speed,
            })

        self._prev_clouds = current_clouds
        return vectors
