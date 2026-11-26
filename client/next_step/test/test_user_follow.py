"""Synthetic scans and local commands: no robot access."""

import math
import unittest
from unittest.mock import patch

from next_step.leg_detection.lidar import analyze_scan, cluster_width, extract_clusters, extract_target
from next_step.finite_state_machine.states.user_follow_state import UserFollowState
from next_step.main import Main
from next_step.measurements import Measurements


def scan_at(x, bands=((-0.06, 0.06),), angle_min=-math.pi):
    """Vertical segments at constant x, sampled by a LiDAR with 1° resolution."""
    ranges = []
    for index in range(360):
        theta = angle_min + math.radians(index)
        y = x * math.tan(theta)
        visible = math.cos(theta) > 0 and any(low < y < high for low, high in bands)
        ranges.append(x / math.cos(theta) if visible else None)
    return {"ranges": ranges, "angle_min": angle_min,
            "angle_increment": math.radians(1), "range_min": 0.12, "range_max": 3.5}


class ExtractionTests(unittest.TestCase):
    def test_polar_conversion_and_manhattan_distance(self):
        x, y = UserFollowState.polar_to_cartesian(2, math.pi / 2)
        self.assertAlmostEqual(x, 0)
        self.assertAlmostEqual(y, 2)
        self.assertEqual(UserFollowState.manhattan_distance(-2, -3), 5)

    def test_one_leg(self):
        x, y = extract_target(scan_at(1.5))
        self.assertAlmostEqual(x, 1.5)
        self.assertAlmostEqual(y, 0)

    def test_two_legs_have_equal_weight_despite_different_point_counts(self):
        scan = scan_at(1.5, ((-0.30, -0.15), (0.18, 0.26)))
        clusters = extract_clusters(scan)
        self.assertEqual(len(clusters), 2)
        self.assertNotEqual(len(clusters[0]), len(clusters[1]))
        x, y = extract_target(scan)
        centers_y = [sum(p[1] for p in cluster) / len(cluster) for cluster in clusters]
        self.assertAlmostEqual(x, 1.5)
        self.assertAlmostEqual(y, sum(centers_y) / 2)
        point_average = sum(p[1] for cluster in clusters for p in cluster) / sum(map(len, clusters))
        self.assertNotAlmostEqual(y, point_average)

    def test_roi_and_sensor_range_limits(self):
        for scan in (scan_at(3.1), scan_at(2.5, ((1.9, 2.1),)),
                     {**scan_at(1), "range_min": 1.2},
                     {**scan_at(1), "range_max": 0.9}):
            with self.subTest(scan=scan):
                self.assertIsNone(extract_target(scan))

    def test_lateral_legs_outside_old_roi_are_detected_on_both_sides(self):
        for band in ((0.65, 0.78), (-0.78, -0.65)):
            with self.subTest(band=band):
                target = extract_target(scan_at(1, (band,)))
                self.assertIsNotNone(target)
                self.assertAlmostEqual(target[0], 1)
                self.assertTrue(band[0] < target[1] < band[1])

    def test_roi_distance_is_euclidean_not_manhattan(self):
        target = extract_target(scan_at(1.5, ((1.72, 1.88),)))
        self.assertIsNotNone(target)
        self.assertLess(math.hypot(*target), 3)
        self.assertGreater(UserFollowState.manhattan_distance(*target), 3)

    def test_three_meter_radius_is_strict_and_rear_points_are_excluded(self):
        for distance in (2.999, 3.0, 3.001):
            scan = {"ranges": [distance] * 3, "angle_min": -0.02, "angle_increment": 0.02}
            with self.subTest(distance=distance):
                if distance < 3:
                    self.assertIsNotNone(extract_target(scan))
                else:
                    self.assertEqual(extract_clusters(scan), [])
        rear_scan = {"ranges": [1] * 3, "angle_min": math.pi - 0.03, "angle_increment": 0.03}
        self.assertEqual(extract_clusters(rear_scan), [])

    def test_point_outside_radius_interrupts_cluster(self):
        scan = {"ranges": [2.95, 3.01, 2.95], "angle_min": -0.02, "angle_increment": 0.02}
        self.assertEqual([len(cluster) for cluster in extract_clusters(scan)], [1, 1])
        self.assertIsNone(extract_target(scan))

    def test_invalid_returns_split_clusters(self):
        for invalid in (None, math.nan, math.inf, -math.inf, 0, -1, 4):
            scan = {"angle_min": -0.02, "angle_increment": 0.02,
                    "ranges": [1, invalid, 1], "range_max": 3.5}
            with self.subTest(invalid=invalid):
                self.assertEqual([len(c) for c in extract_clusters(scan)], [1, 1])
                self.assertIsNone(extract_target(scan))

    def test_distance_jump_splits_consecutive_rays(self):
        scan = {"angle_min": 0, "angle_increment": 0.01, "ranges": [1, 1, 1.3, 1.3]}
        self.assertEqual([len(c) for c in extract_clusters(scan)], [2, 2])

    def test_cluster_diameter_and_inclusive_width_bounds(self):
        self.assertEqual(cluster_width([(0, 0), (0.3, 0.4), (0, 0)]), 0.5)
        for width in (0.049, 0.05, 0.20, 0.201):
            cluster = [(1, 0), (1, width)]
            with self.subTest(width=width), patch("next_step.leg_detection.lidar.extract_clusters", return_value=[cluster]):
                if 0.05 <= width <= 0.20:
                    self.assertEqual(extract_target({}), (1, width / 2))
                else:
                    self.assertIsNone(extract_target({}))

    def test_wall_and_three_candidates_are_rejected(self):
        self.assertIsNone(extract_target(scan_at(1.5, ((-0.4, 0.4),))))
        self.assertIsNone(extract_target(scan_at(1.5, ((-0.4, -0.3), (-0.06, 0.06), (0.3, 0.4)))))

    def test_full_circle_seam_is_merged_for_either_scan_direction(self):
        scan = scan_at(1.5, angle_min=0)
        # The bridge rounds angles to six decimal places.
        scan["angle_increment"] = round(scan["angle_increment"], 6)
        self.assertEqual(len(extract_clusters(scan)), 1)
        target = extract_target(scan)
        self.assertIsNotNone(target)
        reverse = {**scan, "ranges": list(reversed(scan["ranges"])),
                   "angle_min": 359 * scan["angle_increment"],
                   "angle_increment": -scan["angle_increment"]}
        self.assertEqual(len(extract_clusters(reverse)), 1)
        for actual, expected in zip(extract_target(reverse), target):
            self.assertAlmostEqual(actual, expected)

    def test_partial_scan_is_not_joined_across_missing_rays(self):
        scan = {"angle_min": -0.02, "angle_increment": 0.02, "ranges": [1, None, 1]}
        self.assertEqual(len(extract_clusters(scan)), 2)

    def test_missing_empty_or_invalid_scan_geometry(self):
        for scan in (None, {}, {"ranges": []},
                     {"ranges": [1], "angle_min": math.nan, "angle_increment": 0.1},
                     {"ranges": [1], "angle_min": 0, "angle_increment": 0}):
            self.assertIsNone(extract_target(scan))

    def test_diagnostics_explain_accepted_and_rejected_clusters(self):
        scan = scan_at(1.5, ((-0.35, -0.34), (0.1, 0.22)))
        info = analyze_scan(scan)
        self.assertEqual(info["reason"], "target_detected")
        self.assertEqual(len(info["clusters"]), 2)
        self.assertEqual(info["valid_clusters"], 1)
        self.assertFalse(info["clusters"][0]["accepted"])
        self.assertEqual(info["clusters"][0]["width"], 0)
        self.assertEqual(info["target"], info["clusters"][1]["center"])
        self.assertEqual(info["roi_points"], sum(c["points"] for c in info["clusters"]))

    def test_diagnostic_reasons_for_missing_or_rejected_target(self):
        for scan, reason in (
            (None, "scan_missing"),
            ({"ranges": []}, "scan_empty"),
            (scan_at(3.1), "no_roi_points"),
            (scan_at(1.5, ((-0.4, 0.4),)), "no_valid_cluster"),
            (scan_at(1.5, ((-0.4, -0.3), (-0.06, 0.06), (0.3, 0.4))), "ambiguous_target"),
            ({"ranges": [1], "angle_min": 0, "angle_increment": 0}, "invalid_angles"),
        ):
            with self.subTest(reason=reason):
                info = analyze_scan(scan)
                self.assertEqual(info["reason"], reason)
                self.assertIsNone(info["target"])


