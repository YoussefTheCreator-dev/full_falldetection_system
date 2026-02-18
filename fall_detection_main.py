#!/usr/bin/env python3
"""
Fall Detection System - Main Application
Receives data from ESP32, manages camera, serves web dashboard
"""

import json
import os
import time
from datetime import datetime
from threading import Thread, Lock
import cv2
import numpy as np
from flask import Flask, render_template, jsonify, send_from_directory, Response
from flask_socketio import SocketIO, emit
import paho.mqtt.client as mqtt
from picamera2 import Picamera2
import pygame
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from fall_detection_config import *
from yolo_streamer_optimized import YOLOStreamer


app = Flask(__name__)
app.config['SECRET_KEY'] = 'fall_detection_secret_2025'
socketio = SocketIO(app, cors_allowed_origins="*")


system_state = {
    'status': 'idle',  # idle, alert, emergency
    'last_sensor_data': {},
    'fall_detected_time': None,
    'alert_active': False,
    'emergency_active': False,

    'sound_muted': False,
    'latest_snapshot': None,
    'sensor_history': [],



}
state_lock = Lock()


picam2 = None
previous_frame = None # Will still be used for generic motion detection if no YOLO person





mqtt_client = mqtt.Client(client_id="raspberry_pi_fall_detection")

def init_camera():
    """Initialize Raspberry Pi camera"""
    global picam2
        try:
        picam2 = Picamera2()

        config = picam2.create_still_configuration(
            main={"size": CAMERA_RESOLUTION}
        )
        print(f"[CAMERA_DEBUG] Still configuration created: {CAMERA_RESOLUTION}")
        picam2.configure(config)

        picam2.start()

    
        print("[CAMERA] Initialized successfully")
        return True
    except Exception as e:
        print(f"[CAMERA] Error initializing: {e}")
        import traceback

        return False
def capture_snapshot(frame=None):
    """Capture image from camera or save a provided frame."""
    global picam2, yolo_streamer

    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"fall_snapshot_{timestamp}.jpg"
        filepath = os.path.join(SNAPSHOT_FOLDER, filename)
        
        os.makedirs(SNAPSHOT_FOLDER, exist_ok=True)
        
        if frame is not None:

            cv2.imwrite(filepath, frame)
            print(f"[CAMERA_DEBUG] Saved provided frame to {filepath}")

            if yolo_streamer and yolo_streamer.get_latest_frame() is not None:
                frame_to_save = yolo_streamer.get_latest_frame()
                cv2.imwrite(filepath, frame_to_save)
                print(f"[CAMERA_DEBUG] Saved latest frame from YOLOStreamer to {filepath}")

                request = picam2.capture_request()
                request.save("main", filepath)
                request.release()
                print(f"[CAMERA_DEBUG] Captured new frame from Picamera2 to {filepath}")
            else:

                return None
            
        print(f"[CAMERA] Snapshot saved: {filename}")
        return filename
    except Exception as e:
        print(f"[CAMERA] Error capturing snapshot: {e}")
        import traceback
        traceback.print_exc()
        return None


def on_mqtt_connect(client, userdata, flags, rc, properties=None):
    """Callback when connected to MQTT broker"""
    if rc == 0:
        print("[MQTT] Connected successfully")
        client.subscribe(MQTT_TOPIC_SENSOR)
        client.subscribe(MQTT_TOPIC_ALERT)
        client.subscribe(MQTT_TOPIC_STATUS)
    else:
        print(f"[MQTT] Connection failed with code {rc}. See paho.mqtt.client documentation for details.")

def on_mqtt_message(client, userdata, msg):
    """Callback when MQTT message received"""
    global system_state
    
    try:
        payload = json.loads(msg.payload.decode())
        topic = msg.topic
        
        print(f"[MQTT] Received on {topic}: {payload}")
        
        with state_lock:

                system_state['last_sensor_data'] = payload
                system_state['sensor_history'].append({
                    'timestamp': datetime.now().isoformat(),
                    'data': payload
                })

                if len(system_state['sensor_history']) > 100:
                    system_state['sensor_history'].pop(0)
                

                if payload.get('status') == 'alert':
                    handle_fall_alert()
                elif payload.get('status') == 'emergency':
                    handle_emergency()
                elif payload.get('status') == 'cancelled':
                    handle_alert_cancelled()
                    

                system_state['status'] = payload.get('status', 'idle')
        

        socketio.emit('system_update', system_state)
        
    except Exception as e:
        print(f"[MQTT] Error processing message: {e}")

