from ..state import State

class LaserAimingLeftState(State):
    def __init__(self, robot=None):
        super().__init__("laser_aiming_left", robot)

    def enter(self):
        print("Entering laser_aiming_left state")

    def exit(self):
        print("Exiting laser_aiming_left state")
