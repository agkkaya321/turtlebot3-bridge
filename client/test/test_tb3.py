"""Local tb3.Robot tests, without networking, ROS, or motor commands."""
import math
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import tb3
from robot import BridgeError


def telemetry(age_ms=0, ranges=None):
    ranges = ranges if ranges is not None else [None] * 360
    return {
        "sensors": {
            "odom": {"age_ms": age_ms, "data": {"x": 0.1, "y": 0.0, "yaw_rad": math.pi / 2,
                                                "linear_mps": 0.0, "angular_rad_s": 0.0}},
            "scan": {"age_ms": age_ms, "data": {"ranges": ranges, "angle_min": 0.0,
                                                "angle_increment": math.radians(1)}},
            "sensor_state": {"age_ms": age_ms, "data": {
                "bumper": 0, "cliff": 0.0, "sonar": 0.0, "illumination": 0.0, "led": 0,
                "button": 1, "torque": True, "left_encoder": 10, "right_encoder": 12,
                "battery_v": 11.9}},
            "battery": {"age_ms": age_ms, "data": {"voltage_v": None, "percentage": None,
                                                   "current_a": None, "present": True}},
        },
        "watched": {"/esp32/lux": {"type": "std_msgs/msg/Float32", "age_ms": 100,
                                   "data": {"data": 42.0}},
                    "/vide": {"type": "std_msgs/msg/Float32", "age_ms": None, "data": None}},
        "limits": {"wheel_mps": 0.1, "angular_rad_s": 1.25},
    }


class FakeBridge:
    url = "http://fake"

    def __init__(self):
        self.sent = []
        self.stops = 0
        self.ready_answers = []
        self.velocity_errors = []
        self.data = telemetry()

    def ready(self):
        return self.ready_answers.pop(0) if self.ready_answers else "ready"

    def status(self):
        return {"status": "not ready", "reason": "Motors disabled"}

    def telemetry(self):
        return self.data

    def velocity(self, linear, angular):
        if self.velocity_errors:
            raise self.velocity_errors.pop(0)
        self.sent.append((linear, angular))

    def stop(self):
        self.stops += 1


def make(cls, ticks=None, **kwargs):
    robot = cls(**kwargs)
    robot.bridge = FakeBridge()
    if ticks is not None:
        original = robot.loop

        def loop():
            original()
            if robot.tick + 1 >= ticks:
                robot.finish()
        robot.loop = loop
    return robot


class Forward(tb3.Robot):
    def loop(self):
        self.forward(0.05)


