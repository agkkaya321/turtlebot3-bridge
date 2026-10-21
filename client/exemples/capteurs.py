"""Afficher les capteurs chaque seconde, sans bouger. Ctrl+C pour quitter."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tb3 import Robot


class Capteurs(Robot):
    def loop(self):
        if not self.every(1):
            return
        self.log("pose", self.pose())
        self.log("devant", self.front_distance(), "m ; plus proche", self.closest_obstacle())
        self.log("batterie", self.battery_voltage(), "V ; moteurs", self.torque(),
                 "; bouton", self.button(), "; encodeurs", self.encoders())
        self.log("imu", self.imu())


if __name__ == "__main__":
    Capteurs.main()
