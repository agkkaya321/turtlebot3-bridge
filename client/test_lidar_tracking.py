"""Target selection: synthetic scenes and centers provided in diagnostic logs.

Summarized centers cannot reproduce the original LiDAR rays: these tests
check candidate association, not extraction.
"""

import unittest
from unittest.mock import patch

from next_step.lidar import TargetTracker, select_target
from next_step.main import Main
from next_step.finite_state_machine.states.user_follow_state import UserFollowState
from test_user_follow import scan_at


def candidate(x, y):
    return {"center": (x, y), "points": 6, "width": 0.10, "accepted": True}


def pair(x, y=0):
    return [candidate(x, y - 0.15), candidate(x, y + 0.15)]


class SelectionTests(unittest.TestCase):
    def test_log_centers_choose_near_pair_despite_background_candidates(self):
        # Accepted candidates from three summaries in the user-provided logs.
        scenes = [
            ([(.419, .068), (.322, -1.984), (2.619, -1.011), (.361, -.062)],
             [1, 4], (.390, .003)),
            ([(.736, .064), (2.748, .725), (.142, -2.032), (.359, -1.975),
              (2.620, -.985), (.376, -.068)], [1, 6], (.556, -.002)),
            ([(.947, .037), (2.758, .728), (.174, -2.032), (.418, -1.950),
              (2.455, -1.392), (2.899, -.692), (.971, -.129)], [1, 7], (.959, -.046)),
        ]
        for centers, selected, target in scenes:
            with self.subTest(centers=centers):
                result = select_target([candidate(*center) for center in centers])
                self.assertEqual(result["selected_clusters"], selected)
                self.assertEqual(result["selection"], "nearest_pair")
                for actual, expected in zip(result["target"], target):
                    self.assertAlmostEqual(actual, expected)

    def test_incoherent_pair_is_not_averaged(self):
        for second in ((1, .7), (1.5, .2), (1.2, .02), (1, .05)):
            with self.subTest(second=second):
                result = select_target([candidate(1, 0), candidate(*second)])
                self.assertIsNone(result["target"])
                self.assertEqual(result["reason"], "no_coherent_pair")

    def test_pair_tie_is_rejected_independently_of_scan_order(self):
        clusters = pair(1, -.7) + pair(1, .7)
        for ordering in (clusters, list(reversed(clusters))):
            result = select_target(ordering)
            self.assertEqual(result["reason"], "ambiguous_target")
            self.assertIsNone(result["target"])
            self.assertEqual(result["selected_clusters"], [])

    def test_tracking_keeps_target_when_a_closer_pair_appears(self):
        clusters = pair(.6) + pair(1.5)
        self.assertAlmostEqual(select_target(clusters)["target"][0], .6)
        result = select_target(clusters, previous_target=(1.45, 0))
        self.assertEqual(result["selected_clusters"], [3, 4])
        self.assertEqual(result["selection"], "tracked_pair")

    def test_single_occluded_leg_is_associated_among_distractors(self):
        clusters = [candidate(.95, -.12), candidate(2.7, .7), candidate(.4, -1.95)]
        result = select_target(clusters, previous_target=(.96, -.04))
        self.assertEqual(result["selected_clusters"], [1])
        self.assertEqual(result["selection"], "tracked_leg")
        self.assertIsNone(select_target(clusters)["target"])

    def test_far_pair_and_singleton_do_not_replace_tracked_target(self):
        for clusters in (pair(2.5), [candidate(2.5, 0)]):
            self.assertEqual(select_target(clusters, (1, 0))["reason"], "target_lost")

    def test_two_equally_close_singletons_remain_ambiguous(self):
        # Two points with the same lateral coordinate do not form a pair.
        result = select_target([candidate(.8, 0), candidate(1.2, 0)], (1, 0))
        self.assertEqual(result["reason"], "ambiguous_target")


class TrackingTests(unittest.TestCase):
    def test_missing_scan_does_not_return_remembered_target_or_refresh_timeout(self):
        tracker = TargetTracker()
        first = tracker.update(scan_at(1), 0)
        self.assertIsNotNone(first["target"])
        self.assertIsNone(tracker.update(None, .2)["target"])
        self.assertEqual(tracker.last_seen, 0)
        self.assertIsNone(tracker.update(scan_at(2), .8)["target"])
        self.assertEqual(tracker.last_seen, 0)
        info = tracker.update(scan_at(2), 1.0)
        self.assertTrue(info["tracking_expired"])
        self.assertAlmostEqual(info["target"][0], 2)

    def test_brief_loss_recovers_same_target_without_waiting_for_timeout(self):
        tracker = TargetTracker()
        tracker.update(scan_at(1), 0)
        tracker.update(None, .1)
        info = tracker.update(scan_at(1.1), .2)
        self.assertEqual(info["selection"], "tracked_leg")
        self.assertFalse(info["tracking_expired"])
        tracker.reset()
        self.assertIsNone(tracker.target)
        self.assertIsNone(tracker.last_seen)

    def test_state_commands_from_selected_pair_with_multiple_candidates(self):
        robot = Main()
        state = UserFollowState(robot, debug=False)
        # One pair at 1 m and another at 2.5 m: the scan has four candidates.
        near, far = scan_at(1, ((-.2, -.1), (.1, .2))), scan_at(2.5, ((.6, .72), (.9, 1.02)))
        scan = {**near, "ranges": [a if a is not None else b
                                  for a, b in zip(near["ranges"], far["ranges"])]}
        robot._telemetry = {"sensors": {"scan": {"data": scan, "age_ms": 0}}}
        with patch.object(robot, "log") as log:
            state.debug = True
            state.loop()
        self.assertGreater(state.diagnostics["valid_clusters"], 2)
        self.assertEqual(state.diagnostics["selection"], "nearest_pair")
        self.assertEqual(robot.command, (-.1, 0))
        output = "\n".join(call.args[0] for call in log.call_args_list)
        self.assertEqual(log.call_count, 1)
        self.assertEqual(output, "Legs detected — distance: 1.00 m — adjusting: backward.")

    def test_reacquisition_after_long_pause_drops_old_distance_average(self):
        robot = Main()
        state = UserFollowState(robot, debug=False)
        for now, distance in ((0, 2), (2, 1)):
            robot.t = now
            robot._telemetry = {"sensors": {"scan": {"data": scan_at(distance), "age_ms": 0}}}
            state.loop()
        self.assertEqual(len(state.distance_measurements), 1)
        self.assertAlmostEqual(state.r_smooth, 1)
        self.assertEqual(robot.command, (-.1, 0))


if __name__ == "__main__":
    unittest.main()
