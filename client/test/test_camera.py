"""Camera client and local UI proxy, with an HTTP server and no robot."""
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

try:
    from client.camera import CameraClient, MAX_FRAME_BYTES
    from client.robot import BridgeError
except ModuleNotFoundError:  # Also support running unittest from client/.
    from camera import CameraClient, MAX_FRAME_BYTES
    from robot import BridgeError


class FakeCamera(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        status, data, kind = self.server.reply
        if self.path == "/camera/status":
            status, data, kind = 200, b'{"enabled": true, "state": "ready"}', "application/json"
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Camera-Sequence", "42")
        self.send_header("X-Camera-Age-Ms", "12")
        self.send_header("X-Camera-Stamp", "123.000000456")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass


class CameraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeCamera)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        spec = importlib.util.spec_from_file_location(
            "camera_test_ui", Path(__file__).resolve().parents[2] / "ui/server.py")
        cls.ui_module = importlib.util.module_from_spec(spec)
        with patch("sys.argv", ["server.py", "--bridge", cls.url]):
            spec.loader.exec_module(cls.ui_module)
        cls.proxy = ThreadingHTTPServer(("127.0.0.1", 0), cls.ui_module.Handler)
        cls.proxy_thread = threading.Thread(target=cls.proxy.serve_forever, daemon=True)
        cls.proxy_thread.start()

    @classmethod
    def tearDownClass(cls):
        for server, thread in [(cls.proxy, cls.proxy_thread), (cls.server, cls.thread)]:
            server.shutdown()
            server.server_close()
            thread.join()

    def setUp(self):
        self.server.reply = (200, b"\xff\xd8test-jpeg\xff\xd9", "image/jpeg")
        self.camera = CameraClient(self.url)

    def test_jpeg_bytes_and_acquisition_metadata(self):
        self.assertEqual(self.camera.status()["state"], "ready")
        frame = self.camera.frame()
        self.assertEqual(frame.jpeg, self.server.reply[1])
        self.assertEqual((frame.sequence, frame.age_ms, frame.stamp), (42, 12, "123.000000456"))

    def test_disabled_or_stale_camera_is_an_explicit_error(self):
        self.server.reply = (503, b'{"error":"No fresh image"}', "application/json")
        with self.assertRaises(BridgeError) as caught:
            self.camera.frame()
        self.assertEqual(caught.exception.code, 503)
        self.assertIn("No fresh image", str(caught.exception))

    def test_rejects_wrong_type_corrupt_and_oversized_images(self):
        for data, kind in [(b"{}", "application/json"), (b"bad", "image/jpeg"),
                           (b"\xff\xd8" + b"x" * MAX_FRAME_BYTES + b"\xff\xd9", "image/jpeg")]:
            with self.subTest(kind=kind, size=len(data)):
                self.server.reply = (200, data, kind)
                with self.assertRaises(ValueError):
                    self.camera.frame()

    def test_ui_proxy_preserves_jpeg_and_metadata(self):
        camera = CameraClient(f"http://127.0.0.1:{self.proxy.server_port}/api")
        self.assertEqual(camera.frame(), self.camera.frame())
        self.server.reply = (503, json.dumps({"error": "stale"}).encode(), "application/json")
        with self.assertRaises(BridgeError) as caught:
            camera.frame()
        self.assertEqual(caught.exception.code, 503)

    def test_ui_proxy_rejects_oversized_camera_frame(self):
        self.server.reply = (200, b"x" * (MAX_FRAME_BYTES + 1), "image/jpeg")
        camera = CameraClient(f"http://127.0.0.1:{self.proxy.server_port}/api")
        with self.assertRaises(BridgeError) as caught:
            camera.frame()
        self.assertEqual(caught.exception.code, 502)
