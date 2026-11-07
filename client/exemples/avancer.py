"""Move straight ahead at 5 cm/s for 3 seconds."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from client.tb3 import Robot


class Avancer(Robot):
    def loop(self):
        self.forward(-0.1)
        if self.t > 10:
            self.finish()


if __name__ == "__main__":
    Avancer.main()
