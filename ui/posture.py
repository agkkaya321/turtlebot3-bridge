"""Store the latest posture result in memory only, on the Mac."""

import base64
import math
import threading
import time


class PostureStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._packet = None
        self._received = 0

    def update(self, packet):
        if not isinstance(packet, dict):
            raise ValueError("Expected a JSON object.")
        if packet.get("stopped") is True:
            with self._lock:
                self._packet = None
            return
        timestamp = packet.get("timestamp_ms")
        if type(timestamp) is not int or timestamp < 0:
            raise ValueError("Invalid timestamp.")
        image = packet.get("image")
        if not isinstance(image, str) or len(image) > 700_000:
            raise ValueError("JPEG image is missing or too large.")
        try:
            jpeg = base64.b64decode(image, validate=True)
        except ValueError as error:
            raise ValueError("Invalid base64-encoded JPEG.") from error
        if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
            raise ValueError("Invalid JPEG.")
        poses = packet.get("poses")
        if not isinstance(poses, list) or len(poses) > 1:
            raise ValueError("At most one pose is accepted.")
        for pose in poses:
            if not isinstance(pose, list) or len(pose) != 33:
                raise ValueError("A pose must contain 33 landmarks.")
            for point in pose:
                if not isinstance(point, dict) or any(
                    type(point.get(key)) not in (float, int) or not math.isfinite(point[key])
                    for key in ("x", "y", "visibility")
                ):
                    raise ValueError("Invalid pose landmark.")
        with self._lock:
            self._packet = {"timestamp_ms": timestamp, "image": image, "poses": poses}
            self._received = time.monotonic()

    def snapshot(self):
        with self._lock:
            age = time.monotonic() - self._received
            # timestamp_ms also uses the Mac monotonic clock.
            if self._packet is not None:
                age = max(age, time.monotonic() - self._packet["timestamp_ms"] / 1000)
            if self._packet is None or age >= 3:
                self._packet = None
                return {"active": False, "poses": [], "image": None}
            return {**self._packet, "active": True, "age_ms": round(age * 1000)}
