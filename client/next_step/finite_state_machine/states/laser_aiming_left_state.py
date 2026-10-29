from client.next_step.finite_state_machine.state import State

class LaserAimingLeftState(State):
    def __init__(self):
        super().__init__("laser_aiming_left")

    def enter(self):
        print("Entering laser_aiming_left state")

    def exit(self):
        print("Exiting laser_aiming_left state")