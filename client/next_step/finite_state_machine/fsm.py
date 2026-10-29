from state import State

states = {
    0 : State("initial"),
    1 : State("posture_checking"),
    2 : State("moving_backward"),
    3 : State("laser_aiming_left"),
    4 : State("laser_aiming_right"),
    5 : State("calibrating_laser"),
    6 : State("calibrating_robot_pos")
}

class FiniteStateMachine:
    def __init__(self):
        self.current_state = states[0]
        self.states = states

    def transition(self, new_state):
        if new_state in self.states:
            self.current_state = new_state

    def get_current_state(self):
        return self.current_state

