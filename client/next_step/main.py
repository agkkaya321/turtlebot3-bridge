import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from next_step.finite_state_machine.fsm import FiniteStateMachine
from tb3 import Robot


class Main(Robot):
    verbose = False  # Show the tracking summary without technical diagnostics.

    def setup(self):
        self.fsm = FiniteStateMachine(self)
        self.fsm.transition(1)  # LiDAR tracking: may command the motors.

        self.sound("error")

    def loop(self):
        self.fsm.loop()


if __name__ == "__main__":
    Main.main()
