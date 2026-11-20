"""Dependency-free Python client. Run it on your computer."""

import json
import math
import sys
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

# Burger manufacturer speed limit; the bridge enforces its own limit (MAX_SPEED_MPS).
BURGER_MAX_SPEED = 0.22
SOUNDS = {"off": 0, "on": 1, "low_battery": 2, "error": 3, "button1": 4, "button2": 5}


def _number(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite.")
    return value


class BridgeError(RuntimeError):
    """Bridge error response; code is the HTTP status (400 command rejected, 503 not ready…)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class BridgeClient:
    """Direct access to the bridge HTTP API. To implement behavior, see tb3.Robot."""

    def __init__(self, url="http://127.0.0.1:8000"):
        self.url = url.rstrip("/")
        self._linear = 0.0
        self._angular = 0.0
        self._http = build_opener(ProxyHandler({}))

    # --- HTTP requests -------------------------------------------------

    def _get(self, path, timeout=0.3):
        with self._http.open(self.url + path, timeout=timeout) as response:
            return json.load(response)

    def _post(self, path, payload, timeout=0.3):
        request = Request(
            self.url + path,
            data=json.dumps(payload, allow_nan=False).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._http.open(request, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise BridgeError(error.code, f"Bridge HTTP {error.code} : {detail}") from error

    # --- Status -----------------------------------------------------------

    def ready(self):
        """Return exactly 'ready' or 'not ready'. Raise if the bridge is unreachable."""
        with self._http.open(self.url + "/ready", timeout=0.3) as response:
            state = response.read().decode("utf-8").strip()
        if state not in ("ready", "not ready"):
            raise RuntimeError(f"Unexpected bridge status: {state!r}")
        return state

    def status(self):
        """Details: status, reason, and supervisor action."""
        return self._get("/status")

    def wait_until_ready(self, timeout=60.0):
        """Wait for the robot without sending motion commands."""
        timeout = float(timeout)
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("Timeout must be finite and nonnegative.")
        deadline = time.monotonic() + timeout
        while True:
            if self.ready() == "ready":
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("The robot is still not ready.")
            time.sleep(min(0.2, remaining))

    # --- Sensors -------------------------------------------------------

    def camera_frame(self, after=0):
        """Return (JPEG bytes, frame_nb) or None after 2.5 s without a new frame.

        Use a separate BridgeClient in a worker: this long poll must not block
        the robot's control loop. No OpenCV dependency in the transport layer.
        """
        with self._http.open(self.url + f"/camera/frame?after={int(after)}", timeout=4.0) as response:
            if response.status == 204:
                return None
            if response.headers.get_content_type() != "image/jpeg":
                raise ValueError("The camera did not return a JPEG.")
            return response.read(), int(response.headers["X-Frame-Seq"])

    def telemetry(self):
        """All sensors: odom, sensor_state, battery, imu, scan, magnetic_field,
        joint_states, plus watched topics, services, and limits."""
        return self._get("/telemetry", timeout=1.0)

    def sensor(self, name, max_age=1.0):
        """Sensor data, or None if missing or older than max_age (seconds)."""
        entry = self.telemetry()["sensors"].get(name)
        if entry is None or entry["age_ms"] > max_age * 1000:
            return None
        return entry["data"]

    def pose(self):
        """Odometry: {'x', 'y', 'yaw_rad', 'linear_mps', 'angular_rad_s'}."""
        return self.sensor("odom")

    def battery(self):
        return self.sensor("battery")

    def scan(self):
        """LiDAR: ranges (m, None if invalid), angle_min, angle_increment."""
        return self.sensor("scan")

    def front_distance(self, half_angle_deg=15):
        """Shortest valid distance ahead of the robot, or None."""
        data = self.scan()
        if data is None:
            return None
        half = math.radians(half_angle_deg)
        best = None
        for index, distance in enumerate(data["ranges"]):
            if distance is None:
                continue
            angle = data["angle_min"] + index * data["angle_increment"]
            angle = math.atan2(math.sin(angle), math.cos(angle))
            if abs(angle) <= half and (best is None or distance < best):
                best = distance
        return best

    def topics(self):
        return self._get("/topics", timeout=1.0)["topics"]

    def watch(self, topic):
        """Watch any topic (e.g. an ESP32 sensor) in telemetry()['watched']."""
        return self._post("/watch", {"topic": topic}, timeout=4.0)

    def unwatch(self, topic):
        return self._post("/unwatch", {"topic": topic}, timeout=4.0)

    # --- Robot services ----------------------------------------------

    def motor_power(self, enabled):
        """Enable (True) or disable (False) motor torque."""
        return self._post("/motor_power", {"enabled": bool(enabled)}, timeout=4.0)

    def sound(self, value=1):
        """Play an OpenCR sound: 0..5 or a name from SOUNDS."""
        value = SOUNDS.get(value, value)
        return self._post("/sound", {"value": int(value)}, timeout=4.0)

    def reset(self):
        """Driver reset service (odometry / IMU); stops the robot first."""
        return self._post("/reset", {}, timeout=4.0)

    # --- Movement ------------------------------------------------------

    def velocity(self, linear, angular=0.0):
        """Forward speed in m/s and angular speed in rad/s (positive = turn left).

        Commands expire after 500 ms on the robot. Use wait() to renew a
        command for a duration, or call velocity() again.
        """
        linear = _number(linear, "Speed")
        angular = _number(angular, "Angular speed")
        if abs(linear) > BURGER_MAX_SPEED:
            raise ValueError(f"Speed must be between -{BURGER_MAX_SPEED} and {BURGER_MAX_SPEED} m/s.")
        # On failure, a later wait() must not resume the previous speed.
        self._linear = self._angular = 0.0
        feedback = self._post("/velocity", {"linear_mps": linear, "angular_rad_s": angular})
        if feedback.get("published_to_ros") is not True:
            raise RuntimeError(f"ROS publication not confirmed: {feedback}")
        self._linear, self._angular = linear, angular
        return feedback

    def forward(self, speed):
        """Speed in m/s: positive = forward, negative = backward, zero = stop."""
        return self.velocity(speed, 0.0)

    def turn(self, angular):
        """Turn in place in rad/s (positive = left)."""
        return self.velocity(0.0, angular)

    def wheels(self, left, right):
        """Speed of each wheel in m/s."""
        left = _number(left, "Left wheel speed")
        right = _number(right, "Right wheel speed")
        return self.velocity((left + right) / 2.0, (right - left) / 0.160)

    def stop(self):
        """Immediately request zero velocity."""
        return self.velocity(0.0, 0.0)

    def wait(self, seconds):
        """Renew the command for this duration, without a background thread."""
        seconds = float(seconds)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Duration must be finite and nonnegative.")
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.velocity(self._linear, self._angular)
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.10, remaining))

    def __enter__(self):
        self.stop()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self.stop()
        except Exception as error:
            if exc_type is None:
                raise
            # Preserve the original error, even if the network connection is already lost.
            print(f"Stop not confirmed: {error}", file=sys.stderr)
        return False
