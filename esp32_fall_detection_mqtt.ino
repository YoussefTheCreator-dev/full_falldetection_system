/*
 * ESP32-C3 Fall Detection with WiFi and MQTT
 * Sends sensor data and alerts to Raspberry Pi
 */

#include <Wire.h>
#include <U8g2lib.h>
#include <FastIMU.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ===== WiFi Configuration =====
const char* ssid = "ADU-STEAM";
const char* password = "YOUR_WIFI_PASSWORD_HERE";  // ⚠️ REPLACE THIS

// ===== MQTT Configuration =====
const char* mqtt_server = "10.13.101.209";
const int mqtt_port = 1883;
const char* mqtt_client_id = "ESP32_Fall_Detection";

// MQTT Topics
const char* topic_sensor = "fall/sensor";
const char* topic_alert = "fall/alert";
const char* topic_status = "fall/status";

// ===== Time Configuration =====
#include <time.h>
const char* ntpServer = "pool.ntp.org";
// Your timezone offset in seconds. E.g., for GMT+4 (UAE), use 4 * 3600
const long  gmtOffset_sec = 4 * 3600;
// Daylight saving offset. Set to 0 if not applicable.
const int   daylightOffset_sec = 0;
struct tm timeinfo;
char timeHourMin[6]; // HH:MM
char dateDay[12]; // e.g., "Sun, Feb 13"

// ===== UI / Display Variables =====
int wifi_animation_frame = 0;

// ===== ESP32-C3 Pin Definitions =====
#define SDA_PIN 5
#define SCL_PIN 6
#define RED_PIN 4
#define GREEN_PIN 7
#define BLUE_PIN 8
#define BUZZER_PIN 3
#define BUTTON_PIN 2
#define MPU6500_ADDRESS 0x68

// ===== Display Setup =====
U8G2_SSD1306_72X40_ER_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE, SCL_PIN, SDA_PIN);

// ===== IMU Setup =====
MPU6500 IMU;
AccelData accel;
GyroData gyro;
calData calib;

// ===== WiFi & MQTT Clients =====
WiFiClient espClient;
PubSubClient mqttClient(espClient);

// ===== Fall Detection Variables =====
boolean fall = false;
boolean trigger1 = false;
boolean trigger2 = false;
boolean trigger3 = false;
byte trigger1count = 0;
byte trigger2count = 0;
byte trigger3count = 0;

// ===== Alert System Variables =====
boolean alertActive = false;
// const unsigned long ALERT_TIMEOUT = 30000; // 30 seconds - Handled by RPi now

// ===== Button Hold Variables =====
const unsigned long HOLD_TO_CANCEL_MS = 3000;
unsigned long buttonPressStart = 0;
bool buttonWasDown = false;

// ===== Sensor Values =====
float ax = 0, ay = 0, az = 0;
float gx = 0, gy = 0, gz = 0;

// ===== Thresholds =====
#define FREEFALL_THRESHOLD 3
#define IMPACT_THRESHOLD 20
#define ANGLE_MIN 20
#define ANGLE_MAX 400
#define STILLNESS_THRESHOLD 15

// ===== Peak Tracking =====
int maxAmpSeen = 0;
int minAmpSeen = 100;
float maxAngleSeen = 0;

// ===== Buzzer Pattern Variables =====
unsigned long buzzerTimer = 0;
bool buzzerOn = false;
uint16_t currentToneHz = 0;

// ===== MQTT Publishing Variables =====
unsigned long lastSensorPublish = 0;
const unsigned long SENSOR_PUBLISH_INTERVAL = 2000; // Publish every 2 seconds

