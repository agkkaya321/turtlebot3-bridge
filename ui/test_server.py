"""Vérifie l'isolation du mode aperçu et la distribution des ressources locales."""
import sys
import unittest
from unittest.mock import Mock, patch

with patch.object(sys, 'argv', ['server.py']):
    import server


class PreviewTests(unittest.TestCase):
    def request(self, method, path):
        handler = object.__new__(server.Handler)
        handler.path = path
        handler.send = Mock()
        handler.proxy = Mock(side_effect=AssertionError('Accès au bridge interdit'))
        handler.camera_frame = Mock(side_effect=AssertionError('Accès caméra interdit'))
        with patch.object(server.ARGS, 'preview', True), patch.object(
                server, 'robot_ctl', side_effect=AssertionError('Accès SSH interdit')):
            getattr(handler, 'do_' + method)()
        return handler.send.call_args.args

    def test_preview_blocks_robot_reads_and_actions(self):
        for path in ['/api/status', '/api/telemetry', '/api/camera/frame',
                     '/local/log', '/local/check']:
            with self.subTest(path=path):
                self.assertEqual(self.request('GET', path)[0], 503)
        for path in ['/api/velocity', '/api/stop', '/local/restart',
                     '/local/start', '/local/stop', '/local/posture']:
            with self.subTest(path=path):
                self.assertEqual(self.request('POST', path)[0], 403)

    def test_preview_serves_ui_and_reports_mode(self):
        self.assertEqual(self.request('GET', '/')[0], 200)
        self.assertTrue(self.request('GET', '/local/info')[1]['preview'])
        self.assertFalse(self.request('GET', '/local/posture')[1]['active'])

    def test_local_assets_are_confined_to_asset_directory(self):
        for path in ['/assets/hyperluv.css', '/assets/fonts/anton.ttf']:
            with self.subTest(path=path):
                self.assertEqual(self.request('GET', path)[0], 200)
        for path in ['/assets/../server.py', '/assets/../../AGENTS.md',
                     '/assets/missing.css', '/assets/fonts']:
            with self.subTest(path=path):
                self.assertEqual(self.request('GET', path)[0], 404)


if __name__ == '__main__':
    unittest.main()
