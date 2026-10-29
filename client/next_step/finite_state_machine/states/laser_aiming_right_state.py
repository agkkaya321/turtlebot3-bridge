from client.next_step.finite_state_machine.state import State

class LaserAimingRightState(State):
    def __init__(self):
        super().__init__("laser_aiming_right")

    def enter(self):
        print("Entering laser_aiming_right state")

    def exit(self):
        print("Exiting laser_aiming_right state")