// ============================================================
// SETUP
// ============================================================
void setup() {
  Serial.begin(115200);
  
  // Pin Setup
  pinMode(RED_PIN, OUTPUT);
  pinMode(GREEN_PIN, OUTPUT);
  pinMode(BLUE_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  digitalWrite(BUZZER_PIN, LOW);
  
  setRGB(0, 0, 255); // Blue - Initializing
  
  // Display initialization
  u8g2.begin();
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_micro_tr);
  u8g2.drawStr(10, 15, "Booting");
  u8g2.drawStr(15, 25, "System");
  u8g2.sendBuffer();
  delay(1000);
  
  // Connect to WiFi
  connectWiFi();
  
  // Setup MQTT
  mqttClient.setServer(mqtt_server, mqtt_port);
  
  // Initialize I2C
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);
  delay(100);
  
  // Initialize MPU6500
  u8g2.clearBuffer();
  u8g2.drawStr(5, 15, "Init MPU");
  u8g2.drawStr(10, 25, "6500...");
  u8g2.sendBuffer();
  
  int err = IMU.init(calib, MPU6500_ADDRESS);
  if (err != 0) {
    u8g2.clearBuffer();
    u8g2.setFont(u8g2_font_6x10_tr);
    u8g2.drawStr(5, 15, "MPU FAIL");
    u8g2.setFont(u8g2_font_micro_tr);
    u8g2.setCursor(10, 30);
    u8g2.print("Err: ");
    u8g2.print(err);
    u8g2.sendBuffer();
    while (1) {
      setRGB(255, 0, 0);
      delay(200);
      setRGB(0, 0, 0);
      delay(200);
    }
  }
  
  u8g2.clearBuffer();
  u8g2.drawStr(5, 15, "MPU OK!");
  u8g2.drawStr(2, 30, "Monitoring");
  u8g2.sendBuffer();
  delay(1500);
  
  setRGB(0, 255, 0); // Green - Ready
  
  // Connect to MQTT
  reconnectMQTT();
  
  // Send initial status
  publishStatus("idle");
}

// ============================================================
// MAIN LOOP
// ============================================================
void loop() {
  // Update time for display
  updateLocalTime();

  // Cycle through WiFi animation frames
  static unsigned long lastAnimUpdate = 0;
  if (millis() - lastAnimUpdate > 500) {
    wifi_animation_frame = (wifi_animation_frame + 1) % 3;
    lastAnimUpdate = millis();
  }

  // Maintain MQTT connection
  if (!mqttClient.connected()) {
    reconnectMQTT();
  }
  mqttClient.loop();
  
  // Handle button hold
  handleButtonHold();
  
  // Check alert timeout (now handled by Raspberry Pi)
  // if (alertActive && (millis() - alertStartTime > ALERT_TIMEOUT)) {
  //   confirmFall();
  // }
  
  // Alert mode buzzer
  if (alertActive) {
    updateBuzzerPattern();
  } else {
    if (currentToneHz != 0) {
      noTone(BUZZER_PIN);
      currentToneHz = 0;
    }
  }
  
  // Read sensor data
  IMU.update();
  IMU.getAccel(&accel);
  IMU.getGyro(&gyro);
  
  ax = accel.accelX;
  ay = accel.accelY;
  az = accel.accelZ;
  gx = gyro.gyroX;
  gy = gyro.gyroY;
  gz = gyro.gyroZ;
  
  // Calculate amplitude
  float Raw_Amp = sqrt(ax * ax + ay * ay + az * az);
  int Amp = Raw_Amp * 10;
  
  // Calculate angular velocity
  float angleChange = sqrt(gx * gx + gy * gy + gz * gz);
  
  // Track peaks
  if (Amp > maxAmpSeen) maxAmpSeen = Amp;
  if (Amp < minAmpSeen) minAmpSeen = Amp;
  if (angleChange > maxAngleSeen) maxAngleSeen = angleChange;
  
  // Fall detection algorithm
  // TRIGGER 1: Free Fall
  if (Amp <= FREEFALL_THRESHOLD && trigger2 == false) {
    trigger1 = true;
  }
  
  // TRIGGER 2: Impact
  if (trigger1 == true) {
    trigger1count++;
    if (Amp >= IMPACT_THRESHOLD) {
      trigger2 = true;
      trigger1 = false;
      trigger1count = 0;
    }
  }
  
  // TRIGGER 3: Orientation Change
  if (trigger2 == true) {
    trigger2count++;
    if (angleChange >= ANGLE_MIN && angleChange <= ANGLE_MAX) {
      trigger3 = true;
      trigger2 = false;
      trigger2count = 0;
    }
  }
  
  // FINAL CHECK: Stillness
  if (trigger3 == true) {
    trigger3count++;
    if (trigger3count >= 10) {
      angleChange = sqrt(gx * gx + gy * gy + gz * gz);
      if (angleChange >= 0 && angleChange <= STILLNESS_THRESHOLD) {
        fall = true;
        trigger3 = false;
        trigger3count = 0;
      } else {
        trigger3 = false;
        trigger3count = 0;
      }
    }
  }
  
  // FALL DETECTED
  if (fall == true) {
    startAlert();
    fall = false;
  }
  
  // Timeouts
  if (trigger2count >= 6) {
    trigger2 = false;
    trigger2count = 0;
  }
  if (trigger1count >= 6) {
    trigger1 = false;
    trigger1count = 0;
  }
  
  // Publish sensor data periodically
  if (millis() - lastSensorPublish > SENSOR_PUBLISH_INTERVAL) {
    publishSensorData(Amp, angleChange);
    lastSensorPublish = millis();
  }
  
  updateDisplay(Amp, angleChange);
  delay(100);
}

