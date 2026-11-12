"""Program the TurtleBot3 like an Arduino: setup() once, then loop() repeatedly.

    from tb3 import Robot

    class Avance(Robot):
        def loop(self):
            self.forward(0.05)

    Avance().run()

Each cycle (10 per second by default), run() reads all sensors in one request,
calls loop(), and sends the motion command to the bridge. A command stays
active until replaced: run() renews it each cycle, and the bridge stops the
robot if no command arrives for 500 ms.
Full guide: docs/GUIDE_ROBOT.md.
"""

import abc
import argparse
import math
import signal
import sys
import threading
import time

from robot import SOUNDS, BridgeClient, BridgeError, _number

WHEEL_SEPARATION = 0.160
# Default bridge limit (MAX_SPEED_MPS), used until /telemetry provides it.
DEFAULT_WHEEL_LIMIT = 0.10
# Network outage tolerated before aborting (s); the robot stops after 500 ms.
OFFLINE_LIMIT = 2.0


def _interrupt(signum, frame):
    raise KeyboardInterrupt


class Robot(abc.ABC):
    """Base class: subclass it and implement loop() (required) and setup() (optional)."""

    verbose = True  # Technical diagnostics; errors are always displayed.

    def __init__(self, url="http://127.0.0.1:8000", hz=10, dry_run=False):
        hz = _number(hz, "hz")
        if not 1 <= hz <= 50:
            raise ValueError("hz must be between 1 and 50.")
        self.bridge = BridgeClient(url)
        self.hz = hz
        self.dry_run = bool(dry_run)
        self.t = 0.0          # Seconds since the first cycle.
        self.tick = 0         # Current cycle number.
        self.state = None     # Current state, changed by goto().
        self._state_since = 0.0
        self._start = None
        self._telemetry = {}
        self._fetched_at = None
        self._command = (0.0, 0.0)
        self._shown = None
        self._every = {}
        self._finished = False
        self._paused = False
        self._offline_since = {}   # By request type: read or send.
        self._last_overrun = -math.inf
        self.cycle_timings_ms = {}

    # --- Override in subclasses ------------------------------------

    def setup(self):
        """Called once before the first cycle. Optional."""

    @abc.abstractmethod
    def loop(self):
        """Called each cycle: read sensors and choose a command. Do not block."""

    # --- Execution --------------------------------------------------------

    @classmethod
    def main(cls):
        """Run from the command line: --url, --hz, --dry-run."""
        parser = argparse.ArgumentParser(description=cls.__doc__)
        parser.add_argument("--url", default="http://127.0.0.1:8000")
        parser.add_argument("--hz", type=float, default=10)
        parser.add_argument("--dry-run", action="store_true",
                            help="Read sensors and display commands without moving")
        args = parser.parse_args()
        cls(url=args.url, hz=args.hz, dry_run=args.dry_run).run()

    def run(self):
        """Main loop. Ctrl+C, finish(), or an error stops the robot."""
        name = type(self).__name__
        mode = " (dry run: no movement)" if self.dry_run else ""
        if self.verbose:
            print(f"{name} : bridge {self.bridge.url}, {self.hz:g} Hz{mode}")
        if threading.current_thread() is threading.main_thread():
            # kill / terminal closure: perform the same clean shutdown as Ctrl+C.
            signal.signal(signal.SIGTERM, _interrupt)
        try:
            if not self.dry_run:
                self._wait_ready()
            self._refresh()
            self._start = time.monotonic()
            self.setup()
            self._start = time.monotonic()
            self._state_since = 0.0
            period = 1.0 / self.hz
            next_tick = self._start
            while not self._finished:
                began = time.monotonic()
                self.t = began - self._start
                self.cycle_timings_ms = {"HTTP_read": 0.0, "ready": 0.0,
                                         "loop": 0.0, "HTTP_send": 0.0}
                phase = time.perf_counter()
                self._network(self._refresh)
                self.cycle_timings_ms["HTTP_read"] = (time.perf_counter() - phase) * 1000
                if self._paused:
                    phase = time.perf_counter()
                    self._check_resume()
                    self.cycle_timings_ms["ready"] = (time.perf_counter() - phase) * 1000
                if not self._paused:
                    phase = time.perf_counter()
                    self.loop()
                    self.cycle_timings_ms["loop"] = (time.perf_counter() - phase) * 1000
                    phase = time.perf_counter()
                    self._network(self._send)
                    self.cycle_timings_ms["HTTP_send"] = (time.perf_counter() - phase) * 1000
                self.tick += 1
                self._pace(began, period)
                next_tick += period
                delay = next_tick - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_tick = time.monotonic()
        except KeyboardInterrupt:
            print("\nStop requested (Ctrl+C).")
        finally:
            self._halt()

    def finish(self):
        """End the program after this cycle and stop the robot."""
        self._finished = True

    def log(self, *values):
        """Print a message prefixed with elapsed time."""
        print(f"[{self.t:7.2f} s]", *values)

    # --- Movement (command sent at the end of the cycle) ---------------------

    def velocity(self, linear, angular=0.0):
        """Forward speed in m/s (negative = backward) and rad/s (positive = left)."""
        linear = _number(linear, "Speed")
        angular = _number(angular, "Angular speed")
        half = angular * WHEEL_SEPARATION / 2.0
        left, right = linear - half, linear + half
        limit = self.max_wheel_speed()
        if max(abs(left), abs(right)) > limit + 1e-9:
            raise ValueError(
                f"Command exceeds speed limit: wheels {left:+.3f} / {right:+.3f} m/s, "
                f"limit ±{limit:.2f} m/s per wheel (MAX_SPEED_MPS in robot.env).")
        self._command = (linear, angular)

    def forward(self, speed):
        """Move straight ahead at speed m/s (negative = backward)."""
        self.velocity(speed, 0.0)

    def backward(self, speed):
        """Move straight backward at speed m/s."""
        self.velocity(-abs(_number(speed, "Speed")), 0.0)

    def turn(self, angular):
        """Turn in place at angular rad/s (positive = left)."""
        self.velocity(0.0, angular)

    def wheels(self, left, right):
        """Speed of each wheel in m/s."""
        left = _number(left, "Left wheel speed")
        right = _number(right, "Right wheel speed")
        self.velocity((left + right) / 2.0, (right - left) / WHEEL_SEPARATION)

    def stop(self):
        """Set a zero-velocity command."""
        self._command = (0.0, 0.0)

    @property
    def command(self):
        """Current command: (m/s, rad/s)."""
        return self._command

    def max_wheel_speed(self):
        """Maximum wheel speed accepted by the bridge (m/s)."""
        return self._telemetry.get("limits", {}).get("wheel_mps") or DEFAULT_WHEEL_LIMIT

    def max_turn_speed(self):
        """Maximum in-place angular speed (rad/s)."""
        return 2.0 * self.max_wheel_speed() / WHEEL_SEPARATION

    # --- Sensors (snapshot taken at the start of the cycle) --------------------------

    def _age_ms(self, age_ms):
        late = (time.monotonic() - self._fetched_at) * 1000 if self._fetched_at else 0.0
        return age_ms + late

    def sensor(self, name, max_age=1.0):
        """Raw bridge sensor data, or None if missing or older than max_age seconds."""
        entry = self._telemetry.get("sensors", {}).get(name)
        if entry is None or self._age_ms(entry["age_ms"]) > max_age * 1000:
            return None
        return entry["data"]

    # LiDAR
    def scan(self, max_age=1.0):
        """Scan: ranges (m, None if invalid), angle_min, angle_increment, range_min, range_max."""
        return self.sensor("scan", max_age)

    def _rays(self):
        """(angle in degrees within [-180, 180), distance) for each valid measurement."""
        data = self.scan()
        if data is None:
            return []
        rays = []
        for index, distance in enumerate(data["ranges"]):
            if distance is None:
                continue
            angle = data["angle_min"] + index * data["angle_increment"]
            rays.append((math.degrees(math.atan2(math.sin(angle), math.cos(angle))), distance))
        return rays

    def distance_at(self, angle_deg, half_angle_deg=5):
        """Shortest distance (m) around angle_deg (0 = forward, 90 = left), or None."""
        best = None
        for angle, distance in self._rays():
            gap = (angle - angle_deg + 180) % 360 - 180
            if abs(gap) <= half_angle_deg and (best is None or distance < best):
                best = distance
        return best

    def front_distance(self, half_angle_deg=15):
        """Closest obstacle ahead (±half_angle_deg), in meters, or None."""
        return self.distance_at(0, half_angle_deg)

    def closest_obstacle(self):
        """(distance in meters, angle in degrees) of the closest obstacle, or None."""
        rays = self._rays()
        if not rays:
            return None
        angle, distance = min(rays, key=lambda ray: ray[1])
        return distance, angle

    # Odometry
    def pose(self, max_age=1.0):
        """Estimated pose: x, y (m), yaw_rad, linear_mps, angular_rad_s."""
        return self.sensor("odom", max_age)

    def heading_deg(self):
        """Odometry heading in degrees within [-180, 180], or None."""
        pose = self.pose()
        if pose is None or pose["yaw_rad"] is None:
            return None
        return math.degrees(pose["yaw_rad"])

    # IMU, magnetometer, wheels
    def imu(self, max_age=1.0):
        """yaw_rad, angular_velocity {x,y,z} (rad/s), linear_acceleration {x,y,z} (m/s²)."""
        return self.sensor("imu", max_age)

    def magnetic_field(self, max_age=1.0):
        """tesla {x, y, z}."""
        return self.sensor("magnetic_field", max_age)

    def joint_states(self, max_age=1.0):
        """name, position_rad, velocity_rad_s for both wheels."""
        return self.sensor("joint_states", max_age)

    # Battery
    def battery(self, max_age=1.0):
        """voltage_v, percentage (0..1 or None), current_a, present."""
        return self.sensor("battery", max_age)

    def battery_voltage(self):
        """Battery voltage in V, or None."""
        battery = self.battery()
        if battery and battery["voltage_v"] is not None:
            return battery["voltage_v"]
        state = self.sensor_state()
        return state["battery_v"] if state else None

    # OpenCR board
    def sensor_state(self, max_age=1.0):
        """bumper, cliff, sonar, illumination, led, button, torque, left_encoder,
        right_encoder, battery_v."""
        return self.sensor("sensor_state", max_age)

    def _state_field(self, field):
        state = self.sensor_state()
        return None if state is None else state[field]

    def button(self):
        """OpenCR buttons (integer, 0 = none), or None."""
        return self._state_field("button")

    def bumper(self):
        """Bumper (integer, 0 = no contact), or None."""
        return self._state_field("bumper")

    def cliff(self):
        """Cliff sensor (raw value), or None."""
        return self._state_field("cliff")

    def sonar(self):
        """Sonar (raw value), or None."""
        return self._state_field("sonar")

    def illumination(self):
        """Light sensor (raw value), or None."""
        return self._state_field("illumination")

    def torque(self):
        """True if the motors are powered, or None."""
        return self._state_field("torque")

    def encoders(self):
        """(left, right) encoder ticks, or None."""
        state = self.sensor_state()
        return None if state is None else (state["left_encoder"], state["right_encoder"])

    # Other topics (ESP32…)
    def watch(self, topic):
        """Start receiving a ROS topic (call in setup())."""
        return self.bridge.watch(topic)

    def unwatch(self, topic):
        return self.bridge.unwatch(topic)

    def watched(self, topic, max_age=1.0):
        """Latest message from a watched topic, or None if nothing is recent."""
        entry = self._telemetry.get("watched", {}).get(topic)
        if entry is None or entry["age_ms"] is None:
            return None
        if self._age_ms(entry["age_ms"]) > max_age * 1000:
            return None
        return entry["data"]

    def telemetry(self):
        """Full snapshot returned by the bridge at the start of the cycle."""
        return self._telemetry

    # --- Actions (immediate; may wait up to 3 seconds) ----------------------

    def sound(self, value="on"):
        """OpenCR sound: a name from SOUNDS or 0..5."""
        return self.bridge.sound(SOUNDS.get(value, value))

    def motor_power(self, enabled):
        """Enable (True) or disable (False) motor torque."""
        return self.bridge.motor_power(enabled)

    def reset(self):
        """Reset odometry and the IMU (the robot stops)."""
        return self.bridge.reset()

    def status(self):
        """Bridge state: status, reason, ros_alive, supervisor."""
        return self.bridge.status()

    # --- Time and states ----------------------------------------------------

    def every(self, seconds, key=None):
        """True on the first call, then every `seconds` seconds (one timer per line)."""
        if key is None:
            caller = sys._getframe(1)
            key = (caller.f_code.co_filename, caller.f_lineno)
        last = self._every.get(key)
        if last is None or self.t - last >= seconds:
            self._every[key] = self.t
            return True
        return False

    def goto(self, state):
        """Switch to another state and reset state_time to zero."""
        if state != self.state:
            self.state = state
            self._state_since = self.t

    @property
    def state_time(self):
        """Seconds spent in the current state."""
        return self.t - self._state_since

    def after(self, seconds):
        """True if the current state has lasted at least `seconds` seconds."""
        return self.state_time >= seconds

    # --- Internals -----------------------------------------------------------

    def _refresh(self):
        self._telemetry = self.bridge.telemetry()
        self._fetched_at = time.monotonic()

    def _send(self):
        linear, angular = self._command
        if self.dry_run:
            if self.verbose and self._command != self._shown:
                self.log(f"[dry-run] command {linear:+.3f} m/s, {angular:+.3f} rad/s")
                self._shown = self._command
            return
        try:
            self.bridge.velocity(linear, angular)
        except BridgeError as error:
            if error.code != 503:
                raise
            self._pause(error)

    def _pause(self, error):
        # Like the bridge, never resume an old command after losing readiness.
        self._command = (0.0, 0.0)
        self._paused = True
        reason = error
        try:
            status = self.status()
            if status.get("status") != "ready":
                reason = status.get("reason")
        except Exception:
            pass
        self.log(f"Robot not ready ({reason}): paused, will resume automatically.")

    def _check_resume(self):
        try:
            ready = self.bridge.ready() == "ready"
        except OSError:
            return
        if ready:
            self._paused = False
            self.log("Robot ready: resuming.")

    def _network(self, action):
        """Execute a request while tolerating a short network outage."""
        kind = action.__name__
        try:
            action()
        except OSError as error:   # URLError, timeout, connection refused
            now = time.monotonic()
            since = self._offline_since.setdefault(kind, now)
            if since == now:
                self.log(f"Bridge unreachable ({error}): retrying…")
            elif now - since > OFFLINE_LIMIT:
                raise ConnectionError(
                    f"Bridge unreachable for {OFFLINE_LIMIT:g} s: tunnel closed or Wi-Fi disconnected? "
                    "(./start.sh must be running)") from error
            return
        if self._offline_since.pop(kind, None) is not None:
            self.log("Bridge reachable again.")

    def _pace(self, began, period):
        if not self.verbose:
            return
        spent = time.monotonic() - began
        if spent > period and began - self._last_overrun > 5.0:
            self._last_overrun = began
            details = ", ".join(f"{name}={ms:.1f} ms" for name, ms in self.cycle_timings_ms.items())
            self.log(f"Slow cycle: {spent * 1000:.0f} ms for a {period * 1000:.0f} ms budget "
                     f"({details}).")

    def _wait_ready(self):
        try:
            state = self.bridge.ready()
        except OSError as error:
            raise ConnectionError(
                f"Bridge unreachable at {self.bridge.url}: run ./start.sh first.") from error
        last_report = -math.inf
        while state != "ready":
            if time.monotonic() - last_report > 5.0:
                last_report = time.monotonic()
                print(f"Waiting for the robot: {self.status().get('reason')}")
            time.sleep(0.5)
            state = self.bridge.ready()

    def _halt(self):
        # No command could have been sent before the first cycle completed.
        if self.dry_run or self.tick == 0:
            return
        last = None
        for _ in range(3):
            try:
                self.bridge.stop()
                print("Robot stopped.")
                return
            except Exception as error:
                last = error
        print(f"Stop not confirmed ({last}): the bridge will stop the robot within 500 ms.",
              file=sys.stderr)