def send_emergency_email(snapshot_filename):
    """Send an emergency email with a snapshot attached"""
    print("[EMAIL] Preparing to send emergency email...")

        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = EMAIL_RECIPIENT
        msg['Subject'] = "!! EMERGENCY ALERT: Fall Detected !!"
        

        body = f"""
        A fall has been detected and the emergency state has been triggered.
        
        Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        
        Please check on the person immediately.
        
        A snapshot from the camera is attached.
        """
        msg.attach(MIMEText(body, 'plain'))
        

        if snapshot_filename:
            filepath = os.path.join(SNAPSHOT_FOLDER, snapshot_filename)
            if os.path.exists(filepath):
                with open(filepath, 'rb') as attachment:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment.read())
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename= {snapshot_filename}',
                )
                msg.attach(part)
                print(f"[EMAIL] Attached snapshot: {snapshot_filename}")
        

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, text)
        server.quit()
        
        print(f"[EMAIL] Emergency email sent successfully to {EMAIL_RECIPIENT}")
        
    except Exception as e:
        print(f"[EMAIL] Failed to send email: {e}")

def play_emergency_sound():
    """Play the emergency alert sound at max volume, if not muted."""
    with state_lock:
        if system_state['sound_muted']:

            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
            print("[AUDIO] Sound is muted by user. Not playing.")
            return
            
    try:
        # These operations are thread-safe so we can do them outside the lock
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.set_volume(1.0)  # Set volume to max
        pygame.mixer.music.load("emergency_alert.mp3")
        pygame.mixer.music.play()
        print("[AUDIO] Playing emergency alert sound at max volume.")
    except Exception as e:
        print(f"[AUDIO] Error playing sound: {e}")

def handle_fall_alert():
    """Handle fall alert from ESP32"""
    global system_state
    
    print("[ALERT] Fall detected! Starting monitoring...")
    
    # No need for state_lock here, as on_mqtt_message already holds it
    system_state['alert_active'] = True
    system_state['status'] = 'alert'
    system_state['fall_detected_time'] = datetime.now().isoformat()
    
    # Capture snapshot

    snapshot = capture_snapshot()

    if snapshot:
        # This state update also doesn't need a lock, it's covered by the parent lock in on_mqtt_message
        system_state['latest_snapshot'] = snapshot
    
    # Start motion detection monitoring

    Thread(target=monitor_motion_after_fall, daemon=True).start()
    
    # Broadcast to web dashboard
    socketio.emit('fall_alert', {
        'message': 'Fall detected! Monitoring for movement...',
        'timestamp': system_state['fall_detected_time'],
        'snapshot': snapshot
    })

def handle_emergency():
    """Handle emergency state (no cancel after timeout)"""
    global system_state
    
    print("[EMERGENCY] Emergency state activated!")
    # NOTE: This function is called from within on_mqtt_message, which already holds state_lock.
    
    system_state['emergency_active'] = True
    system_state['alert_active'] = False
    system_state['status'] = 'emergency'
    

    person_present = system_state['person_present']
    # person_moving is no longer considered as per user request
    person_fallen_by_pose = system_state['person_fallen_by_pose']
    

    system_state['motion_detected'] = person_fallen_by_pose 
    
    print(f"[EMERGENCY_DEBUG] State set to 'emergency'. Person Present: {person_present}, Pose Fall: {person_fallen_by_pose}")
    

    socketio.emit('emergency_alert', {
        'message': 'EMERGENCY! No response detected!',
        'person_present': person_present,
        'person_fallen_by_pose': person_fallen_by_pose,
        'snapshot': system_state.get('latest_snapshot'),
        'sensor_data': system_state.get('last_sensor_data')
    })
    socketio.emit('system_update', system_state)



    Thread(target=send_emergency_email, args=(system_state.get('latest_snapshot'),), daemon=True).start()
    

    Thread(target=play_emergency_sound, daemon=True).start()


