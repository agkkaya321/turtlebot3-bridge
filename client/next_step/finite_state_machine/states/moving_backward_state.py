from client.next_step.finite_state_machine.state import State

class MovingBackwardState(State):
    def __init__(self):
        super().__init__("moving_backward")

    def enter(self):
        print("Entering moving_backward state")

    def exit(self):
        print("Exiting moving_backward state")