@patch("tb3.time.sleep")
@patch("builtins.print")
class RunTests(unittest.TestCase):
    def test_http_error_at_startup_reports_wrong_endpoint_without_moving(self, *_):
        robot = make(Forward, ticks=1)
        error = HTTPError(robot.bridge.url + "/ready", 404, "Not Found", {}, None)
        with patch.object(robot.bridge, "ready", side_effect=error), patch.object(robot, "setup") as setup:
            with self.assertRaises(ConnectionError) as raised:
                robot.run()
        message = str(raised.exception)
        self.assertIn("HTTP 404 from http://fake/ready", message)
        self.assertIn("--url", message)
        self.assertNotIn("unreachable", message)
        setup.assert_not_called()
        self.assertEqual(robot.bridge.sent, [])
        self.assertEqual(robot.bridge.stops, 0)

    def test_unreachable_at_startup_reports_tunnel_url(self, *_):
        robot = make(Forward, ticks=1)
        with patch.object(robot.bridge, "ready", side_effect=URLError("Connection refused")):
            with self.assertRaisesRegex(ConnectionError, "Bridge unreachable.*--url"):
                robot.run()
        self.assertEqual(robot.bridge.sent, [])

    def test_cycle_timings_separate_read_loop_and_send(self, *_):
        robot = make(Forward, ticks=1)
        with patch("tb3.time.perf_counter", side_effect=[0, 0.01, 0.01, 0.03, 0.03, 0.06]):
            robot.run()
        self.assertAlmostEqual(robot.cycle_timings_ms["HTTP_read"], 10)
        self.assertAlmostEqual(robot.cycle_timings_ms["loop"], 20)
        self.assertAlmostEqual(robot.cycle_timings_ms["HTTP_send"], 30)
        self.assertEqual(robot.cycle_timings_ms["ready"], 0)

    def test_slow_cycle_log_includes_timings_and_stays_rate_limited(self, *_):
        robot = Forward()
        robot.cycle_timings_ms = {"HTTP_read": 65, "loop": 2, "HTTP_send": 53}
        with patch.object(robot, "log") as log, patch(
                "tb3.time.monotonic", side_effect=[0.12, 0.14, 6.2]):
            robot._pace(0, 0.1)
            robot._pace(0.01, 0.1)
            robot._pace(6, 0.1)
        self.assertEqual(log.call_count, 2)
        message = log.call_args_list[0].args[0]
        self.assertIn("120 ms for a 100 ms budget", message)
        self.assertIn("HTTP_read=65.0 ms", message)
        self.assertIn("loop=2.0 ms", message)
        self.assertIn("HTTP_send=53.0 ms", message)

    def test_loop_is_mandatory(self, *_):
        class NoLoop(tb3.Robot):
            pass
        with self.assertRaises(TypeError):
            NoLoop()

    def test_command_is_sent_every_tick_then_robot_stops(self, *_):
        robot = make(Forward, ticks=3)
        robot.run()
        self.assertEqual(robot.bridge.sent, [(0.05, 0.0)] * 3)
        self.assertEqual(robot.bridge.stops, 1)

    def test_command_set_once_persists(self, *_):
        class Once(tb3.Robot):
            def setup(self):
                self.turn(0.5)

            def loop(self):
                pass
        robot = make(Once, ticks=4)
        robot.run()
        self.assertEqual(robot.bridge.sent, [(0.0, 0.5)] * 4)

    def test_error_in_loop_stops_robot(self, *_):
        class Crash(tb3.Robot):
            def loop(self):
                self.forward(0.05)
                if self.tick == 2:
                    raise ZeroDivisionError
        robot = make(Crash)
        with self.assertRaises(ZeroDivisionError):
            robot.run()
        self.assertEqual(robot.bridge.stops, 1)

    def test_ctrl_c_stops_robot(self, *_):
        class Interrupt(tb3.Robot):
            def loop(self):
                self.forward(0.05)
                if self.tick == 1:
                    raise KeyboardInterrupt
        robot = make(Interrupt)
        robot.run()
        self.assertEqual(robot.bridge.stops, 1)

    def test_not_ready_pauses_and_drops_old_command(self, *_):
        calls = []

        class Count(tb3.Robot):
            def setup(self):
                self.forward(0.05)

            def loop(self):
                calls.append(self.tick)
                if self.tick >= 4:
                    self.finish()
        robot = make(Count)
        robot.bridge.velocity_errors = [BridgeError(503, "not ready")]
        robot.bridge.ready_answers = ["ready", "not ready", "ready"]
        robot.run()
        # Cycle 0 rejected → pause; cycle 1 still not ready; resume on cycle 2.
        self.assertEqual(calls, [0, 2, 3, 4])
        self.assertEqual(robot.bridge.sent, [(0.0, 0.0)] * 3)

    def test_refused_command_is_an_error(self, *_):
        robot = make(Forward)
        robot.bridge.velocity_errors = [BridgeError(400, "trop rapide")]
        with self.assertRaises(BridgeError):
            robot.run()

    def test_short_network_loss_is_tolerated(self, *_):
        robot = make(Forward, ticks=3)
        robot.bridge.velocity_errors = [URLError("coupure")]
        robot.run()
        self.assertEqual(len(robot.bridge.sent), 2)

    def test_long_network_loss_ends_program(self, *_):
        robot = make(Forward)
        robot.bridge.velocity_errors = [URLError("coupure")] * 100
        with patch("tb3.time.monotonic", side_effect=[float(i) for i in range(1000)]):
            with self.assertRaises(ConnectionError):
                robot.run()

    def test_dry_run_never_moves(self, *_):
        robot = make(Forward, ticks=3, dry_run=True)
        robot.bridge.ready_answers = ["not ready"] * 10
        robot.run()
        self.assertEqual(robot.bridge.sent, [])
        self.assertEqual(robot.bridge.stops, 0)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.robot = make(Forward)
        self.robot._refresh()

    def test_wheels_become_linear_and_angular(self):
        self.robot.wheels(-0.03, 0.05)
        linear, angular = self.robot.command
        self.assertAlmostEqual(linear, 0.01)
        self.assertAlmostEqual(angular, 0.5)

    def test_wheel_limit_from_bridge(self):
        self.robot.turn(self.robot.max_turn_speed())
        for bad in (lambda: self.robot.forward(0.11), lambda: self.robot.turn(1.3),
                    lambda: self.robot.forward(float("nan")), lambda: self.robot.forward(True)):
            with self.assertRaises(ValueError):
                bad()

    def test_backward(self):
        self.robot.backward(0.05)
        self.assertEqual(self.robot.command, (-0.05, 0.0))


