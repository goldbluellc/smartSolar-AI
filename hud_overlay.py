"""
hud_overlay.py — Phase 4 enhanced HUD overlay for SmartSolar AI.

Phase 4 additions:
  - Frame border (6 px, threat-coloured; pulses on DANGER)
  - Full-width threat banner using FONT_HERSHEY_DUPLEX
  - Cloud trajectory dotted lines (10-frame lookahead from vectors)
  - Shadow risk % progress bar below info panel
  - Legend bottom-left
  - Serial-status badge in info panel
  - Dual FPS readout (display FPS + pipeline processing FPS)
"""

import time

import cv2
import numpy as np

from config import SHADOW_DANGER_ZONE_PX

# ── Colour palette (BGR) ──────────────────────────────────────────────────────
_THREAT_COLOR = {
    "SAFE":     (0, 200, 0),
    "WARNING":  (0, 165, 255),
    "DANGER":   (0, 0, 255),
    # Legacy aliases kept for backward compat
    "NONE":     (0, 200, 0),
    "LOW":      (0, 255, 255),
    "HIGH":     (0, 165, 255),
    "CRITICAL": (0, 0, 255),
}

_PANEL_W      = 300     # info panel width (px)
_BANNER_H     = 50      # full-width top banner height (px)
_BORDER_PX    = 6       # frame border thickness
_PULSE_PERIOD = 0.4     # DANGER border pulse period (seconds)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def draw_hud(
    frame: np.ndarray,
    sun_pos: "tuple[int, int] | None",
    servo_x: "int | None",
    servo_y: "int | None",
    threat: str,
    direction: str,
    fps: float,
    maintenance_alert: str = "",
    *,
    vectors: "list | None" = None,
    proc_fps: float = 0.0,
    serial_status: str = "",
) -> np.ndarray:
    """
    Render the full Phase-4 HUD onto a copy of the frame and return it.

    Args:
        frame:             Original BGR frame (not modified in place).
        sun_pos:           (x, y) pixel of detected sun, or None.
        servo_x:           Commanded pan angle, or None.
        servo_y:           Commanded tilt angle, or None.
        threat:            "SAFE", "WARNING", or "DANGER".
        direction:         Direction hint, e.g. "HOLD", "ROTATE_LEFT".
        fps:               Display (render) FPS.
        maintenance_alert: Non-empty string → amber banner at bottom.
        vectors:           Cloud motion vectors from CloudTracker.update().
        proc_fps:          Pipeline processing FPS (half-res, skipped frames).
        serial_status:     "OK", "OFFLINE", or "" — badge in info panel.
    """
    out = frame.copy()
    if vectors is None:
        vectors = []

    color = _THREAT_COLOR.get(threat, (180, 180, 180))

    # Draw order: back → front
    _draw_border(out, color, threat)
    if vectors:
        _draw_trajectories(out, vectors, sun_pos)
    if sun_pos is not None:
        _draw_zone_circles(out, sun_pos)
    _draw_threat_banner_full(out, threat, color)
    _draw_info_panel(out, sun_pos, servo_x, servo_y,
                     threat, direction, fps, proc_fps, serial_status, vectors)
    if sun_pos is not None and vectors:
        _draw_risk_bar(out, sun_pos, vectors)
    _draw_fps(out, fps, proc_fps)
    _draw_legend(out)
    if maintenance_alert:
        _draw_maintenance_banner(out, maintenance_alert)

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────────────

def _draw_border(frame: np.ndarray, color: tuple, threat: str) -> None:
    """6-pixel coloured frame border; pulses on DANGER."""
    h, w = frame.shape[:2]
    if threat == "DANGER":
        phase = (time.monotonic() % _PULSE_PERIOD) / _PULSE_PERIOD
        c = color if phase < 0.5 else tuple(int(x * 0.35) for x in color)
    else:
        c = color
    cv2.rectangle(frame, (0, 0), (w - 1, h - 1), c, _BORDER_PX)