// ============================================================
// WiFi Functions
// ============================================================
void connectWiFi() {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_micro_tr);
  u8g2.drawStr(5, 15, "WiFi...");
  u8g2.sendBuffer();
  
  WiFi.begin(ssid, password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi Connected!");
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());
    
    u8g2.clearBuffer();
    u8g2.drawStr(5, 15, "WiFi OK!");
    u8g2.sendBuffer();
    delay(1000);

    // Init and get time
    configTime(gmtOffset_sec, daylightOffset_sec, ntpServer);

  } else {
    Serial.println("\nWiFi Failed!");
    u8g2.clearBuffer();
    u8g2.drawStr(5, 15, "WiFi");
    u8g2.drawStr(5, 25, "Failed");
    u8g2.sendBuffer();
    delay(2000);
  }
}

// ============================================================
// MQTT Functions
// ============================================================
void reconnectMQTT() {
  int attempts = 0;
  while (!mqttClient.connected() && attempts < 5) {
    Serial.print("Connecting to MQTT...");
    
    if (mqttClient.connect(mqtt_client_id)) {
      Serial.println("connected!");
      publishStatus("connected");
      break;
    } else {
      Serial.print("failed, rc=");
      Serial.println(mqttClient.state());
      delay(2000);
      attempts++;
    }
  }
}

void publishSensorData(int amplitude, float angleChange) {
  if (!mqttClient.connected()) return;
  
  StaticJsonDocument<200> doc;
  doc["amplitude"] = amplitude;
  doc["angle_change"] = (int)angleChange;
  doc["device_state"] = alertActive ? "alert" : "normal";
  doc["timestamp"] = millis();
  
  char buffer[200];
  serializeJson(doc, buffer);
  
  mqttClient.publish(topic_sensor, buffer);
}

void publishAlert(const char* status) {
  if (!mqttClient.connected()) return;
  
  StaticJsonDocument<200> doc;
  doc["status"] = status;
  doc["timestamp"] = millis();
  
  char buffer[200];
  serializeJson(doc, buffer);
  
  mqttClient.publish(topic_alert, buffer);
  Serial.print("Alert published: ");
  Serial.println(status);
}

void publishStatus(const char* status) {
  if (!mqttClient.connected()) return;
  
  StaticJsonDocument<200> doc;
  doc["status"] = status;
  doc["timestamp"] = millis();
  
  char buffer[200];
  serializeJson(doc, buffer);
  
  mqttClient.publish(topic_status, buffer);
}

// ============================================================
// Button Handling
// ============================================================
void handleButtonHold() {
  bool down = (digitalRead(BUTTON_PIN) == LOW);
  
  if (down && !buttonWasDown) {
    buttonWasDown = true;
    buttonPressStart = millis();
  } else if (!down && buttonWasDown) {
    buttonWasDown = false;
    buttonPressStart = 0;
  }
  
  if (buttonWasDown) {
    unsigned long held = millis() - buttonPressStart;
    if (alertActive && held >= HOLD_TO_CANCEL_MS) {
      cancelAlert();
      buttonWasDown = false;
      buttonPressStart = 0;
    }
  }
}

// ============================================================
// Alert Functions
// ============================================================
void startAlert() {
  alertActive = true;
  setRGB(255, 165, 0);
  buzzerTimer = millis();
  buzzerOn = false;
  currentToneHz = 0;
  
  publishAlert("alert");
  Serial.println("FALL DETECTED - Alert started");
}

void cancelAlert() {
  alertActive = false;
  setRGB(0, 255, 0);
  noTone(BUZZER_PIN);
  currentToneHz = 0;
  
  publishAlert("cancelled");
  Serial.println("Alert cancelled");
  
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tr);
  u8g2.drawStr(5, 20, "Canceled!");
  u8g2.sendBuffer();
  delay(1000);
}


