"""
mqtt_sender.py — Sends servo commands via MQTT (WiFi mode).

Publishes to topic "smartsolar/commands" as JSON.
Payload: {"x": 90, "y": 45, "threat": "SAFE"}
"""

import json
from config import MQTT_PORT

MQTT_COMMANDS_TOPIC = "smartsolar/commands"

try:
    import paho.mqtt.client as _mqtt_client
    _MQTT_AVAILABLE = True
except ImportError:
    _mqtt_client = None
    _MQTT_AVAILABLE = False


def init_mqtt(broker_ip: str, port: int = MQTT_PORT):
    """
    Create and connect an MQTT client to the broker.

    Args:
        broker_ip: IP address or hostname of the MQTT broker.
        port:      Broker port (default 1883).

    Returns:
        Connected paho MQTT client, or None on failure.
    """
    if not _MQTT_AVAILABLE:
        print("[mqtt] paho-mqtt not installed — MQTT output disabled.")
        return None
    try:
        client = _mqtt_client.Client(client_id="smartsolar_ai")
        client.connect(broker_ip, port, keepalive=60)
        client.loop_start()
        print(f"[mqtt] Connected to broker {broker_ip}:{port}")
        return client
    except Exception as e:
        print(f"[mqtt] Failed to connect to {broker_ip}:{port}: {e}")
        return None


def send_command_mqtt(
    client,
    servo_x: int,
    servo_y: int,
    threat_level: str,
) -> bool:
    """
    Publish a servo command as JSON to "smartsolar/commands".

    Payload: {"x": servo_x, "y": servo_y, "threat": threat_level}

    Args:
        client:       Connected paho MQTT client (or None — silently skipped).
        servo_x:      Horizontal servo angle 0-180.
        servo_y:      Vertical servo angle 0-180.
        threat_level: e.g. "SAFE", "WARNING", "DANGER".

    Returns:
        True if publish was enqueued, False otherwise.
    """
    if client is None:
        return False
    try:
        payload = json.dumps({"x": servo_x, "y": servo_y, "threat": threat_level})
        result = client.publish(MQTT_COMMANDS_TOPIC, payload)
        return result.rc == 0
    except Exception as e:
        print(f"[mqtt] Publish error: {e}")
        return False


def close_mqtt(client) -> None:
    """Stop the client loop and disconnect."""
    if client is not None:
        try:
            client.loop_stop()
            client.disconnect()
            print("[mqtt] Disconnected.")
        except Exception:
            pass


# ── Class-based API (retained for backward compatibility) ──────────────────


class MQTTSender:
    def __init__(self, broker: str, port: int = MQTT_PORT, topic: str = MQTT_COMMANDS_TOPIC):
        self.broker = broker
        self.port = port
        self.topic = topic
        self._client = None

    def connect(self) -> bool:
        self._client = init_mqtt(self.broker, self.port)
        return self._client is not None

    def send_angles(self, angle_x: int, angle_y: int, threat: str = "SAFE") -> bool:
        return send_command_mqtt(self._client, angle_x, angle_y, threat)

    def disconnect(self) -> None:
        close_mqtt(self._client)
        self._client = None
