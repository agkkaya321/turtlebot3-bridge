import base64
import unittest
from unittest.mock import patch

from posture import PostureStore


class PostureStoreTests(unittest.TestCase):
    def packet(self, poses=None):
        return {"timestamp_ms": 100_000, "image": base64.b64encode(b"\xff\xd8jpeg\xff\xd9").decode(),
                "poses": poses or []}

    def test_result_expires_even_when_producer_disappears(self):
        store = PostureStore()
        with patch("posture.time.monotonic", return_value=100):
            store.update(self.packet())
            self.assertTrue(store.snapshot()["active"])
        with patch("posture.time.monotonic", return_value=103):
            self.assertIsNone(store.snapshot()["image"])

    def test_delayed_packet_is_not_shown_as_fresh(self):
        store = PostureStore()
        with patch("posture.time.monotonic", return_value=105):
            store.update(self.packet())
            self.assertFalse(store.snapshot()["active"])

    def test_clear_and_empty_detection_remove_points(self):
        store = PostureStore()
        pose = [{"x": .5, "y": .5, "visibility": .9} for _ in range(33)]
        with patch("posture.time.monotonic", return_value=100):
            store.update(self.packet([pose]))
            self.assertEqual(len(store.snapshot()["poses"][0]), 33)
            store.update(self.packet())
            self.assertEqual(store.snapshot()["poses"], [])
            store.update({"stopped": True})
            self.assertFalse(store.snapshot()["active"])

    def test_invalid_payloads_are_rejected(self):
        for packet in ([], {}, self.packet([[{}]]), {**self.packet(), "image": "invalid"},
                       {**self.packet(), "image": "a" * 700_001},
                       self.packet([[{"x": float("nan"), "y": 0, "visibility": 1}] * 33])):
            with self.subTest(packet=str(packet)[:60]), self.assertRaises(ValueError):
                PostureStore().update(packet)


if __name__ == "__main__":
    unittest.main()
