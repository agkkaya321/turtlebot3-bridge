import os
import sys
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from next_step.finite_state_machine.fsm import FiniteStateMachine
from next_step.measurements import Measurements
from tb3 import Robot


class Main(Robot):
    verbose = False  # Show the tracking summary without technical diagnostics.

    def __init__(self, *args, initial_state=2, ui_url="http://127.0.0.1:8080", pose_model=None,
                 measurements=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.measurements = Measurements() if measurements is None else measurements
        if not isinstance(self.measurements, Measurements):
            raise TypeError("measurements must be a Measurements instance.")
        self.initial_state = initial_state
        self.ui_url = ui_url
        self.pose_model = pose_model
        self.fsm = None

    def setup(self):
        self.fsm = FiniteStateMachine(self)
        self.fsm.transition(self.initial_state)

    def loop(self):
        self.fsm.loop()

    def user_follow_test(self):
        """Start LiDAR following; motors are enabled unless dry_run is set."""
        self.initial_state = 1
        self.run()

    def camera_test(self):
        """Start the camera and MediaPipe through the posture_checking state."""
        self.initial_state = 2
        self.run()

    def run(self):
        try:
            super().run()
        finally:
            # Robot.run() stops the motors before releasing the camera and MediaPipe.
            if self.fsm is not None:
                self.fsm.get_current_state().exit()

    @classmethod
    def main(cls):
        parser = argparse.ArgumentParser(description="NextStep: posture analysis or LiDAR following.")
        parser.add_argument("--url", default="http://127.0.0.1:8000", help="Bridge tunnel URL")
        parser.add_argument("--ui-url", default="http://127.0.0.1:8080", help="Local UI URL")
        parser.add_argument("--pose-model", help="Path to the MediaPipe .task model (or POSE_MODEL)")
        parser.add_argument("--state", choices=("posture_checking", "user_follow"), default="posture_checking")
        parser.add_argument("--hz", type=float, default=10)
        parser.add_argument("--dry-run", action="store_true", help="Disable motor commands")
        args = parser.parse_args()
        robot = cls(url=args.url, hz=args.hz, dry_run=args.dry_run, ui_url=args.ui_url,
                    pose_model=args.pose_model)
        if args.state == "user_follow":
            robot.user_follow_test()
        else:
            robot.camera_test()


if __name__ == "__main__":
    Main.main()
