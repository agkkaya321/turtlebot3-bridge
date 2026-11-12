"""Camera over the bridge's HTTP/SSH connection; standard library, no ROS.

Fetch frames outside the movement loop. JPEG decoding / posture analysis belongs
to a separate consumer; this module does not install a vision dependency.
"""

import json
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

try:
    from .robot import BridgeError
except ImportError:
    from robot import BridgeError

MAX_FRAME_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class CameraFrame:
    jpeg: bytes
    sequence: int
    age_ms: int
    stamp: str  # ROS acquisition timestamp, seconds.nanoseconds


class CameraClient:
    """Read-only camera API. Use the same URL as BridgeClient (including its port)."""

    def __init__(self, url="http://127.0.0.1:8000"):
        self.url = url.rstrip("/")
        self._http = build_opener(ProxyHandler({}))

    def status(self, timeout=1.0):
        with self._http.open(self.url + "/camera/status", timeout=timeout) as response:
            return json.load(response)

    def frame(self, timeout=1.0):
        """Return CameraFrame. Raise BridgeError on disabled, missing or stale camera.

        age_ms is the age at the bridge when responding, not including download
        time. sequence allows consumers to detect repeated frames.
        """
        try:
            with self._http.open(self.url + "/camera/frame.jpg", timeout=timeout) as response:
                if response.headers.get_content_type() != "image/jpeg":
                    raise ValueError("Expected a JPEG camera response")
                data = response.read(MAX_FRAME_BYTES + 1)
                if len(data) > MAX_FRAME_BYTES:
                    raise ValueError("Camera frame exceeds 2 MiB")
                if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
                    raise ValueError("Invalid JPEG camera frame")
                return CameraFrame(data, int(response.headers["X-Camera-Sequence"]),
                                   int(response.headers["X-Camera-Age-Ms"]),
                                   response.headers["X-Camera-Stamp"])
        except HTTPError as error:
            detail = error.read(4096).decode("utf-8", errors="replace")
            raise BridgeError(error.code, f"Camera HTTP {error.code}: {detail}") from error
