"""Read the robot's HTTP JPEG stream without accessing the Mac webcam."""

import time

from robot import BridgeClient


class LiveStreamDecoder:
    def __init__(self, url="http://127.0.0.1:8000"):
        self.bridge = BridgeClient(url)
        self.sequence = 0
        self.timestamp_ms = -1

    def get_image(self):
        """Return (bgr_frame, timestamp_ms), or None when no new frame is available.

        The timestamp uses the Mac monotonic clock and marks reception, not
        camera exposure. A 204 response resets the cursor so acquisition
        can resume after the bridge restarts.
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
            raise ValueError("Invalid camera JPEG image.")
        self.sequence = sequence
        self.timestamp_ms = max(self.timestamp_ms + 1, time.monotonic_ns() // 1_000_000)
        return bgr_frame, self.timestamp_ms

    @staticmethod
    def bgr_to_rgb(bgr_frame):
        """Convert BGR (OpenCV) to RGB (MediaPipe)."""
        import cv2

        return cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
