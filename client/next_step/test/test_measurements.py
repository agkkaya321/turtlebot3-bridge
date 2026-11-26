"""Unit conversions, ground targets and shared configuration, without network access."""

from dataclasses import replace
import math
import unittest
from unittest.mock import patch

from next_step.finite_state_machine.fsm import FiniteStateMachine
from next_step.main import Main
from next_step.measurements import (
    Measurements, cm_to_m, mm_to_m, m_to_cm,
    degrees_to_radians, radians_to_degrees,
)


class MeasurementsTests(unittest.TestCase):
    def test_unit_conversions(self):
        self.assertEqual(cm_to_m(227.5), 2.275)
        self.assertEqual(mm_to_m(330), 0.33)
        self.assertAlmostEqual(m_to_cm(0.214), 21.4)
        self.assertAlmostEqual(degrees_to_radians(-90), -math.pi / 2)
        self.assertAlmostEqual(radians_to_degrees(math.pi), 180)
        for convert in (cm_to_m, mm_to_m, m_to_cm, degrees_to_radians, radians_to_degrees):
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(convert=convert, value=value), self.assertRaises(ValueError):
                    convert(value)

    def test_default_limits_match_documented_geometry(self):
        config = Measurements()
        near, far = config.target_distance_bounds_m()
        self.assertAlmostEqual(near, 1.825)
        self.assertAlmostEqual(far, 2.075)
        pitch, yaw = config.laser_angle_limits("left").to_degrees()
        self.assertAlmostEqual(pitch[0], -10.2261300812)
        self.assertAlmostEqual(pitch[1], -8.9726013562)
        self.assertAlmostEqual(yaw[0], -7.8001878842)
        self.assertAlmostEqual(yaw[1], -3.4473868519)
        right_pitch, right_yaw = config.laser_angle_limits("right").to_degrees()
        self.assertEqual(pitch, right_pitch)
        self.assertEqual(right_yaw, (-yaw[1], -yaw[0]))

    def test_rays_land_on_future_foot_positions_and_remain_within_limits(self):
        for config in (Measurements(), Measurements(laser_height_m=0.4, person_distance_m=2.5,
                                                    foot_spacing_m=(0.2, 0.4), step_length_m=(0.1, 0.5))):
            for foot, sign in (("left", -1), ("right", 1)):
                limits = config.laser_angle_limits(foot)
                for i in range(5):
                    step = config.step_length_m[0] + i / 4 * (config.step_length_m[1] - config.step_length_m[0])
                    for j in range(5):
                        spacing = config.foot_spacing_m[0] + j / 4 * (config.foot_spacing_m[1] - config.foot_spacing_m[0])
                        angles = config.laser_angles(foot, step, spacing)
                        distance = config.laser_height_m / math.tan(-angles.pitch_rad)
                        self.assertAlmostEqual(distance * math.cos(angles.yaw_rad), config.person_distance_m - step)
                        self.assertAlmostEqual(distance * math.sin(angles.yaw_rad), sign * spacing / 2)
                        self.assertLessEqual(limits.pitch_rad[0], angles.pitch_rad)
                        self.assertLessEqual(angles.pitch_rad, limits.pitch_rad[1])
                        self.assertLessEqual(limits.yaw_rad[0], angles.yaw_rad)
                        self.assertLessEqual(angles.yaw_rad, limits.yaw_rad[1])

    def test_invalid_dimensions_and_targets_are_rejected(self):
        for kwargs in ({"laser_height_m": 0}, {"person_distance_m": -1},
                       {"robot_height_m": math.nan}, {"person_height_m": math.inf},
                       {"foot_spacing_m": (0.5, 0.25)}, {"step_length_m": (0.2,)},
                       {"step_length_m": (0.2, 2.275)}, {"foot_spacing_m": (0, 0.5)},
                       {"step_length_m": (0.2, math.inf)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Measurements(**kwargs)
        config = Measurements()
        for args in (("unknown", .2, .25), ("left", .46, .25), ("left", .19, .25),
                     ("right", .2, .51), ("right", .2, .24), ("left", math.nan, .25)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                config.laser_angles(*args)

    @patch("builtins.print")
    def test_states_use_same_configuration_and_recalculate_after_replacement(self, _):
        robot = Main()
        fsm = FiniteStateMachine(robot)
        follow, left, right = (fsm.states[i] for i in (1, 3, 4))
        follow.distance_measurements.append(2.275)
        self.assertEqual(follow.adapt_speed(), 0)
        original = left.angles_for_step(0.3, 0.4)
        robot.measurements = replace(robot.measurements, person_distance_m=2.0, laser_height_m=0.4)
        for state in (follow, left, right):
            self.assertIs(state.measurements, robot.measurements)
        self.assertAlmostEqual(follow.adapt_speed(), 0.1375)
        updated = left.angles_for_step(0.3, 0.4)
        self.assertNotEqual(original, updated)
        self.assertLess(updated.pitch_rad, original.pitch_rad)
        self.assertEqual(right.angles_for_step(0.3, 0.4).yaw_rad, -updated.yaw_rad)
        self.assertEqual(left.angle_limits, robot.measurements.laser_angle_limits("left"))
        self.assertEqual(right.angle_limits, robot.measurements.laser_angle_limits("right"))
        self.assertEqual(robot.command, (0, 0))
        self.assertEqual(Main().measurements.person_distance_m, 2.275)


if __name__ == "__main__":
    unittest.main()
