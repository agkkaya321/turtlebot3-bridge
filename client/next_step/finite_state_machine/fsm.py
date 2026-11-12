from .states.laser_aiming_left_state import LaserAimingLeftState
from .states.laser_aiming_right_state import LaserAimingRightState
from .states.user_follow_state import UserFollowState
from .states.posture_checking_state import PostureCheckingState
from .state import State


class FiniteStateMachine:
    def __init__(self, robot):
        self.robot = robot
        self.states = {
            0: State("initial", robot),
            1: UserFollowState(robot),
            2: PostureCheckingState(robot),
            3: LaserAimingLeftState(robot),
            4: LaserAimingRightState(robot),
        }
        self.current_state = self.states[0]
        self.current_state.enter()

    def loop(self):
        """Run one cycle of the current state at the Robot.loop() frequency."""
        self.current_state.loop()

    def transition(self, new_state):
        if new_state in self.states:
            self.current_state.exit()
            self.current_state = self.states[new_state]
            self.current_state.enter()

    def get_current_state(self):
        return self.current_state

