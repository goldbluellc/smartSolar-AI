# SmartSolar AI

Real-time computer vision system that tracks the sun, detects approaching clouds, predicts shadow threats via cloud motion vectors, and automatically rotates a solar panel via servo motors to stay in direct sunlight.

---

## Quick Start

```bash
pip install -r requirements.txt
python demo_launcher.py        # interactive one-click launcher
```

---

## Modes

### Live Camera Mode
```bash
python live_mode.py                          # webcam index 0
python live_mode.py --camera 1               # alternate camera
python live_mode.py --camera 0 --serial COM3 # with Arduino
python live_mode.py --fullscreen --demo      # stage presentation
```

On startup, auto-calibrates sun/cloud thresholds from 15 sky frames.

### Video Mode
```bash
python main.py --video test_sky.mp4
python main.py --video test_sky.mp4 --serial COM3
python main.py --video test_sky.mp4 --mqtt 192.168.1.100
python main.py --video test_sky.mp4 --fullscreen --demo
```

### RFC 2217 (Wokwi VS Code Extension)
```bash
python main.py --video test_sky.mp4 --serial rfc2217://localhost:4000
```

### Record a Demo Video
```bash
python demo_recorder.py --video test_sky.mp4
# outputs: demo_output.avi, demo_safe.png, demo_warning.png, demo_danger.png
```

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Q` / `ESC` | Quit |
| `F` | Toggle fullscreen |
| `S` | Save screenshot |
| `C` | Recalibrate thresholds *(live mode)* |
| `R` | Draw sky ROI region *(live mode)* |
| `=` / `-` | Sun brightness threshold ±5 *(live mode)* |
| `]` / `[` | Cloud darkness threshold ±5 *(live mode)* |

---

## Arduino Serial Protocol

The Arduino firmware (`arduino_receiver/sketch.ino`) expects:

| Command | Meaning |
|---------|---------|
| `P{angle}\n` | Set pan servo (0–180°) |
| `T{angle}\n` | Set tilt servo (0–180°) |
| `E1\n` | Enable warning LED (DANGER edge) |
| `E0\n` | Disable warning LED (SAFE edge) |

E1/E0 are sent only on threat **state change**, not every frame.

---

## Project Structure

```
SmartsolarAI/
├── demo_launcher.py    # One-click interactive launcher (start here)
├── main.py             # Video / webcam pipeline entry point
├── live_mode.py        # Live camera mode with adaptive calibration
├── demo_recorder.py    # Record pipeline output to .avi
├── sun_detector.py     # Locates sun via brightness thresholding
├── cloud_detector.py   # Detects cloud blobs via inverse threshold
├── cloud_tracker.py    # Nearest-neighbour cloud tracking, motion vectors
├── shadow_analyzer.py  # Predicts SAFE / WARNING / DANGER from trajectories
├── servo_mapper.py     # Maps pixel coords to servo angles (0–180°)
├── hud_overlay.py      # Phase-4 HUD (border, risk bar, trajectory lines)
├── serial_sender.py    # Sends P/T/E commands to Arduino via USB serial
├── mqtt_sender.py      # Sends commands to ESP32 via WiFi / MQTT
├── config.py           # All tunable constants
├── arduino_receiver/
│   ├── sketch.ino      # Arduino firmware (pan, tilt, LED, diagnostics)
│   └── diagram.json    # Wokwi circuit diagram
├── wokwi_bridge.py     # Connects pipeline to Wokwi cloud simulation
├── wokwi_test.py       # Standalone Wokwi serial sweep test
├── integration_test.py # Simulated end-to-end integration test
├── demo_script.md      # Stage talking points for live presentation
└── requirements.txt
```

---

## Config Tuning

Edit `config.py` to adjust sensitivity:

| Constant | Default | Effect |
|----------|---------|--------|
| `SUN_BRIGHTNESS_THRESHOLD` | 240 | Min brightness to detect sun |
| `CLOUD_DARKNESS_THRESHOLD` | 120 | Max brightness to detect cloud |
| `MIN_CLOUD_AREA` | 2000 | Min px² to count as a cloud |
| `SHADOW_DANGER_ZONE_PX` | 80 | Distance (px) for DANGER trigger |

Live mode overrides these automatically via adaptive calibration.

---

## Getting Test Videos

Search for `cloud timelapse` on [Pixabay](https://pixabay.com/videos/search/sky%20timelapse/) or [Pexels](https://www.pexels.com/search/videos/cloud%20timelapse/) — 30–60 s clips with visible cumulus clouds work best.