class FollowingTests(unittest.TestCase):
    def setUp(self):
        # Real Robot.forward/backward/stop methods, without calling run().
        self.robot = Main(measurements=Measurements(person_distance_m=1.5))
        self.state = UserFollowState(self.robot, debug=False)

    def set_scan(self, scan, age_ms=0):
        self.robot._telemetry = {"sensors": {"scan": {"data": scan, "age_ms": age_ms}}}

    def test_default_distance_controls_real_commands_at_2275_m(self):
        self.robot = Main()
        self.state = UserFollowState(self.robot, debug=False)
        for distance, expected in ((2.175, -0.05), (2.275, 0), (2.375, 0.05)):
            with self.subTest(distance=distance):
                self.state._reset()
                self.set_scan(scan_at(distance))
                self.state.loop()
                self.assertAlmostEqual(self.robot.command[0], expected)
                self.assertEqual(self.robot.command[1], 0)

    def test_signed_speed_and_saturation_through_real_robot_commands(self):
        for distance, expected in ((2, 0.1), (1.6, 0.05), (1.4, -0.05), (0.5, -0.1)):
            with self.subTest(distance=distance):
                self.state._reset()
                self.set_scan(scan_at(distance))
                self.state.loop()
                self.assertAlmostEqual(self.robot.command[0], expected)
                self.assertEqual(self.robot.command[1], 0)

    def test_uses_configured_robot_speed_limit(self):
        self.set_scan(scan_at(2))
        self.robot._telemetry["limits"] = {"wheel_mps": 0.04}
        self.state.loop()
        self.assertEqual(self.robot.command, (0.04, 0))

    def test_zero_error_stops_and_direction_calls_use_positive_magnitudes(self):
        info = {**analyze_scan(scan_at(1.5)), "target": (1.5, 0), "tracking_expired": False}
        with patch.object(self.state.tracker, "update", return_value=info):
            self.robot.forward(0.05)
            self.state.loop()
            self.assertEqual(self.robot.command, (0, 0))
        for distance, method in ((2, "forward"), (0.5, "backward")):
            self.state._reset()
            self.set_scan(scan_at(distance))
            with patch.object(self.robot, method) as movement:
                self.state.loop()
            movement.assert_called_once_with(0.1)

    def test_partial_window_and_eviction_after_100_cycles(self):
        self.set_scan(scan_at(2))
        self.state.loop()
        self.assertAlmostEqual(self.state.adapt_speed(), 0.25)
        self.set_scan(scan_at(1.8))
        self.state.loop()
        self.assertAlmostEqual(self.state.adapt_speed(), 0.20)
        for _ in range(99):
            self.state.loop()
        self.assertEqual(len(self.state.distance_measurements), 100)
        self.assertAlmostEqual(self.state.adapt_speed(), 0.15)
        self.assertAlmostEqual(self.state.compute_sliding_window(range(101)), 50.5)

    def test_loss_staleness_and_ambiguity_stop_and_reset_before_reacquisition(self):
        failures = [(None, 0), (scan_at(1), 501), (scan_at(3.1), 0),
                    (scan_at(2, ((-0.4, -0.3), (-0.06, 0.06), (0.3, 0.4))), 0)]
        for scan, age_ms in failures:
            with self.subTest(age_ms=age_ms, scan=scan):
                self.state._reset()
                self.robot.t = 0
                self.set_scan(scan_at(2))
                self.state.loop()
                self.assertGreater(self.robot.command[0], 0)
                self.set_scan(scan, age_ms)
                self.state.loop()
                self.assertEqual(self.robot.command, (0, 0))
                self.assertEqual(len(self.state.distance_measurements), 0)
                self.assertIsNone(self.state.target)
                self.assertEqual(self.state.adapt_speed(), 0)
                self.set_scan(scan_at(1))
                self.robot.t = 0.1
                self.state.loop()
                self.assertEqual(self.robot.command, (0, 0))  # Reject a 1 m jump.
                self.robot.t = 1.1
                self.state.loop()
                self.assertEqual(self.robot.command, (-0.1, 0))

    @patch("builtins.print")
    def test_enter_exit_and_independent_buffers(self, _):
        self.set_scan(scan_at(2))
        self.state.loop()
        other = UserFollowState(self.robot)
        self.assertEqual(len(other.distance_measurements), 0)
        for action in (self.state.exit, self.state.enter):
            self.state.loop()
            action()
            self.assertEqual(self.robot.command, (0, 0))
            self.assertFalse(self.state.distance_measurements)
            self.assertIsNone(self.state.target)
            self.assertIsNone(self.state.tracker.target)

    def test_debug_reports_current_values_and_is_rate_limited(self):
        self.state.debug = True
        self.set_scan(scan_at(2))
        with patch.object(self.robot, "log") as log, patch(
                "next_step.leg_detection.lidar.extract_clusters", wraps=extract_clusters) as clusters:
            self.state.loop()
            output = "\n".join(call.args[0] for call in log.call_args_list)
            self.assertEqual(output, "Legs detected — distance: 2.00 m — adjusting: forward.")
            self.assertEqual(log.call_count, 1)
            count = log.call_count
            self.robot.t = 0.5
            self.state.loop()
            self.assertEqual(log.call_count, count)
            self.robot.t = 1.0
            self.state.loop()
            self.assertEqual(log.call_count, count * 2)
            self.assertEqual(clusters.call_count, 3)  # No second analysis pass for logging.

    def test_debug_stale_scan_clears_previous_values(self):
        self.state.debug = True
        with patch.object(self.robot, "log") as log:
            self.set_scan(scan_at(2))
            self.state.loop()
            self.set_scan(scan_at(2), age_ms=501)
            self.robot.t = 1
            self.state.loop()
            output = log.call_args.args[0]
        self.assertEqual(output, "Legs not detected — stopped.")
        self.assertEqual(self.state.diagnostics["reason"], "scan_stale")
        self.assertIsNone(self.state.r_smooth)
        self.assertEqual(self.state.raw_speed, 0)

    def test_disabled_debug_is_silent_and_dry_run_is_explicit(self):
        self.set_scan(scan_at(2))
        with patch.object(self.robot, "log") as log:
            self.state.loop()
            log.assert_not_called()
            self.state.debug = True
            self.robot.dry_run = True
            self.state.loop()
            self.assertIn("dry run, no movement", log.call_args_list[0].args[0])


if __name__ == "__main__":
    unittest.main()
