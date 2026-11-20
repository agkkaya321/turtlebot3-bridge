import os
import sys
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from next_step.finite_state_machine.fsm import FiniteStateMachine
from tb3 import Robot


class Main(Robot):
    verbose = False  # Show the tracking summary without technical diagnostics.

    def __init__(self, *args, initial_state=2, ui_url="http://127.0.0.1:8080", pose_model=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial_state = initial_state
        self.ui_url = ui_url
        self.pose_model = pose_model
        self.fsm = None

    def setup(self):
        self.fsm = FiniteStateMachine(self)
        self.fsm.transition(self.initial_state)

    def loop(self):
        self.fsm.loop()

    def run(self):
        try:
            super().run()
        finally:
            # Robot.run() arrête les moteurs avant de libérer caméra / MediaPipe.
            if self.fsm is not None:
                self.fsm.get_current_state().exit()

    @classmethod
    def main(cls):
        parser = argparse.ArgumentParser(description="NextStep : analyse de posture ou suivi LiDAR.")
        parser.add_argument("--url", default="http://127.0.0.1:8000", help="URL du tunnel du bridge")
        parser.add_argument("--ui-url", default="http://127.0.0.1:8080", help="URL locale de l'interface")
        parser.add_argument("--pose-model", help="Chemin du modèle MediaPipe .task (ou POSE_MODEL)")
        parser.add_argument("--state", choices=("posture_checking", "user_follow"), default="posture_checking")
        parser.add_argument("--hz", type=float, default=10)
        parser.add_argument("--dry-run", action="store_true", help="Inhiber les commandes moteurs")
        args = parser.parse_args()
        cls(url=args.url, hz=args.hz, dry_run=args.dry_run, ui_url=args.ui_url,
            pose_model=args.pose_model, initial_state=2 if args.state == "posture_checking" else 1).run()


if __name__ == "__main__":
    Main.main()
