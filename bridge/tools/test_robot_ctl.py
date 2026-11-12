"""Startup tests without SSH, ROS, or hardware.

Run: python3 -B -m unittest discover -s bridge/tools -p 'test_*.py'
"""

import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest


class StartTests(unittest.TestCase):
    def run_start(self, setup="", binary=None):
        source = Path(__file__).with_name("robot_ctl.sh").read_text()
        functions = source.rsplit('\ncase "${1:-check}" in', 1)[0]
        with tempfile.TemporaryDirectory(prefix="tb3-start-test-") as tmp:
            root = Path(tmp)
            release = root / "target" / "release"
            release.mkdir(parents=True)
            (root / "robot.env").touch()
            (root / "run.sh").write_text(
                '#!/bin/bash\n' + setup
                + '\nexec ./target/release/turtlebot-speed-bridge\n'
            )
            (release / "turtlebot-speed-bridge").write_text(
                '#!/bin/bash\necho $$ > binary.pid\n'
                + (binary if binary is not None else
                   'echo "not ready" > response\nwhile :; do sleep 1; done\n')
            )
            # Linux process detachment is simulated; the whole process family
            # stays in a dedicated session that is cleaned up after the test.
            shim = root / "setsid"
            shim.write_text(
                '#!/bin/bash\n[ "$1" = --wait ] && shift\nexec "$@"\n'
            )
            shim.chmod(0o755)
            harness = root / "test.sh"
            harness.write_text(functions + '''
DIR=$1
bridge_pids() {
    local pid
    if [ -f "$DIR/binary.pid" ]; then
        pid=$(cat "$DIR/binary.pid")
        kill -0 "$pid" 2>/dev/null && echo "$pid"
    fi
    return 0
}
http_get() { cat "$DIR/response" 2>/dev/null; }
# Speed up only controller sleeps, not those of the fake robot.
sleep() { command sleep 0.03; }
cmd_start
''')
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ["PATH"])
            process = subprocess.Popen(
                ["bash", str(harness), tmp], env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, start_new_session=True,
            )
            try:
                output, _ = process.communicate(timeout=15)
                return process.returncode, output
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()

    def test_slow_ros_setup(self):
        code, output = self.run_start(setup="sleep 0.8")
        self.assertEqual(code, 0, output)
        self.assertIn("Bridge started", output)

    def test_setup_failure_reports_log(self):
        code, output = self.run_start(setup="echo 'ROS missing' >&2\nexit 7")
        self.assertEqual(code, 1, output)
        self.assertIn("stopped during startup", output)
        self.assertIn("ROS missing", output)

    def test_binary_failure_reports_log(self):
        code, output = self.run_start(binary="echo 'Binary error' >&2\nexit 8")
        self.assertEqual(code, 1, output)
        self.assertIn("stopped during startup", output)
        self.assertIn("Binary error", output)

    def test_http_timeout_is_failure(self):
        code, output = self.run_start(binary="while :; do sleep 1; done")
        self.assertEqual(code, 1, output)
        self.assertIn("Startup timed out", output)

    def test_http_can_start_before_robot_is_ready(self):
        code, output = self.run_start(binary=(
            'sleep 0.8\necho "not ready" > response\n'
            'while :; do sleep 1; done\n'
        ))
        self.assertEqual(code, 0, output)
        self.assertIn("Bridge started", output)


if __name__ == "__main__":
    unittest.main()
