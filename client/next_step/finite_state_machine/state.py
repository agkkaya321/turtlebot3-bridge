from ..measurements import DEFAULT_MEASUREMENTS


class State:
    def __init__(self, name, robot=None):
        self.name = name
        self.robot = robot

    @property
    def measurements(self):
        """Shared configuration; states also see replacement configurations."""
        return getattr(self.robot, "measurements", DEFAULT_MEASUREMENTS)

    def enter(self):
        if getattr(self.robot, "verbose", True):
            print(f"Entering state: {self.name}")

    def loop(self):
        """
        Loops in the state when the robot is active.
        Read values and update the robot's topic with self.robot.
        """

    def exit(self):
        if getattr(self.robot, "verbose", True):
            print(f"Exiting state: {self.name}")

    def get_name(self):
        return self.name
