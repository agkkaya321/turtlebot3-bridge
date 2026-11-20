"""Filter native diagnostics while preserving Python and robot errors.

MediaPipe also writes directly to the stderr file descriptor from its C++
threads, bypassing logging and contextlib.redirect_stderr.
"""

import logging
import os
import re
import threading


class NativeLogFilter:
    _diagnostic = re.compile(
        rb"^(?:[IWD]\d{4} \d{2}:\d{2}:\d+\.\d+\s+\d+\s+[^\n]+\.(?:cc|h):\d+\]|"
        rb"INFO: Created TensorFlow Lite|"
        rb"WARNING: All log messages before absl::InitializeLog\(\)|"
        rb"\[\s*(?:WARN|INFO|DEBUG|VERBOSE):)"
    )

    def __init__(self):
        self._saved = None
        self._thread = None

    def start(self):
        os.environ["OPENCV_LOG_LEVEL"] = "ERROR"
        os.environ["GLOG_minloglevel"] = "2"
        os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"

        logging.getLogger("mediapipe").setLevel(logging.ERROR)
        logging.getLogger("absl").setLevel(logging.ERROR)

        self._saved = os.dup(2)

        reader, writer = os.pipe()

        self._thread = threading.Thread(
            target=self._forward, args=(reader, self._saved),
            name="posture-logs", daemon=True,
        )
        self._thread.start()

        try:
            os.dup2(writer, 2)
        finally:
            os.close(writer)

    def _forward(self, reader, destination):
        try:
            with os.fdopen(reader, "rb") as source:
                for line in source:
                    if not self._diagnostic.match(line):
                        # Preserve native errors, tracebacks, and robot messages.
                        pending = memoryview(line)
                        while pending:
                            pending = pending[os.write(destination, pending):]
        finally:
            os.close(destination)

    def close(self):
        if self._saved is not None:
            os.dup2(self._saved, 2)
            self._saved = None
            self._thread.join(timeout=1)
