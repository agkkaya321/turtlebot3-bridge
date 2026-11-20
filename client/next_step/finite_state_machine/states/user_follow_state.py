from collections import deque
import math
from time import perf_counter

from ...leg_detection.lidar import TargetTracker, polar_to_cartesian
from ..state import State

DISTANCE_THRESHOLD = 1.5  # Meters.
SLIDING_WINDOW_SIZE = 100
REACTIVITY_CONSTANT = 0.5
SCAN_MAX_AGE = 0.5  # Seconds.
DEBUG = True
DEBUG_INTERVAL = 1.0  # Seconds between log messages.


class UserFollowState(State):
    def __init__(self, robot=None, debug=DEBUG):
        super().__init__("user_follow", robot)
        self.distance_measurements = deque(maxlen=SLIDING_WINDOW_SIZE)
        self.tracker = TargetTracker()
        self.target = None
        self.r = None
        self.r_smooth = None
        self.raw_speed = 0.0
        self.speed = 0.0
        self.diagnostics = None
        self.debug = debug
        self._last_debug = -float("inf")

    def _reset(self, keep_tracking=False):
        if not keep_tracking:
            self.tracker.reset()
        self.distance_measurements.clear()
        self.target = None
        self.r = None
        self.r_smooth = None
        self.raw_speed = 0.0
        self.speed = 0.0
        if self.robot is not None:
            self.robot.stop()

    def enter(self):
        self._reset()
        self.diagnostics = None
        self._last_debug = -float("inf")
        super().enter()

    def loop(self):

        began = perf_counter()
        scan = self.robot.scan(max_age=SCAN_MAX_AGE)
        self.diagnostics = self.tracker.update(scan, self.robot.t)

        if self.diagnostics["tracking_expired"]:
            self.distance_measurements.clear()

        if scan is None:
            entry = self.robot.telemetry().get("sensors", {}).get("scan", {})
            if entry.get("data") is not None:
                self.diagnostics["reason"] = "scan_stale"

        self.target = self.diagnostics["target"]

        if self.target is None:
            self._reset(keep_tracking=True)
            self._debug(began)
            return

        self.r = self.manhattan_distance(*self.target)
        self.distance_measurements.append(self.r)
        self.r_smooth = self.compute_sliding_window(self.distance_measurements)

        limit = self.robot.max_wheel_speed()

        self.raw_speed = self.adapt_speed()
        self.speed = max(-limit, min(limit, self.raw_speed))

        if self.speed > 0:
            self.robot.forward(self.speed)
        elif self.speed < 0:
            self.robot.backward(-self.speed)
        else:
            self.robot.stop()
        self._debug(began)

    def _debug(self, began):
        """Log one tracking summary per second; keep details in memory."""
        self.diagnostics["processing_ms"] = (perf_counter() - began) * 1000
        if not self.debug or self.robot.t - self._last_debug < DEBUG_INTERVAL:
            return
        self._last_debug = self.robot.t
        mode = " [dry run, no movement]" if self.robot.dry_run else ""
        if self.target is None:
            self.robot.log(f"Legs not detected — stopped.{mode}")
            return
        if math.isclose(self.speed, 0, abs_tol=1e-9):
            action = "holding position"
        else:
            action = "adjusting: forward" if self.speed > 0 else "adjusting: backward"
        self.robot.log(f"Legs detected — distance: {math.hypot(*self.target):.2f} m — {action}.{mode}")

    def exit(self):
        self._reset()
        self.diagnostics = None
        super().exit()

    @staticmethod
    def manhattan_distance(x, y):
        return abs(x) + abs(y)

    @staticmethod
    def polar_to_cartesian(r, theta):
        return polar_to_cartesian(r, theta)

    @staticmethod
    def compute_sliding_window(array) -> float:
        """Average the latest values; use a partial window during startup."""
        values = list(array)[-SLIDING_WINDOW_SIZE:]
        return sum(values) / len(values) if values else 0.0

    def adapt_speed(self):
        """Signed speed before clamping; no measurements means stop."""
        if not self.distance_measurements:
            return 0.0

        r_smooth = self.compute_sliding_window(self.distance_measurements)

        return REACTIVITY_CONSTANT * (r_smooth - DISTANCE_THRESHOLD)
