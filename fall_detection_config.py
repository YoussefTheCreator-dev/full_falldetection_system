"""
Configuration file for Fall Detection System
"""

# Raspberry Pi Settings
PI_IP = "10.13.101.209"
FLASK_PORT = 5000

# MQTT Settings
MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883
MQTT_TOPIC_SENSOR = "fall/sensor"
MQTT_TOPIC_ALERT = "fall/alert"
MQTT_TOPIC_STATUS = "fall/status"

# Camera Settings
CAMERA_RESOLUTION = (320, 240)
SNAPSHOT_FOLDER = "snapshots"

# AI Model Settings
POSENET_MODEL_PATH = "posenet_mobilenet_v1_100_257x257_multi_kpt_stripped.tflite"
YOLO_MODEL_PATH = "yolov8n.pt" # Placeholder for YOLO model path
YOLO_POSE_MODEL_NAME = "yolov8n-pose.pt" # YOLOv8 model for pose estimation

# Fall Detection Settings
ALERT_TIMEOUT = 30  # seconds (Overall timeout for alert escalation)
EMERGENCY_TRIGGER_DURATION = 30 # seconds (How long person must be fallen AND motionless to trigger emergency)
MOTION_THRESHOLD = 25  # OpenCV motion detection threshold
MOTION_MIN_AREA = 500  # Minimum contour area to detect motion

# WiFi Settings (for ESP32)
WIFI_SSID = "ADU-STEAM"
# Note: You'll need to add your WiFi password in the ESP32 code

# Email Settings for Emergency Alerts
EMAIL_SENDER = "bme425falldetection@gmail.com"
EMAIL_PASSWORD = "ervzypzkdqlyqrie"
EMAIL_RECIPIENT = "mazengumball@gmail.com"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587