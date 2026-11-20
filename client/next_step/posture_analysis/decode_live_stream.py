"""Acquisition du flux JPEG HTTP du robot, sans accès à la webcam du Mac."""

import time

from robot import BridgeClient


class LiveStreamDecoder:
    def __init__(self, url="http://127.0.0.1:8000"):
        self.bridge = BridgeClient(url)
        self.sequence = 0
        self.timestamp_ms = -1

    def get_image(self):
        """Obtenir (bgr_frame, timestamp_ms), ou None sans nouvelle image.

        L'horodatage est monotone sur le Mac ; il indique la réception, pas
        l'heure d'exposition de la caméra. Un 204 réinitialise le curseur pour
        permettre la reprise après un redémarrage du bridge.
        """
        import cv2
        import numpy as np

        frame = self.bridge.camera_frame(self.sequence)
        if frame is None:
            self.sequence = 0
            return None
        jpeg, sequence = frame
        bgr_frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if bgr_frame is None:
            raise ValueError("Image JPEG de la caméra invalide.")
        self.sequence = sequence
        self.timestamp_ms = max(self.timestamp_ms + 1, time.monotonic_ns() // 1_000_000)
        return bgr_frame, self.timestamp_ms

    @staticmethod
    def bgr_to_rgb(bgr_frame):
        """Convertir BGR (OpenCV) en RGB (MediaPipe)."""
        import cv2

        return cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
