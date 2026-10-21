"""Tests locaux du client, sans réseau, ROS ou commande moteur."""
import io
import json
import math
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

from robot import BridgeClient


class RobotStatusTests(unittest.TestCase):
    def test_ready_and_not_ready_are_returned_verbatim(self):
        robot = BridgeClient()
        robot._http = Mock()
        for label in ("ready", "not ready"):
            robot._http.open.return_value = io.BytesIO(label.encode())
            self.assertEqual(robot.ready(), label)

    def test_status_includes_reason_and_supervisor(self):
        robot = BridgeClient()
        expected = {"status": "not ready", "reason": "Moteurs désactivés",
                    "supervisor": "Bringup supervisé actif", "ros_alive": True}
        robot._http = Mock()
        robot._http.open.return_value = io.BytesIO(json.dumps(expected).encode())
        self.assertEqual(robot.status(), expected)

    def test_unreachable_bridge_is_not_reported_as_a_robot_status(self):
        robot = BridgeClient()
        robot._http = Mock()
        robot._http.open.side_effect = URLError("Connexion refusée")
        with self.assertRaises(URLError):
            robot.ready()

    def test_unexpected_status_is_rejected(self):
        robot = BridgeClient()
        robot._http = Mock()
        robot._http.open.return_value = io.BytesIO(b"unknown")
        with self.assertRaises(RuntimeError):
            robot.ready()

    def test_waiting_for_ready_never_sends_motion(self):
        robot = BridgeClient()
        robot.ready = Mock(side_effect=["not ready", "ready"])
        robot.forward = Mock()
        with patch("robot.time.sleep"):
            robot.wait_until_ready()
        robot.forward.assert_not_called()
        self.assertEqual(robot.ready.call_count, 2)

    def test_ready_timeout(self):
        robot = BridgeClient()
        robot.ready = Mock(return_value="not ready")
        with self.assertRaises(TimeoutError):
            robot.wait_until_ready(timeout=0)

    def test_invalid_timeouts(self):
        robot = BridgeClient()
        for timeout in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                robot.wait_until_ready(timeout)


class RobotMotionTests(unittest.TestCase):
    def robot(self):
        robot = BridgeClient()
        robot._post = Mock(return_value={"published_to_ros": True})
        return robot

    def test_wheels_become_linear_and_angular(self):
        robot = self.robot()
        robot.wheels(-0.03, 0.05)
        path, payload = robot._post.call_args.args
        self.assertEqual(path, "/velocity")
        self.assertAlmostEqual(payload["linear_mps"], 0.01)
        self.assertAlmostEqual(payload["angular_rad_s"], 0.5)

    def test_wait_renews_the_last_command(self):
        robot = self.robot()
        robot.velocity(0.02, 0.3)
        robot._post.reset_mock()
        with patch("robot.time.sleep"), patch("robot.time.monotonic",
                                               side_effect=[0, 0, 0.1, 0.2, 1, 1]):
            robot.wait(0.5)
        for call in robot._post.call_args_list:
            self.assertEqual(call.args[1], {"linear_mps": 0.02, "angular_rad_s": 0.3})

    def test_failed_command_is_not_renewed(self):
        robot = self.robot()
        robot.velocity(0.02)
        robot._post.side_effect = RuntimeError("Bridge HTTP 503")
        with self.assertRaises(RuntimeError):
            robot.velocity(0.05)
        self.assertEqual((robot._linear, robot._angular), (0.0, 0.0))

    def test_invalid_speeds(self):
        robot = self.robot()
        for value in (True, float("nan"), 1.0):
            with self.assertRaises(ValueError):
                robot.forward(value)
        robot._post.assert_not_called()

    def test_front_distance_ignores_invalid_and_side_ranges(self):
        robot = BridgeClient()
        ranges = [None] * 360
        ranges[0], ranges[5], ranges[90], ranges[355] = None, 0.8, 0.2, 0.5
        robot.sensor = Mock(return_value={"ranges": ranges, "angle_min": 0.0,
                                          "angle_increment": math.radians(1)})
        self.assertEqual(robot.front_distance(15), 0.5)


if __name__ == "__main__":
    unittest.main()