def handle_alert_cancelled():
    """Handle alert cancellation"""
    global system_state, previous_frame
    
    print("[ALERT] Alert cancelled by user")
    # NOTE: This function is called from within on_mqtt_message, which already holds state_lock.
    
    system_state['alert_active'] = False
    system_state['emergency_active'] = False
    system_state['status'] = 'idle'


    system_state['person_moving'] = False # Reset person_moving to False as it's no longer used for motion detection


    
    print(f"[CANCEL_DEBUG] State set to 'idle'.")
    

    socketio.emit('alert_cancelled', {
        'message': 'Alert cancelled successfully'
    })
    socketio.emit('system_update', system_state)


def monitor_motion_after_fall():
    """Monitor for motion (via YOLO) and take snapshots after fall detection or during emergency."""
    global system_state, yolo_streamer
    
    print("[MOTION] Starting continuous monitoring for motion and snapshots (YOLO-based)...")
    


    last_snapshot_time = time.time()
    last_sound_play_time = 0
    
    while True:
        try:
            current_time = time.time()
            with state_lock:
                alert_active_local = system_state['alert_active']
                emergency_active_local = system_state['emergency_active']
                

                if not alert_active_local and not emergency_active_local:
                    print("[MOTION] Monitoring stopped - neither alert nor emergency active. Breaking loop.")
                    fall_condition_met_start_time = None # Reset
                    break
                
                # Get latest YOLO status and PoseNet status
                person_present = system_state['person_present']
                person_fallen_by_pose = system_state['person_fallen_by_pose']
                print(f"[MOTION_THREAD_DEBUG] In loop: person_present={person_present}, person_fallen_by_pose={person_fallen_by_pose}")

                # === Handle Alert Countdown and Motion Update ===
                if alert_active_local:
                    time_elapsed_overall = current_time - start_monitoring_time
                    time_remaining_overall = max(0, int(ALERT_TIMEOUT - time_elapsed_overall))
                    
                    # Emergency Trigger Logic:
                    # If we are in the last 10 seconds of the 30s countdown (time_remaining <= 10)
                    # AND the AI detects a fall posture.
                    if time_remaining_overall <= 10:


                        if person_fallen_by_pose:
                            print(f"[MOTION] Emergency Condition Met: Person fallen in last 10s (Time Remaining: {time_remaining_overall}s). Escalating to EMERGENCY.")
                            handle_emergency()

                    

                    socketio.emit('motion_update', {
                        'person_present': person_present,
                        'person_fallen_by_pose': person_fallen_by_pose,
                        'time_remaining_overall': time_remaining_overall,
                        'time_remaining_fallen_motionless': time_remaining_overall 
                    })
                    print(f"[MOTION_DEBUG] Alert active. Time remaining: {time_remaining_overall}s. Person: {person_present}, Fall: {person_fallen_by_pose}")

                    # If overall alert timeout reached without specific emergency conditions met, cancel alert
                    if time_remaining_overall == 0:
                        # As per user request: Always trigger emergency at the end of the countdown if not cancelled by user.
                        print("[MOTION] Timeout reached. Escalating to EMERGENCY (Forced).")
                        handle_emergency()
                        # Do NOT break here, loop must continue for emergency sound
                    
                # === Handle Emergency Sound ===
                if emergency_active_local:
                    if current_time - last_sound_play_time >= 5:
                        Thread(target=play_emergency_sound, daemon=True).start()
                        last_sound_play_time = current_time
                    
                # === Continuous Snapshots ===
                if current_time - last_snapshot_time >= 5:
                    frame_to_save = yolo_streamer.get_latest_frame() if yolo_streamer else None
                    if frame_to_save is not None:
                        snapshot = capture_snapshot(frame=frame_to_save)
                        if snapshot:
                            system_state['latest_snapshot'] = snapshot
                            socketio.emit('system_update', system_state) 
                    last_snapshot_time = current_time
        
        except Exception as e:
            print(f"[ERROR] Exception in monitor_motion_after_fall thread: {e}")
            import traceback
            traceback.print_exc()
            break # Exit loop on error to prevent spinning

        time.sleep(1) # Sleep for a shorter interval to allow frequent checks and non-blocking behavior



