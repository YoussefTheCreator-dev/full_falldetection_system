# Fall Detection System

## Project Overview

This is a comprehensive Fall Detection System designed for integration between a Raspberry Pi and an ESP32 microcontroller. The primary goal of the system is to detect falls using sensor data from the ESP32 and then to trigger alerts, capture visual evidence with a Raspberry Pi camera, and provide a real-time monitoring dashboard.

The system operates as follows:
- **ESP32:** Collects accelerometer and gyroscope data, processes it to detect potential falls, and publishes relevant sensor readings and fall alerts to an MQTT broker.
- **Raspberry Pi:** Subscribes to MQTT topics to receive data and alerts from the ESP32. Upon detecting a fall alert, it activates a camera (Picamera2) to capture snapshots and initiates motion detection. It also hosts a web-based dashboard using Flask and SocketIO for real-time monitoring of system status, sensor data, and captured snapshots.

## Main Technologies

*   **Raspberry Pi Application (Python):**
    *   **Frameworks:** Flask, Flask-SocketIO
    *   **MQTT Client:** `paho-mqtt`
    *   **Camera Interface:** `Picamera2`
    *   **Image Processing:** `OpenCV` (cv2), `numpy`
    *   **AI/Pose Estimation:** `tflite-runtime` (for PoseNet model for posture detection)
    *   **Audio Playback:** `pygame`
    *   **Email:** `smtplib`, `email`
    *   **Concurrency:** `threading`
*   **ESP32 Firmware (Arduino/C++):**
    *   **IMU Library:** `FastIMU` (for MPU6500)
    *   **Display Library:** `U8g2lib` (for OLED display)
    *   **Networking:** WiFi, `PubSubClient` (for MQTT)
    *   **JSON Handling:** `ArduinoJson`
*   **Communication Protocol:** MQTT
*   **User Interface:** Web Dashboard (HTML, CSS, JavaScript)

## Architecture

The system follows a client-server architecture with MQTT as the central messaging backbone:

1.  **ESP32 (Client):**
    *   Continuously reads data from the MPU6500 (accelerometer, gyroscope).
    *   Executes a fall detection algorithm based on amplitude and angle changes.
    *   Publishes sensor data to `fall/sensor` MQTT topic.
    *   Publishes fall alerts (e.g., `alert`, `emergency`, `cancelled`) to `fall/alert` MQTT topic.
    *   Manages an OLED display for status feedback and a button for alert cancellation.

2.  **Raspberry Pi (Server):**
    *   **MQTT Listener:** Subscribes to `fall/sensor`, `fall/alert`, and `fall/status` topics.
    *   **State Management:** Maintains `system_state` (idle, alert, emergency) using a `threading.Lock` for thread-safe access.
    *   **Camera Module:** Initializes `Picamera2`, captures still images during alerts, and performs motion detection.
    *   **Web Server (Flask):** Serves the `dashboard.html` interface.
    *   **WebSocket (Flask-SocketIO):** Provides real-time updates to connected web clients (browser dashboard) on system status, motion detection, and new snapshots.
    *   **Alert Handling:** Triggers snapshot capture and starts motion monitoring when a fall alert is received. Escalates to emergency mode if an alert is not cancelled.

## Building and Running

### Raspberry Pi Application

1.  **Prerequisites:**
    *   Raspberry Pi with a connected Picamera2 module.
    *   Python 3 installed.
    *   MQTT Broker running (can be on the same Raspberry Pi or a separate machine).
    *   `libcamera` and `picamera2` libraries correctly installed and configured for your Raspberry Pi OS.

2.  **Install Python Dependencies:**
    ```bash
    pip install Flask Flask-SocketIO paho-mqtt opencv-python numpy tflite-runtime pygame
    ```
    (Note: `picamera2` usually requires specific installation steps beyond pip, refer to official documentation).

3.  **Configuration:**
    *   Review `fall_detection_config.py`.
    *   Ensure `PI_IP` matches your Raspberry Pi's IP address.
    *   Verify `MQTT_BROKER` points to your MQTT server.
    *   Adjust `CAMERA_RESOLUTION`, `SNAPSHOT_FOLDER`, and fall detection thresholds as needed.

4.  **Run the Application:**
    ```bash
    python3 fall_detection_main.py
    ```
    The web dashboard will be accessible via a browser at `http://<YOUR_PI_IP>:<FLASK_PORT>` (e.g., `http://10.13.101.209:5000`).

### ESP32 Firmware

1.  **Prerequisites:**
    *   ESP32 development board (e.g., ESP32-C3).
    *   MPU6500 IMU sensor connected.
    *   OLED display connected.
    *   Arduino IDE installed with ESP32 board support.

2.  **Install Arduino Libraries:**
    *   `FastIMU`
    *   `U8g2lib`
    *   `PubSubClient`
    *   `ArduinoJson`
    (Install via Arduino IDE's Library Manager).

3.  **Configuration:**
    *   Open `esp32_fall_detection_mqtt.ino` in Arduino IDE.
    *   **WiFi Credentials:** Update `const char* ssid = "ADU-STEAM";` and `const char* password = "YOUR_WIFI_PASSWORD_HERE";` with your actual WiFi network details.
    *   **MQTT Broker IP:** Update `const char* mqtt_server = "10.13.101.209";` to match the IP address of your MQTT broker (likely your Raspberry Pi's IP).
    *   Adjust sensor thresholds (`FREEFALL_THRESHOLD`, `IMPACT_THRESHOLD`, etc.) if necessary for your environment.

4.  **Upload Firmware:**
    *   Select the correct ESP32 board and COM port in Arduino IDE.
    *   Compile and upload the sketch to your ESP32.
