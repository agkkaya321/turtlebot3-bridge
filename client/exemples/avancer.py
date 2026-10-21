"""Avancer tout droit à 5 cm/s pendant 3 secondes."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tb3 import Robot


class Avancer(Robot):
    def loop(self):
        self.forward(-0.1)
        if self.t > 10:
            self.finish()


if __name__ == "__main__":
    Avancer.main()
