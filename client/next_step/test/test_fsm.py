"""NextStep FSM lifecycle, without network access or a real robot."""

import unittest
from unittest.mock import Mock, patch

from next_step.finite_state_machine.fsm import FiniteStateMachine
from next_step.finite_state_machine.state import State
from next_step.main import Main


class RecordingState(State):
    def __init__(self, name, events):
        super().__init__(name)
        self.events = events

    def enter(self):
        self.events.append((self.name, "enter"))

    def loop(self):
        self.events.append((self.name, "loop"))

    def exit(self):
        self.events.append((self.name, "exit"))


@patch("builtins.print")
class FiniteStateMachineTests(unittest.TestCase):
    def test_loop_repeats_only_for_active_state_between_enter_and_exit(self, _):
        fsm = FiniteStateMachine(object())
        events = []
        first = RecordingState("first", events)
        second = RecordingState("second", events)
        fsm.states.update({1: first, 2: second})

        fsm.transition(1)
        fsm.loop()
        fsm.loop()
        fsm.transition(2)
        fsm.loop()

        self.assertEqual(events, [
            ("first", "enter"),
            ("first", "loop"),
            ("first", "loop"),
            ("first", "exit"),
            ("second", "enter"),
            ("second", "loop"),
        ])
        self.assertIs(fsm.get_current_state(), second)

    def test_states_and_robot_context_are_independent_between_machines(self, _):
        robot_a, robot_b = Mock(), Mock()
        first = FiniteStateMachine(robot_a)
        second = FiniteStateMachine(robot_b)
        for state_id in first.states:
            self.assertIsNot(first.states[state_id], second.states[state_id])
            self.assertIs(first.states[state_id].robot, robot_a)
            self.assertIs(second.states[state_id].robot, robot_b)
        first.transition(1)
        self.assertEqual(second.get_current_state().get_name(), "initial")

    def test_initial_state_enters_once_and_supports_default_loop(self, _):
        with patch.object(State, "enter") as enter:
            fsm = FiniteStateMachine(object())
            fsm.loop()
            fsm.loop()
        enter.assert_called_once_with()
        self.assertIs(fsm.get_current_state(), fsm.states[0])

    def test_unknown_transition_preserves_active_state(self, _):
        fsm = FiniteStateMachine(object())
        events = []
        fsm.states[1] = RecordingState("active", events)
        fsm.transition(1)
        fsm.transition(999)
        fsm.loop()
        self.assertEqual(events, [("active", "enter"), ("active", "loop")])

    def test_main_dispatches_each_cycle_to_the_current_state(self, _):
        robot = Main()
        robot.bridge = Mock()
        with patch("next_step.finite_state_machine.states.posture_checking_state.PostureDetector") as detector:
            robot.setup()
        self.assertIs(robot.fsm.get_current_state(), robot.fsm.states[2])
        detector.return_value.start.assert_called_once()
        with patch.object(robot.fsm.states[2], "loop") as posture_loop:
            robot.loop()
            robot.loop()
            robot.fsm.transition(0)
            robot.loop()
        self.assertEqual(posture_loop.call_count, 2)
        detector.return_value.close.assert_called_once()
        self.assertEqual(robot.command, (0, 0))

    def test_lidar_can_still_be_selected_explicitly(self, _):
        robot = Main(initial_state=1)
        robot.setup()
        self.assertIs(robot.fsm.get_current_state(), robot.fsm.states[1])


if __name__ == "__main__":
    unittest.main()
