from ..state import State
from ...posture_analysis.posture_detector import PostureDetector

class PostureCheckingState(State):
    def __init__(self, robot=None):
        super().__init__("posture_checking", robot)
        self.detector = None
        self._last_message = None

    def enter(self):
        self.robot.stop()
        self._last_message = None

        self.detector = PostureDetector(
            self.robot.bridge.url,
            ui_url=getattr(self.robot, "ui_url", "http://127.0.0.1:8080"),
            model_path=getattr(self.robot, "pose_model", None),
        )

        self.detector.start()

    def loop(self):
        self.robot.stop()

        status = self.detector.status()

        message = None

        if not status["present"]:
            if status["fresh"]:
                message = "The user must be on the image."
            else:
                message = status["error"] or "Waiting for an image."

        if message is not None and message != self._last_message:
            print(message, flush=True)

        self._last_message = message

    def exit(self):
        self.robot.stop()
        if self.detector is not None:
            self.detector.close()
            self.detector = None
