from ..state import State

class LaserAimingRightState(State):
    def __init__(self, robot=None):
        super().__init__("laser_aiming_right", robot)

    def enter(self):
        print("Entering laser_aiming_right state")

    def exit(self):
        print("Exiting laser_aiming_right state")
