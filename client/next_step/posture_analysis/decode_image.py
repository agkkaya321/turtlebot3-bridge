import time
import cv2
import mediapipe as mp

def stream_webcam(hand_landmarker: mp.tasks.vision.HandLandmarker, camera_index: int = 0):
    cap = cv2.VideoCapture(camera_index)
    try:
        while cap.isOpened():
            ok, bgr_frame = cap.read()
            if not ok:
                break
            rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
            timestamp_ms = time.monotonic_ns() // 1_000_000
            hand_landmarker.detect_async(mp_image, timestamp_ms)
    finally:
        cap.release()