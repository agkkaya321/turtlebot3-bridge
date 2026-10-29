from client.next_step.finite_state_machine.states.laser_aiming_left_state import LaserAimingLeftState
from client.next_step.finite_state_machine.states.laser_aiming_right_state import LaserAimingRightState
from client.next_step.finite_state_machine.states.moving_backward_state import MovingBackwardState
from client.next_step.finite_state_machine.states.posture_checking_state import PostureCheckingState
from state import State

states = {
    0 : State("initial"),
    1 : PostureCheckingState(),
    2 : MovingBackwardState(),
    3 : LaserAimingLeftState(),
    4 : LaserAimingRightState(),
}

class FiniteStateMachine:
    def __init__(self):
        self.current_state = states[0]
        self.states = states

    def transition(self, new_state):
        if new_state in self.states:
            self.current_state.exit()
            self.current_state = new_state
            self.current_state.enter()

    def get_current_state(self):
        return self.current_state

