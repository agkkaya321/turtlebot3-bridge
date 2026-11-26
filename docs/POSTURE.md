# NextStep posture analysis

Analysis runs on the Mac. The Raspberry Pi supplies JPEG frames through the
existing bridge; MediaPipe does not need to be installed on the robot.

## Prepare the Mac with internet access

Use a Python virtual environment compatible with MediaPipe:

```bash
# Only if no virtual environment exists yet:
python3 -m venv .venv
.venv/bin/python -m pip install -r client/next_step/posture_analysis/requirements.txt
curl -fL -o client/next_step/posture_analysis/pose_landmarker_lite.task \
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task
```

`opencv-contrib-python` provides `cv2` and is also used by MediaPipe. Do not
install another OpenCV distribution in the same environment. The model and
`.venv/` are ignored by Git. Prepare both before joining the isolated robot
network; the client does not download them automatically at startup.
Set `Main(pose_model="PATH")` or `POSE_MODEL` to use another model.

## Run a test without command-line arguments

From the repository root, start the tunnel and UI with `./start.sh`.
In a second terminal, activate the prepared environment and run:

```bash
source .venv/bin/activate
python3 client/next_step/main.py
```

With the environment activated, `python3` uses its installed dependencies.
The script has no argument parser. Select the test at the bottom of
`client/next_step/main.py`, leaving exactly one call enabled:

```python
if __name__ == "__main__":
    robot = Main()

    # Choose one test: comment out the other call.
    robot.camera_test()
    # robot.user_follow_test()  # Motors are enabled; use Main(dry_run=True) to disable them.
```

- `camera_test()` starts the camera and MediaPipe through `posture_checking`
  (state 2). It holds a zero motion command and displays the analysis in the
  UI's main camera view. This is the default selection.
- `user_follow_test()` starts LiDAR following (state 1) and can move the robot.
  Change the constructor to `Main(dry_run=True)` to calculate commands without
  sending movement commands. This still accesses the real bridge and sensors.

Stop the current test with Ctrl+C before switching to the other one. Both
methods run the FSM loop and preserve shutdown handling.

If the ports printed by `start.sh` differ from the defaults, edit the
constructor in the same block:

```python
robot = Main(
    url="http://127.0.0.1:8000",
    ui_url="http://127.0.0.1:8080",
    hz=10,
    dry_run=True,
    # pose_model="/path/to/model.task",
)
```

Dimensions can also be supplied through `Main(measurements=...)`; see
[GUIDE_ROBOT.md](GUIDE_ROBOT.md). No Rust rebuild is needed for client changes.

## Camera display and lifecycle

The main camera view shows visible landmarks and skeleton connections on the
exact analyzed frame. While MediaPipe is active, the UI uses this local stream
instead of requesting a second raw stream from the robot. If analysis becomes
inactive or expires, it returns to the raw camera feed.

**Pause** freezes the view and suspends its image requests; the Python detector
continues processing. **Capture** saves the displayed image with its landmarks.
The display follows the frame's rotation and dimensions in portrait or landscape.
Restart the UI server if it was already running before an update.

Analysis continues indefinitely when no person is detected. The console prints
"The user must be on the image." only when the situation changes, without a
countdown. Ctrl+C or a state exit releases the detector.
**The UI, bridge and Raspberry Pi remain running.**

OpenCV/MediaPipe technical logs (information, warnings and debug), including
native C++ output, are filtered. Errors remain visible. A disconnected camera,
an invalid stream or a missing MediaPipe response is reported; absence of a
person does not trigger an automatic shutdown. Displayed analysis expires after
3 seconds so an old posture does not remain on screen if the process disappears.

## macOS executable in build/

After preparing `.venv` and the model, select the test and configure `Main(...)`
at the bottom of `main.py`, then build from the repository root:

```bash
.venv/bin/python -m pip install 'pyinstaller==6.22.3'
./build-client.sh
```

