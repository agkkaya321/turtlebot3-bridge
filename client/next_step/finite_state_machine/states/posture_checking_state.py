from ..state import State
from ...posture_analysis.posture_detector import PostureDetector

class PostureCheckingState(State):
    def __init__(self, robot=None):
        super().__init__("posture_checking", robot)
        self.detector = None
        self._last_message = None

    def enter(self):
        # At the state entrance, ensure that the robot is immobile
        self.robot.stop()
        self._last_message = None

        # Initiate the posture detector
        self.detector = PostureDetector(
            self.robot.bridge.url,
            ui_url=getattr(self.robot, "ui_url", "http://127.0.0.1:8080"),
            model_path=getattr(self.robot, "pose_model", None),
        )

        # and start it...
        self.detector.start()

    def loop(self):

        status = self.detector.status() # Dictionary with Present, fresh, error
        message = None

        if not status["present"]:
            if status["fresh"]:
                message = "The user must be on the image."
            else:
                message = status["error"] or "Waiting for an image."

        # print debug log if there's an error message
        if message is not None and message != self._last_message:
            print(message, flush=True)

        self._last_message = message

    def exit(self):
        # On exit, we stop the robot for now just to test
        self.robot.stop()
        # We stop the detector for now, but it may be reused later to optimize the memory
        if self.detector is not None:
            self.detector.close()
            self.detector = None
