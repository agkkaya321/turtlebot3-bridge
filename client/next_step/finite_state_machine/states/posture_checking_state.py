from ..state import State

class PostureCheckingState(State):
    def __init__(self, robot=None):
        super().__init__("posture_checking", robot)

    def enter(self):
        print("Entering posture_checking state")

    def exit(self):
        print("Exiting posture_checking state")
