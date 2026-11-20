"""Acquisition, délai d'absence et cycle de vie, sans robot."""

from email.message import Message
import importlib.util
import threading
import time
import unittest
from unittest.mock import Mock, patch

from robot import BridgeClient
from next_step.main import Main
from next_step.posture_analysis.decode_live_stream import LiveStreamDecoder
from next_step.posture_analysis.posture_detector import PosePresence, PostureDetector
from next_step.finite_state_machine.states.posture_checking_state import PostureCheckingState


class PresenceTests(unittest.TestCase):
    def test_initial_grace_then_exact_timeout(self):
        presence = PosePresence(100)
        self.assertFalse(presence.status(109.999)["expired"])
        self.assertTrue(presence.status(110)["expired"])

    def test_detection_resets_deadline_but_absence_does_not(self):
        presence = PosePresence(100)
        presence.observe(True, 109)
        presence.observe(False, 110)
        self.assertFalse(presence.status(118.999)["expired"])
        self.assertTrue(presence.status(119)["expired"])
        presence.observe(True, 119)
        self.assertFalse(presence.status(120)["expired"])

    def test_stale_result_and_out_of_order_callback_do_not_extend_timeout(self):
        presence = PosePresence(100)
        presence.observe(True, 101)
        presence.observe(False, 102)
        presence.observe(True, 100.5)
        self.assertFalse(presence.status(103)["present"])
        self.assertFalse(presence.status(106)["fresh"])
        self.assertTrue(presence.status(111)["expired"])

    def test_frozen_positive_result_expires(self):
        presence = PosePresence(100)
        presence.observe(True, 101)
        self.assertFalse(presence.status(105)["present"])
        self.assertTrue(presence.status(111)["expired"])


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


@unittest.skipUnless(importlib.util.find_spec("cv2"), "OpenCV optionnel absent")
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
    def test_state_stops_motion_waits_then_finishes_and_closes(self, output):
        robot = Main()
        robot.forward(.05)
        state = PostureCheckingState(robot)
        with patch("next_step.finite_state_machine.states.posture_checking_state.PostureDetector") as factory:
            detector = factory.return_value
            detector.status.return_value = {"present": False, "fresh": True, "remaining": 9, "expired": False, "error": None}
            state.enter()
            self.assertEqual(robot.command, (0, 0))
            state.loop()
            self.assertFalse(robot._finished)
            self.assertTrue(any("La personne n'est pas sur l'image" in str(c) for c in output.call_args_list))
            detector.status.return_value.update(remaining=0, expired=True)
            state.loop()
            self.assertTrue(robot._finished)
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