The script uses [PyInstaller](https://pyinstaller.org/en/stable/usage.html)
to create `build/nextstep/nextstep` with Python, OpenCV, MediaPipe and the posture
model included. It does not run the executable after building.

Keep the **entire `build/nextstep/` directory**, including `_internal/`, when
copying it. The executable targets macOS and the build Mac's architecture
(Apple Silicon for the existing build). It does not run on the Raspberry Pi
and does not require `.venv` at runtime. Build outputs and caches remain in
`build/`, which is ignored by Git.

After `./start.sh`, launch it in a second terminal:

```bash
./build/nextstep/nextstep
```

The executable runs the test selected in `main.py` when it was built.
**Rebuild after changing the selected test or constructor settings.**
There are no `--state`, `--dry-run`, `--url`, `--ui-url` or `--pose-model`
options. Set `dry_run=True` in the constructor before building to disable
movement. `POSE_MODEL` can override the bundled model when no explicit
`pose_model` is configured. Ctrl+C stops the selected test; the bridge and UI
remain open and are still launched separately by `start.sh`.

The previous macOS ARM64 build was checked against a local fake HTTP bridge:
both modes with movement disabled, MediaPipe analysis of a synthetic JPEG with
no person, publication of the analyzed frame and clean Ctrl+C shutdown.
Those checks predate the removal of the argument parser; the executable has
not been rebuilt or revalidated for this change. They do not validate hardware.

## Components and HTTP routes

- `BridgeClient.camera_frame(after)`: requests `GET /camera/frame?after=N`
  through the tunnel and returns `(jpeg, frame_nb)`, or `None` for HTTP 204,
  with a 4-second HTTP timeout.
- `decode_live_stream.py`: `LiveStreamDecoder.get_image()` decodes the JPEG
  into `(bgr_frame, timestamp_ms)`; `bgr_to_rgb()` converts it to RGB.
  Receipt timestamps strictly increase. After HTTP 204, the cursor resets to
  recover from a restarted bridge.
- `posture_detector.py` replaces `mediapipe_test.py`. A worker acquires
  frames, supplies `rgb_frame` and `timestamp_ms` to `detect_async()` and
  publishes the latest result. The callback retains the exact frame associated
  with the landmarks. HTTP and MediaPipe work do not block the 10 Hz FSM loop.
- `POST /local/posture` on the **Mac's UI server** receives
  `{timestamp_ms, image, poses}`: a base64 JPEG and up to one pose containing
  33 `{x, y, visibility}` landmarks. `{stopped: true}` clears the result.
- `GET /local/posture` returns the latest result with `active` and `age_ms`,
  or `{active: false, image: null, poses: []}` after expiration. Data stays in
  memory and is not sent back through the robot.

The historical `decode_image.py` and `openCV_test.py` examples are independent
tutorial scripts, not FSM components.

API reference:
[MediaPipe PoseLandmarker — LIVE_STREAM and detect_async](https://developers.google.com/edge/api/mediapipe/python/mp/tasks/vision/PoseLandmarker).
MediaPipe may skip frames while busy, so the UI draws on the callback frame
rather than a different stream frame.

## Verify without a robot

```bash
.venv/bin/python -B -m unittest discover -s client -p 'test_*.py'
python3 -B -m unittest discover -s ui -p 'test_*.py'
```

Tests cover acquisition, JPEG decoding and color conversion (when OpenCV is
installed), waiting without an absence timeout, stale results, log filtering,
state exit and display expiration. They do not validate posture tracking on
the C270 or a clinical score.

Previous local checks used MediaPipe 0.10.35 and OpenCV 4.14.0: a real
LIVE_STREAM callback on frames without a person served by a fake HTTP bridge,
and UI cleanup on exit. Skeleton rendering was checked in Chrome with
33 synthetic points. Person detection and tracking on the real C270 stream
remain unconfirmed.