def _draw_trajectories(
    frame: np.ndarray,
    vectors: list,
    sun_pos: "tuple[int, int] | None",
) -> None:
    """Dotted trajectory line + endpoint dot for each moving cloud (10-frame look-ahead)."""
    for v in vectors:
        cx, cy = v["cloud"]["center"]
        dx, dy = v["dx"], v["dy"]
        if v["speed"] < 0.5:        # skip near-static clouds
            continue

        tx = int(cx + dx * 10)
        ty = int(cy + dy * 10)

        if sun_pos:
            to_sx = sun_pos[0] - cx
            to_sy = sun_pos[1] - cy
            dot   = dx * to_sx + dy * to_sy
            c = (0, 100, 255) if dot > 0 else (100, 100, 100)   # orange toward sun
        else:
            c = (100, 100, 100)

        _dotted_line(frame, (cx, cy), (tx, ty), c)
        cv2.circle(frame, (tx, ty), 3, c, -1)


def _draw_zone_circles(frame: np.ndarray, sun_pos: tuple) -> None:
    """Dashed danger (red) and warning (orange) rings around the sun."""
    _dashed_circle(frame, sun_pos, SHADOW_DANGER_ZONE_PX,
                   (0, 0, 220), thickness=1)
    _dashed_circle(frame, sun_pos, int(SHADOW_DANGER_ZONE_PX * 2),
                   (0, 130, 255), thickness=1, dash_deg=8, gap_deg=6)


def _draw_threat_banner_full(
    frame: np.ndarray,
    threat: str,
    color: tuple,
) -> None:
    """Full-width threat banner at the very top of the frame."""
    h, w = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, _BANNER_H), color, -1)
    cv2.addWeighted(overlay, 0.82, frame, 0.18, 0, frame)
    cv2.line(frame, (0, _BANNER_H), (w, _BANNER_H), (200, 200, 200), 1)

    font      = cv2.FONT_HERSHEY_DUPLEX
    scale     = 1.0
    thickness = 2
    label     = f"THREAT: {threat}"
    (tw, th), _ = cv2.getTextSize(label, font, scale, thickness)
    tx = (w - tw) // 2
    ty = (_BANNER_H + th) // 2
    cv2.putText(frame, label, (tx, ty), font, scale,
                (255, 255, 255), thickness, cv2.LINE_AA)


