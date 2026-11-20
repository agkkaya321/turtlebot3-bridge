from ..state import State
from ...posture_analysis.posture_detector import PostureDetector
import time

class PostureCheckingState(State):
    def __init__(self, robot=None):
        super().__init__("posture_checking", robot)
        self.detector = None
        self._last_message = -float("inf")

    def enter(self):
        self.robot.stop()
        print("Analyse de posture : placez-vous devant la caméra (délai : 10 s).", flush=True)
        self._last_message = -float("inf")
        self.detector = PostureDetector(
            self.robot.bridge.url,
            ui_url=getattr(self.robot, "ui_url", "http://127.0.0.1:8080"),
            model_path=getattr(self.robot, "pose_model", None),
        )
        self.detector.start()

    def loop(self):
        self.robot.stop()
        status = self.detector.status()
        now = time.monotonic()
        if not status["present"] and now - self._last_message >= 1:
            if status["fresh"]:
                message = "La personne n'est pas sur l'image."
            else:
                message = status["error"] or "En attente d'une image analysée de la caméra."
            print(f"{message} Arrêt dans {status['remaining']:.0f} s sans détection.", flush=True)
            self._last_message = now
        if status["expired"]:
            print("Aucune personne détectée depuis 10 s : arrêt du programme NextStep.", flush=True)
            self.robot.finish()

    def exit(self):
        self.robot.stop()
        if self.detector is not None:
            self.detector.close()
            self.detector = None
