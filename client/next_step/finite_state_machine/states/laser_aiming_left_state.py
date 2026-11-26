from ..state import State

class LaserAimingLeftState(State):
    def __init__(self, robot=None):
        super().__init__("laser_aiming_left", robot)

    @property
    def angle_limits(self):
        return self.measurements.laser_angle_limits("left")

    def angles_for_step(self, step_length_m, foot_spacing_m):
        """Calculate angles in radians without commanding the hardware."""
        return self.measurements.laser_angles("left", step_length_m, foot_spacing_m)

    def enter(self):
        print("Entering laser_aiming_left state")

    def exit(self):
        print("Exiting laser_aiming_left state")
