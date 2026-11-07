"""Drive a 40 cm square using states: move forward, turn, and repeat four times."""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from client.tb3 import Robot

COTE = 0.40      # m
VITESSE = 0.08   # m/s
ROTATION = 0.8   # rad/s


class Carre(Robot):
    def setup(self):
        self.cotes = 0
        self.goto("avance")

    def loop(self):
        if self.state == "avance":
            self.forward(VITESSE)
            if self.after(COTE / VITESSE):
                self.goto("tourne")
        elif self.state == "tourne":
            self.turn(ROTATION)
            # Theoretical quarter-turn duration; odometry (heading_deg) is more accurate.
            if self.after((math.pi / 2) / ROTATION):
                self.cotes += 1
                self.log(f"side {self.cotes} completed")
                if self.cotes == 4:
                    self.finish()
                self.goto("avance")


if __name__ == "__main__":
    Carre.main()