def _draw_info_panel(
    frame: np.ndarray,
    sun_pos,
    servo_x,
    servo_y,
    threat: str,
    direction: str,
    fps: float,
    proc_fps: float,
    serial_status: str,
    vectors: list,
) -> None:
    """Semi-transparent info panel below the threat banner (top-left)."""
    y_off = _BANNER_H + 4
    W, H  = _PANEL_W, 200

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, y_off), (W, y_off + H), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)

    color = _THREAT_COLOR.get(threat, (200, 200, 200))
    GREEN = (0, 220, 0)
    WHITE = (220, 220, 220)
    GREY  = (160, 160, 160)

    cv2.putText(frame, "SmartSolar AI", (10, y_off + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.58, GREEN, 1, cv2.LINE_AA)

    def _row(label: str, value: str, row: int, val_color=WHITE) -> None:
        y = y_off + 38 + row * 24
        cv2.putText(frame, label, (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.43, GREY, 1, cv2.LINE_AA)
        cv2.putText(frame, value, (118, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.43, val_color, 1, cv2.LINE_AA)

    sun_str = f"({sun_pos[0]},{sun_pos[1]})" if sun_pos else "N/A"
    svo_str = f"{servo_x}/{servo_y}"         if servo_x is not None else "N/A"
    fps_str = f"D:{fps:.0f} P:{proc_fps:.0f}" if proc_fps > 0 else f"{fps:.1f}"
    cld_str = str(len(vectors))

    _row("Sun pos:",  sun_str,  0)
    _row("Servo:",    svo_str,  1)
    _row("Threat:",   threat,   2, color)
    _row("Action:",   direction, 3, color)
    _row("FPS:",      fps_str,  4)
    _row("Clouds:",   cld_str,  5)

    # Serial status badge (top-right of panel)
    if serial_status:
        badge_c = (0, 170, 0) if serial_status == "OK" else (30, 30, 200)
        bx = _PANEL_W - 88
        by = y_off + 6
        cv2.rectangle(frame, (bx - 2, by - 11), (bx + 85, by + 3), badge_c, -1)
        cv2.putText(frame, f"SER:{serial_status}", (bx, by),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.36, (255, 255, 255), 1, cv2.LINE_AA)


def _draw_risk_bar(
    frame: np.ndarray,
    sun_pos: tuple,
    vectors: list,
) -> None:
    """Horizontal shadow-risk progress bar just below the info panel."""
    sx, sy   = sun_pos
    min_dist = min(
        np.hypot(v["cloud"]["center"][0] - sx, v["cloud"]["center"][1] - sy)
        for v in vectors
    )
    zone = SHADOW_DANGER_ZONE_PX
    if min_dist >= zone * 3:
        risk = 0
    elif min_dist <= zone:
        risk = 100
    else:
        risk = int(100 * (1.0 - (min_dist - zone) / (zone * 2)))

    bx = 10
    by = _BANNER_H + 4 + 200 + 8   # below info panel
    bw = _PANEL_W - 20
    bh = 14

    cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (30, 30, 30), -1)
    fill_w = int(bw * risk / 100)
    if fill_w > 0:
        bar_c = (0, 180, 0) if risk < 50 else (0, 140, 255) if risk < 80 else (0, 0, 220)
        cv2.rectangle(frame, (bx, by), (bx + fill_w, by + bh), bar_c, -1)
    cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (100, 100, 100), 1)

    cv2.putText(frame, f"SHADOW RISK  {risk}%",
                (bx + 4, by + bh - 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (220, 220, 220), 1, cv2.LINE_AA)


def _draw_fps(frame: np.ndarray, disp_fps: float, proc_fps: float) -> None:
    """Dual FPS counter, positioned above any maintenance alert banner."""
    h, w = frame.shape[:2]
    label = (f"DISP:{disp_fps:.0f}  PROC:{proc_fps:.0f}"
             if proc_fps > 0 else f"FPS:{disp_fps:.1f}")
    cv2.putText(frame, label, (w - 175, h - 44),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, (140, 140, 140), 1, cv2.LINE_AA)


def _draw_legend(frame: np.ndarray) -> None:
    """Colour-coded legend at bottom-left, above maintenance alert area."""
    h, w = frame.shape[:2]
    items = [
        ((0,   0, 220), "Danger zone"),
        ((0, 130, 255), "Warning zone"),
        ((0, 100, 255), "Cloud trajectory"),
    ]
    for i, (c, label) in enumerate(items):
        y = h - 52 - (len(items) - 1 - i) * 17
        cv2.circle(frame, (14, y - 4), 4, c, -1)
        cv2.putText(frame, label, (22, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.37, (180, 180, 180), 1, cv2.LINE_AA)


def _draw_maintenance_banner(frame: np.ndarray, alert: str) -> None:
    """Amber banner at the bottom — shows Arduino ALERT/PREDICTION messages."""
    h, w = frame.shape[:2]
    bh   = 34
    y1   = h - bh

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, y1), (w, h), (0, 180, 255), -1)
    cv2.addWeighted(overlay, 0.78, frame, 0.22, 0, frame)

    max_chars = w // 9
    display   = alert if len(alert) <= max_chars else alert[:max_chars - 1] + "\u2026"
    label     = f"  \u26a0  {display}"
    cv2.putText(frame, label, (8, h - 9),
                cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.putText(frame, label, (8, h - 9),
                cv2.FONT_HERSHEY_SIMPLEX, 0.50, (10, 10, 100), 1, cv2.LINE_AA)


def _dashed_circle(
    frame: np.ndarray,
    center: tuple,
    radius: int,
    color: tuple,
    thickness: int = 1,
    dash_deg: float = 10.0,
    gap_deg: float = 8.0,
) -> None:
    """Draw a dashed circle using short arc segments."""
    step  = dash_deg + gap_deg
    angle = 0.0
    while angle < 360.0:
        end = min(angle + dash_deg, 360.0)
        cv2.ellipse(frame, center, (radius, radius), 0, angle, end,
                    color, thickness, cv2.LINE_AA)
        angle += step


def _dotted_line(
    frame: np.ndarray,
    pt1: tuple,
    pt2: tuple,
    color: tuple,
    dash: int = 6,
    gap: int = 4,
    thickness: int = 1,
) -> None:
    """Draw a dotted line between two points."""
    x1, y1 = pt1
    x2, y2 = pt2
    dist = int(np.hypot(x2 - x1, y2 - y1))
    if dist == 0:
        return
    ddx = (x2 - x1) / dist
    ddy = (y2 - y1) / dist
    d   = 0
    while d < dist:
        end = min(d + dash, dist)
        p1 = (int(x1 + ddx * d),   int(y1 + ddy * d))
        p2 = (int(x1 + ddx * end), int(y1 + ddy * end))
        cv2.line(frame, p1, p2, color, thickness, cv2.LINE_AA)
        d += dash + gap