def generate_frames():
    """Generator function for video streaming."""
    while True:
        try:
            # Wait for a frame to be available from the YOLO streamer

                time.sleep(0.5)
                continue

            frame = yolo_streamer.get_latest_frame()
            

            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ret:
                continue
                
            frame_bytes = buffer.tobytes()

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            



        except Exception as e:
            print(f"[VIDEO_FEED] Error in frame generator: {e}")


            time.sleep(1)

@app.route('/video_feed')
def video_feed():
    """Video streaming route."""
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')



@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('dashboard.html')

@app.route('/api/status')
def get_status():
    """Get current system status"""
    with state_lock:
        return jsonify(system_state)

@app.route('/snapshots/<filename>')
def get_snapshot(filename):
    """Serve snapshot images"""
    return send_from_directory(SNAPSHOT_FOLDER, filename)

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    print("[WEBSOCKET] Client connected")
    emit('system_update', system_state)

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print("[WEBSOCKET] Client disconnected")

@socketio.on('mute_sound')
def handle_mute_sound():
    """Handle mute sound from dashboard"""
    print("[DASHBOARD] Mute sound received.")
    with state_lock:
        system_state['sound_muted'] = True
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
    emit('system_update', system_state, broadcast=True)

@socketio.on('yolo_detection_update')
def handle_yolo_detection_update(data):
    """Handle YOLO detection updates from YOLOStreamer."""
    global system_state
    with state_lock:
        if system_state['alert_active']:
            if data.get('person_detected', False):
                system_state['person_present'] = True
            if data.get('person_fallen_by_pose', False):
                system_state['person_fallen_by_pose'] = True
        else:

            system_state['person_present'] = data.get('person_detected', False)
            system_state['person_fallen_by_pose'] = data.get('person_fallen_by_pose', False)

        # 'person_moving' is explicitly cancelled as per user request.
        system_state['person_moving'] = False 
        

        system_state['motion_detected'] = system_state['person_fallen_by_pose']

    emit('system_update', system_state, broadcast=True)



def init_mqtt():
    """Initialize MQTT client"""
    global mqtt_client
    
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message
    
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
        print(f"[MQTT] Connecting to broker at {MQTT_BROKER}:{MQTT_PORT}")
        return True
    except Exception as e:
        print(f"[MQTT] Connection error: {e}")
        return False

def main():
    """Main application entry point"""
    print("=" * 60)
    print("Fall Detection System - Raspberry Pi")
    print("=" * 60)
    

    os.makedirs(SNAPSHOT_FOLDER, exist_ok=True)
    os.makedirs('logs', exist_ok=True)
    

    try:
        pygame.init()
        pygame.mixer.init()
        print("[INFO] Pygame mixer initialized for audio alerts.")
    except Exception as e:
        print(f"[ERROR] Failed to initialize pygame: {e}")

    

    if not init_camera():
        print("[WARNING] Failed to initialize camera! Continuing without camera feed.")
        # If camera fails, set picam2 to None so other parts can check for its availability
        global picam2
        picam2 = None
    

    global yolo_streamer
    try:
        print("[AI] Initializing YOLOStreamer...")
        yolo_streamer = YOLOStreamer(picam2, socketio, YOLO_MODEL_PATH)
        yolo_streamer.start()
        print("[AI] YOLOStreamer initialized and started successfully.")
    except Exception as e:
        print(f"[AI] Error initializing YOLOStreamer: {e}")
        # We can continue without the streamer, but AI detection won't work
        yolo_streamer = None


    if not init_mqtt():
        print("[ERROR] Failed to connect to MQTT broker!")
        return
    
    print(f"\n[INFO] System ready!")
    print(f"[INFO] Dashboard URL: http://{PI_IP}:{FLASK_PORT}")
    print(f"[INFO] MQTT Broker: {MQTT_BROKER}:{MQTT_PORT}")
    print("\n" + "=" * 60 + "\n")
    

    try:
        socketio.run(app, host='0.0.0.0', port=FLASK_PORT, debug=False)
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down...")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        if yolo_streamer:
            yolo_streamer.stop()
        if picam2:
            picam2.stop()

if __name__ == "__main__":
    main()