class SensorTests(unittest.TestCase):
    def robot(self, **kwargs):
        robot = make(Forward)
        robot.bridge.data = telemetry(**kwargs)
        robot._refresh()
        return robot

    def test_old_data_is_ignored(self):
        robot = self.robot(age_ms=1500)
        self.assertIsNone(robot.pose())
        self.assertIsNotNone(robot.pose(max_age=2))

    def test_lidar_helpers(self):
        ranges = [None] * 360
        ranges[3], ranges[90], ranges[350], ranges[180] = 0.8, 0.2, 0.5, 1.5
        robot = self.robot(ranges=ranges)
        self.assertEqual(robot.front_distance(), 0.5)
        self.assertEqual(robot.distance_at(90), 0.2)
        self.assertEqual(robot.distance_at(-90), None)
        self.assertEqual(robot.distance_at(180), 1.5)
        self.assertEqual(robot.distance_at(-180), 1.5)
        distance, angle = robot.closest_obstacle()
        self.assertEqual(distance, 0.2)
        self.assertAlmostEqual(angle, 90)

    def test_no_scan(self):
        robot = self.robot()
        self.assertIsNone(robot.front_distance())
        self.assertIsNone(robot.closest_obstacle())

    def test_opencr_and_battery(self):
        robot = self.robot()
        self.assertEqual(robot.button(), 1)
        self.assertTrue(robot.torque())
        self.assertEqual(robot.encoders(), (10, 12))
        self.assertEqual(robot.battery_voltage(), 11.9)
        self.assertAlmostEqual(robot.heading_deg(), 90)

    def test_watched_topics(self):
        robot = self.robot()
        self.assertEqual(robot.watched("/esp32/lux"), {"data": 42.0})
        self.assertIsNone(robot.watched("/vide"))
        self.assertIsNone(robot.watched("/inconnu"))


class TimeTests(unittest.TestCase):
    def test_every_and_states(self):
        robot = make(Forward)
        fired = []
        for step in range(12):
            robot.t = step * 0.5
            if robot.every(2):
                fired.append(robot.t)
        self.assertEqual(fired, [0.0, 2.0, 4.0])

        robot.t = 10.0
        robot.goto("tourne")
        robot.t = 11.0
        self.assertFalse(robot.after(1.5))
        robot.t = 11.5
        self.assertTrue(robot.after(1.5))
        robot.goto("tourne")              # Same state: elapsed time keeps increasing.
        self.assertEqual(robot.state_time, 1.5)


if __name__ == "__main__":
    unittest.main()
