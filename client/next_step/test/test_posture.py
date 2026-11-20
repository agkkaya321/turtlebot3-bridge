"""Test continuous acquisition, presence, and lifecycle without a robot."""

from email.message import Message
import importlib.util
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch

from robot import BridgeClient
from next_step.main import Main
from next_step.posture_analysis.decode_live_stream import LiveStreamDecoder
from next_step.posture_analysis.posture_detector import PosePresence, PostureDetector
from next_step.finite_state_machine.states.posture_checking_state import PostureCheckingState


class PresenceTests(unittest.TestCase):
    def test_no_deadline_when_waiting_for_first_result(self):
        presence = PosePresence()
        self.assertEqual(presence.status(3600), {"present": False, "fresh": False})

    def test_presence_can_return_after_a_long_absence(self):
        presence = PosePresence()
        presence.observe(True, 109)
        presence.observe(False, 110)
        self.assertFalse(presence.status(3600)["present"])
        presence.observe(True, 3600)
        self.assertEqual(presence.status(3601), {"present": True, "fresh": True})

    def test_stale_result_and_out_of_order_callback_do_not_restore_presence(self):
        presence = PosePresence()
        presence.observe(True, 101)
        presence.observe(False, 102)
        presence.observe(True, 100.5)
        self.assertFalse(presence.status(103)["present"])
        self.assertFalse(presence.status(106)["fresh"])

    def test_frozen_positive_result_expires(self):
        presence = PosePresence()
        presence.observe(True, 101)
        self.assertFalse(presence.status(105)["present"])


