"""Display sensor readings every second without moving. Press Ctrl+C to exit."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from client.tb3 import Robot


class Capteurs(Robot):
    def loop(self):
        if not self.every(1):
            return
        self.log("pose", self.pose())
        self.log("front", self.front_distance(), "m; closest", self.closest_obstacle())
        self.log("battery", self.battery_voltage(), "V; motors", self.torque(),
                 "; button", self.button(), "; encoders", self.encoders())
        self.log("imu", self.imu())


if __name__ == "__main__":
    Capteurs.main()
