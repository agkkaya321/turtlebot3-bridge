from client.robot import BridgeClient
from client.tb3 import Robot

class Main(Robot):
    def __init__(self):
        super().__init__()
        self.robot = BridgeClient()

    def setup(self):
        self.robot.sound("button1")

    def loop(self):
        pass
