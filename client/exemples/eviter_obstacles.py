"""Move forward and turn left when an obstacle is less than 30 cm ahead."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from client.tb3 import Robot


class EviterObstacles(Robot):
    def setup(self):
        self.sound("on")

    def loop(self):
        devant = self.front_distance()
        if devant is None:
            self.stop()               # No recent LiDAR data: do not drive blind.
        elif devant < 0.30:
            self.turn(0.8)
        else:
            self.forward(0.08)
        if self.every(1):
            self.log(f"front: {devant} m")


if __name__ == "__main__":
    EviterObstacles.main()