// ============================================================
// Buzzer Patterns
// ============================================================
void updateBuzzerPattern() {
  unsigned long now = millis();
  
  if (alertActive) {
    static uint8_t step = 0;
    static unsigned long stepStart = 0;
    if (stepStart == 0) stepStart = now;
    unsigned long dt = now - stepStart;
    
    switch (step) {
      case 0:
        setToneIfNeeded(1800);
        if (dt >= 120) { step = 1; stepStart = now; }
        break;
      case 1:
        setToneIfNeeded(0);
        if (dt >= 120) { step = 2; stepStart = now; }
        break;
      case 2:
        setToneIfNeeded(1800);
        if (dt >= 120) { step = 3; stepStart = now; }
        break;
      case 3:
        setToneIfNeeded(0);
        if (dt >= 400) { step = 0; stepStart = now; }
        break;
    }
  }
}

void setToneIfNeeded(uint16_t hz) {
  if (hz == 0) {
    if (currentToneHz != 0) {
      noTone(BUZZER_PIN);
      currentToneHz = 0;
    }
  } else {
    if (currentToneHz != hz) {
      tone(BUZZER_PIN, hz);
      currentToneHz = hz;
    }
  }
}

// ============================================================
// Display Functions
// ============================================================

// New function to get and format the local time
bool updateLocalTime() {
  if (!getLocalTime(&timeinfo)) {
    return false;
  }
  strftime(timeHourMin, sizeof(timeHourMin), "%H:%M", &timeinfo);
  strftime(dateDay, sizeof(dateDay), "%a, %b %d", &timeinfo);
  return true;
}

void drawWatchFace(int amp, float angleChange); // Forward declaration

void updateDisplay(int amp, float angleChange) {
  if (alertActive) {
    // If an alert is active, show the critical FALL screen
    u8g2.clearBuffer();
    u8g2.setFont(u8g2_font_9x15_tf);
    u8g2.drawStr(5, 15, "FALL!");
    u8g2.setFont(u8g2_font_micro_tr);
    u8g2.drawStr(0, 28, "Hold btn 3s");
    u8g2.sendBuffer();
    
    // Blink orange LED in alert mode
    if ((millis() / 500) % 2 == 0) {
      setRGB(255, 165, 0);
    } else {
      setRGB(0, 0, 0);
    }
  } else {
    // Otherwise, show the normal watch face
    drawWatchFace(amp, angleChange);
    
    // Keep LED solid green when idle
    static unsigned long lastGreenLedUpdate = 0;
    if (millis() - lastGreenLedUpdate > 1000) { // Update once a second to be safe
      setRGB(0, 255, 0);
      lastGreenLedUpdate = millis();
    }
  }
}

// New function to draw the main "watch" interface
void drawWatchFace(int amp, float angleChange) {
  u8g2.clearBuffer();

  // 1. Draw WiFi Icon (top right)
  u8g2.setFont(u8g2_font_open_iconic_www_1x_t);
  // Animate using different glyphs from the icon font to show "broadcasting"
  switch(wifi_animation_frame) {
    case 0: u8g2.drawGlyph(62, 9, 69); break; // Low signal icon
    case 1: u8g2.drawGlyph(62, 9, 70); break; // Medium signal icon
    case 2: u8g2.drawGlyph(62, 9, 71); break; // High signal icon
  }

  // 2. Draw Time (Centered and large)
  u8g2.setFont(u8g2_font_logisoso16_tr);
  int timeWidth = u8g2.getStrWidth(timeHourMin);
  u8g2.drawStr((72 - timeWidth) / 2, 22, timeHourMin);

  // 3. Draw Date (Below time, smaller font)
  u8g2.setFont(u8g2_font_5x7_tr);
  int dateWidth = u8g2.getStrWidth(dateDay);
  u8g2.drawStr((72 - dateWidth) / 2, 30, dateDay);
  
  // 4. Draw Sensor data (Bottom)
  char sensorLine[20];
  sprintf(sensorLine, "A:%d  G:%d", amp, (int)angleChange);
  int sensorWidth = u8g2.getStrWidth(sensorLine);
  u8g2.drawStr((72 - sensorWidth) / 2, 39, sensorLine);

  u8g2.sendBuffer();
}

void setRGB(int red, int green, int blue) {
  analogWrite(RED_PIN, red);
  analogWrite(GREEN_PIN, green);
  analogWrite(BLUE_PIN, blue);
}