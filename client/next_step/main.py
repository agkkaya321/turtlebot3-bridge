import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from client.tb3 import Robot


class Main(Robot):
    def setup(self):
        self.sound("error")

    def loop(self):
        self.sound("low_battery")
        pass


if __name__ == "__main__":
    Main.main()