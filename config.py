# config.py — All tunable constants for SmartSolar AI

# Sun detection
SUN_BRIGHTNESS_THRESHOLD = 240  # Pixel brightness to identify sun region (0-255)

# Cloud detection
CLOUD_DARKNESS_THRESHOLD = 120  # Pixel brightness below which a region is "cloudy"
MIN_CLOUD_AREA = 2000           # Minimum pixel area to count as a cloud contour

# Shadow prediction
SHADOW_DANGER_ZONE_PX = 80     # Distance (px) from sun at which cloud is a threat

# Frame dimensions
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

# Servo output ranges (degrees)
SERVO_X_RANGE = (0, 180)
SERVO_Y_RANGE = (0, 180)

# Serial defaults
DEFAULT_BAUD_RATE = 9600

# MQTT defaults
MQTT_PORT = 1883
MQTT_TOPIC = "smartsolar/servo"
