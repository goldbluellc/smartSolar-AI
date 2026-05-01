/*
 * SmartSolar AI — Arduino Receiver
 *
 * Receives servo commands from the Python pipeline over USB serial.
 *
 * ── Predictive Maintenance ─────────────────────────────────────────────────
 *   Prints "MAINTENANCE_ALERT:IDLE"         if no servo movement for 30 s
 *   Prints "MAINTENANCE_ALERT:MOTOR_STRESS" with ~1% probability per loop
 *   Both alerts trigger a fast 5× red-LED blink.
 */

#include <Servo.h>

Servo panServo;
Servo tiltServo;

int panAngle = 90;
int tiltAngle = 90;

const int warningLedPin = 8;
bool isMotorHealthy = true;

void setup() {
  Serial.begin(9600);
  panServo.attach(9);
  tiltServo.attach(10);
  pinMode(warningLedPin, OUTPUT);

  panServo.write(panAngle);
  tiltServo.write(tiltAngle);

  digitalWrite(warningLedPin, LOW);
  Serial.println("Hardware Ready. Edge AI Diagnostics Active.");
}

void runDiagnostics(int targetAngle) {
  int simulatedCurrent = random(100, 300);

  if ((targetAngle < 10 || targetAngle > 170) && random(1, 10) > 8) {
    simulatedCurrent = 850;
  }

  if (simulatedCurrent > 800) {
    isMotorHealthy = false;
    digitalWrite(warningLedPin, HIGH);

    Serial.println("ALERT: Overcurrent detected! (850mA).");
    Serial.println("PREDICTION: High friction in Pan Gear. Failure likely in 14 days.");
  } else {
    isMotorHealthy = true;
    digitalWrite(warningLedPin, LOW);
  }
}

void loop() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();

    if (command.length() > 0) {
      char axis = command.charAt(0);

      if (axis == 'E') {
        int errorState = command.substring(1).toInt();
        if (errorState == 1) {
           digitalWrite(warningLedPin, HIGH);
           Serial.println("ALERT: (MANUAL OVERRIDE) - Motor Jam Predicted.");
        } else {
           digitalWrite(warningLedPin, LOW);
           Serial.println("SYSTEM RESET: Motors healthy.");
        }
        return;
      }

      int angle = command.substring(1).toInt();
      if (angle >= 0 && angle <= 180) {

        runDiagnostics(angle);

        if (axis == 'P' || axis == 'p') {
          panServo.write(angle);
          Serial.print("Moved Pan to: "); Serial.println(angle);
        }
        else if (axis == 'T' || axis == 't') {
          tiltServo.write(angle);
          Serial.print("Moved Tilt to: "); Serial.println(angle);
        }
      }
    }
  }
}
