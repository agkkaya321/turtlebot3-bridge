from ..state import State

class LaserAimingRightState(State):
    def __init__(self, robot=None):
        super().__init__("laser_aiming_right", robot)

    @property
    def angle_limits(self):
        return self.measurements.laser_angle_limits("right")

    def angles_for_step(self, step_length_m, foot_spacing_m):
        """Calculate angles in radians without commanding the hardware."""
        return self.measurements.laser_angles("right", step_length_m, foot_spacing_m)

    def enter(self):
        print("Entering laser_aiming_right state")

    def exit(self):
        print("Exiting laser_aiming_right state")
