"""MediaPipe LIVE_STREAM sur le Mac ; acquisition et publication hors de la FSM."""

import base64
import os
from pathlib import Path
import threading
import time

from robot import BridgeClient
from .decode_live_stream import LiveStreamDecoder

DEFAULT_MODEL = Path(__file__).with_name("pose_landmarker_lite.task")


class PosePresence:
    """Horloge indépendante de MediaPipe, testable sans caméra ni réseau."""

    def __init__(self, now, timeout=10.0):
        self.timeout = timeout
        self.last_seen = now
        self.last_result = None
        self.present = False

    def observe(self, present, captured_at):
        # Un ancien résultat asynchrone ne doit pas prolonger le délai.
        if self.last_result is not None and captured_at <= self.last_result:
            return
        self.last_result = captured_at
        self.present = bool(present)
        if present:
            self.last_seen = max(self.last_seen, captured_at)

    def status(self, now):
        fresh = self.last_result is not None and now - self.last_result < 3.0
        return {
            "present": self.present and fresh,
            "fresh": fresh,
            "remaining": max(0.0, self.timeout - (now - self.last_seen)),
            "expired": now - self.last_seen >= self.timeout,
        }


class PostureDetector:
    def __init__(self, bridge_url, ui_url="http://127.0.0.1:8080", model_path=None):
        self.stream = LiveStreamDecoder(bridge_url)
        self.ui = BridgeClient(ui_url)
        self.model_path = Path(model_path or os.environ.get("POSE_MODEL", DEFAULT_MODEL)).expanduser()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._pending = None
        self._error = None
        self._presence = None
        self._landmarker = None

    def start(self):
        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"Modèle MediaPipe absent : {self.model_path}. "
                "Voir docs/POSTURE.md pour installer le modèle et les dépendances.")
        try:
            import cv2
            import mediapipe as mp
        except ImportError as error:
            raise RuntimeError("Installer les dépendances de client/next_step/posture_analysis/requirements.txt") from error
        self.cv2, self.mp = cv2, mp
        self._stop.clear()
        self._pending = self._error = None
        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(self.model_path)),
            running_mode=mp.tasks.vision.RunningMode.LIVE_STREAM,
            num_poses=1,
            result_callback=self._on_result,
        )
        self._landmarker = mp.tasks.vision.PoseLandmarker.create_from_options(options)
        self._presence = PosePresence(time.monotonic())
        self._thread = threading.Thread(target=self._run, name="posture-camera", daemon=True)
        self._thread.start()

    def _on_result(self, result, output_image, timestamp_ms):
        if self._stop.is_set():
            return
        try:
            poses = [[{"x": float(p.x), "y": float(p.y),
                       "visibility": float(p.visibility if p.visibility is not None else 1.0)}
                      for p in pose] for pose in result.pose_landmarks]
            # Publier l'image EXACTE du callback, même si MediaPipe saute des frames.
            bgr = self.cv2.cvtColor(output_image.numpy_view(), self.cv2.COLOR_RGB2BGR)
            ok, jpeg = self.cv2.imencode(".jpg", bgr, [self.cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                raise ValueError("Impossible d'encoder l'image analysée.")
            with self._lock:
                self._presence.observe(bool(poses), timestamp_ms / 1000)
                self._pending = {
                    "timestamp_ms": timestamp_ms, "poses": poses,
                    "image": base64.b64encode(jpeg).decode("ascii"),
                }
        except Exception as error:
            with self._lock:
                self._error = f"Analyse de posture : {error}"

    def status(self):
        with self._lock:
            status = self._presence.status(time.monotonic())
            status["error"] = self._error
            return status

    def _publish(self):
        with self._lock:
            packet, self._pending = self._pending, None
        if packet is not None:
            try:
                self.ui._post("/local/posture", packet, timeout=0.5)
                self._ui_warned = False
            except Exception as error:
                if not getattr(self, "_ui_warned", False):
                    print(f"Affichage posture indisponible ({self.ui.url}) : {error}", flush=True)
                    self._ui_warned = True

    def _run(self):
        try:
            while not self._stop.is_set():
                self._publish()
                try:
                    frame = self.stream.get_image()
                    if self._stop.is_set():
                        break
                    if frame is None:
                        continue
                    bgr_frame, timestamp_ms = frame
                    rgb_frame = self.stream.bgr_to_rgb(bgr_frame)
                    mp_image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb_frame)
                    self._landmarker.detect_async(mp_image, timestamp_ms)
                except Exception as error:
                    with self._lock:
                        self._error = f"Flux caméra / analyse indisponible : {error}"
                    self._stop.wait(0.2)
                else:
                    with self._lock:
                        self._error = None
        finally:
            try:
                self._landmarker.close()
            finally:
                # Nettoyage dans le worker, après le dernier callback.
                try:
                    self.ui._post("/local/posture", {"stopped": True}, timeout=0.5)
                except Exception:
                    pass  # L'UI expire aussi les images si le programme est interrompu.

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=6)
            self._thread = None