class NativeLogTests(unittest.TestCase):
    def test_native_diagnostics_are_filtered_but_errors_and_stderr_are_restored(self):
        code = '''
import os
from next_step.posture_analysis.native_logs import NativeLogFilter
logs = NativeLogFilter()
logs.start()
os.write(2, b"I0000 00:00:123456.123456 123 gl_context.cc:407] INFO atypical format\\n")
os.write(2, b"I0000 00:00:00.123456 123 gl_context.cc:407] GL version\\n")
os.write(2, b"W0000 00:00:00.123456 123 inference_feedback_manager.cc:121] feedback\\n")
os.write(2, b"INFO: Created TensorFlow Lite XNNPACK delegate for CPU.\\n")
os.write(2, b"[ WARN:0@0.001] global cap.cpp debug\\n")
os.write(2, b"E0000 00:00:00.123456 123 graph.cc:1] native failure\\n")
os.write(2, b"Stop not confirmed: robot disconnected\\n")
logs.close()
logs.close()
os.write(2, b"stderr restored\\n")
'''
        result = subprocess.run([sys.executable, "-B", "-c", code],
                                cwd=Path(__file__).resolve().parents[2],
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(b"GL version", result.stderr)
        self.assertNotIn(b"atypical format", result.stderr)
        self.assertNotIn(b"feedback", result.stderr)
        self.assertNotIn(b"TensorFlow", result.stderr)
        self.assertNotIn(b"cap.cpp", result.stderr)
        self.assertIn(b"native failure", result.stderr)
        self.assertIn(b"robot disconnected", result.stderr)
        self.assertIn(b"stderr restored", result.stderr)


class CameraTransportTests(unittest.TestCase):
    def response(self, status=200, kind="image/jpeg"):
        response = Mock(status=status)
        response.headers = Message()
        response.headers["Content-Type"] = kind
        response.headers["X-Frame-Seq"] = "42"
        response.read.return_value = b"jpeg"
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_camera_route_returns_bytes_and_sequence(self):
        bridge = BridgeClient("http://localhost:9876")
        bridge._http = Mock()
        bridge._http.open.return_value = self.response()
        self.assertEqual(bridge.camera_frame(41), (b"jpeg", 42))
        bridge._http.open.assert_called_once_with("http://localhost:9876/camera/frame?after=41", timeout=4.0)

    def test_no_frame_is_not_decoded(self):
        bridge = BridgeClient()
        bridge._http = Mock()
        response = self.response(status=204)
        bridge._http.open.return_value = response
        self.assertIsNone(bridge.camera_frame())
        response.read.assert_not_called()

    def test_wrong_content_type_is_rejected(self):
        bridge = BridgeClient()
        bridge._http = Mock()
        bridge._http.open.return_value = self.response(kind="application/json")
        with self.assertRaises(ValueError):
            bridge.camera_frame()


@unittest.skipUnless(importlib.util.find_spec("cv2"), "Optional OpenCV dependency is not installed")
class DecoderTests(unittest.TestCase):
    def test_real_jpeg_decoding_rgb_conversion_and_monotone_timestamps(self):
        import cv2
        import numpy as np
        decoder = LiveStreamDecoder()
        source = np.full((8, 12, 3), (15, 30, 240), dtype=np.uint8)
        ok, jpeg = cv2.imencode(".jpg", source)
        self.assertTrue(ok)
        decoder.bridge = Mock()
        decoder.bridge.camera_frame.side_effect = [(jpeg.tobytes(), 4), (jpeg.tobytes(), 5), None]
        with patch("time.monotonic_ns", return_value=1_000_000):
            first, stamp1 = decoder.get_image()
            second, stamp2 = decoder.get_image()
        self.assertEqual(first.shape, (8, 12, 3))
        self.assertGreater(stamp2, stamp1)
        rgb = decoder.bgr_to_rgb(second)
        np.testing.assert_array_equal(rgb[:, :, 0], second[:, :, 2])
        np.testing.assert_array_equal(rgb[:, :, 2], second[:, :, 0])
        self.assertIsNone(decoder.get_image())
        self.assertEqual(decoder.sequence, 0)

    def test_bad_jpeg_is_rejected(self):
        decoder = LiveStreamDecoder()
        decoder.bridge = Mock()
        decoder.bridge.camera_frame.return_value = (b"not jpeg", 1)
        with self.assertRaises(ValueError):
            decoder.get_image()


@patch("builtins.print")
class PostureStateTests(unittest.TestCase):
    def test_state_keeps_waiting_without_finishing_or_repeating_absence_message(self, output):
        robot = Main()
        robot.forward(.05)
        state = PostureCheckingState(robot)
        with patch("next_step.finite_state_machine.states.posture_checking_state.PostureDetector") as factory:
            detector = factory.return_value
            detector.status.return_value = {"present": False, "fresh": True, "error": None}
            state.enter()
            self.assertEqual(robot.command, (0, 0))
            state.loop()
            self.assertFalse(robot._finished)
            self.assertTrue(any("La personne n'est pas sur l'image" in str(c) for c in output.call_args_list))
            for _ in range(600):
                state.loop()
            self.assertFalse(robot._finished)
            output.assert_called_once_with("La personne n'est pas sur l'image.", flush=True)
            detector.status.return_value.update(present=True)
            state.loop()
            detector.status.return_value.update(present=False)
            state.loop()
            self.assertEqual(output.call_count, 2)
            state.exit()
            detector.close.assert_called_once()

    def test_main_releases_state_on_keyboard_interrupt(self, _):
        robot = Main()
        robot.fsm = Mock()
        with patch("tb3.Robot.run", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                robot.run()
        robot.fsm.get_current_state.return_value.exit.assert_called_once()

    def test_acquisition_worker_closes_landmarker_on_stop(self, _):
        detector = PostureDetector("http://localhost:9999")
        detector._landmarker = Mock()
        detector.ui = Mock()
        entered = threading.Event()

        def wait_frame():
            entered.set()
            detector._stop.wait(1)
            return None

        detector.stream.get_image = wait_frame
        detector._thread = threading.Thread(target=detector._run)
        detector._thread.start()
        self.assertTrue(entered.wait(1))
        detector.close()
        detector._landmarker.close.assert_called_once()
        detector.ui._post.assert_called_once_with("/local/posture", {"stopped": True}, timeout=0.5)


if __name__ == "__main__":
    unittest.main()
