from client.next_step.finite_state_machine.state import State

class PostureCheckingState(State):
    def __init__(self):
        super().__init__("posture_checking")

    def enter(self):
        print("Entering posture_checking state")

    def exit(self):
        print("Exiting posture_checking state")