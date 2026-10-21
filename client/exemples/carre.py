"""Parcourir un carré de 40 cm avec des états : avancer, tourner, recommencer 4 fois."""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tb3 import Robot

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
            # Durée théorique d'un quart de tour ; l'odométrie (heading_deg) est plus précise.
            if self.after((math.pi / 2) / ROTATION):
                self.cotes += 1
                self.log(f"côté {self.cotes} terminé")
                if self.cotes == 4:
                    self.finish()
                self.goto("avance")


if __name__ == "__main__":
    Carre.main()
