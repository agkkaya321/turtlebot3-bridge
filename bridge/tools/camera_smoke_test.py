"""Real ROS CompressedImage -> ARM64 bridge -> HTTP, entirely inside Docker."""
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

os.environ.update(ROS_DOMAIN_ID="198", ROS_LOCALHOST_ONLY="1")
import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Image

opener = build_opener(ProxyHandler({}))
url = "http://127.0.0.1:18001"


def get(path):
    with opener.open(url + path, timeout=2) as response:
        return response.read(), response.headers


def status():
    return json.loads(get("/camera/status")[0])


def wait_for(check, seconds=15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            if check():
                return
        except (URLError, TimeoutError):
            pass
        time.sleep(0.05)
    raise AssertionError("Camera condition not reached")


def unavailable():
    try:
        get("/camera/frame.jpg")
    except HTTPError as error:
        assert error.code == 503, error.code
        return
    raise AssertionError("Missing/stale camera frame should return 503")


env = dict(os.environ, ROS_AUTOSTART="false", CAMERA_ENABLED="true",
           CAMERA_AUTOSTART="true", CAMERA_RAW_TOPIC="/test_camera/image_raw",
           BRIDGE_BIND="127.0.0.1:18001")
rclpy.init()
node = rclpy.create_node("synthetic_camera")
# An existing raw publisher must suppress autostart even before JPEG is available.
raw = node.create_publisher(Image, "/test_camera/image_raw", qos_profile_sensor_data)
publisher = None
process = subprocess.Popen([sys.argv[1]], env=env)
publishing = threading.Event()
stop = threading.Event()
payload = CompressedImage()
payload.format = "rgb8; jpeg compressed bgr8"
# No decoding in this transport; marker-valid synthetic bytes, not a real photograph.
payload.data = b"\xff\xd8" + b"test" * 16384 + b"\xff\xd9"


def publish():
    while not stop.wait(0.05):
        if publishing.is_set():
            payload.header.stamp = node.get_clock().now().to_msg()
            publisher.publish(payload)


thread = threading.Thread(target=publish)
thread.start()
try:
    wait_for(lambda: status()["enabled"])
    unavailable()
    wait_for(lambda: "External camera" in status()["supervisor"])
    time.sleep(5.5)  # Beyond the autostart discovery interval.
    assert "External camera" in status()["supervisor"]
    publisher = node.create_publisher(CompressedImage, "/test_camera/image_raw/compressed", qos_profile_sensor_data)
    publishing.set()
    wait_for(lambda: status()["state"] == "ready")
    data, headers = get("/camera/frame.jpg")
    assert data == bytes(payload.data)
    assert headers.get_content_type() == "image/jpeg"
    assert int(headers["X-Camera-Sequence"]) > 0
    assert int(headers["X-Camera-Age-Ms"]) < 1000
    # Camera works even with no motor drivers and does not make the robot ready.
    assert get("/ready")[0] == b"not ready"
    # Parallel image reads must leave the control path responsive.
    failures = []

    def download():
        for _ in range(10):
            try:
                get("/camera/frame.jpg")
            except HTTPError as error:
                if error.code != 503:
                    failures.append(error)
            except Exception as error:
                failures.append(error)

    readers = [threading.Thread(target=download) for _ in range(6)]
    for reader in readers:
        reader.start()
    request = Request(url + "/stop", data=b"{}", headers={"Content-Type": "application/json"})
    started = time.monotonic()
    with opener.open(request, timeout=2) as response:
        assert json.load(response)["published_to_ros"]
    assert time.monotonic() - started < 1
    for reader in readers:
        reader.join()
    assert not failures, failures
    publishing.clear()
    wait_for(lambda: status()["state"] == "stale")
    unavailable()
    publishing.set()
    wait_for(lambda: status()["state"] == "ready")
    print("Camera smoke passed: external driver, JPEG >32 KiB, metadata, concurrent reads, stop, stale and recovery.", flush=True)
finally:
    stop.set()
    thread.join()
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
    try:
        code = process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise AssertionError("Camera bridge did not shut down")
    finally:
        node.destroy_node()
        rclpy.shutdown()
    assert code == 0, code

# Exercise owned-driver startup, retry and cleanup without a USB device. Only this
# subprocess gets the fake ros2 executable; it publishes synthetic ROS images.
with tempfile.TemporaryDirectory(prefix="camera-driver-") as directory:
    root = Path(directory)
    script = root / "driver.py"
    script.write_text('''import os, sys, time
from pathlib import Path
root = Path(__file__).parent
args = sys.argv[1:]
assert args[:3] == ["run", "usb_cam", "usb_cam_node_exe"], args
assert "pixel_format:=mjpeg2rgb" in args and "image_width:=640" in args, args
attempt = root / "attempt"
if not attempt.exists():
    attempt.write_text("failed once")
    sys.exit(1)
(root / "pid").write_text(str(os.getpid()))
import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage
rclpy.init()
node = rclpy.create_node("fake_owned_usb_cam")
pub = node.create_publisher(CompressedImage, "/owned/image_raw/compressed", qos_profile_sensor_data)
message = CompressedImage()
message.format = "jpeg"
message.data = bytes([255, 216, 255, 217])
try:
    while rclpy.ok():
        pub.publish(message)
        time.sleep(0.05)
except KeyboardInterrupt:
    pass
finally:
    node.destroy_node()
    rclpy.try_shutdown()
''')
    wrapper = root / "ros2"
    wrapper.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(script))} \"$@\"\n")
    wrapper.chmod(0o755)
    url = "http://127.0.0.1:18002"
    owned_env = dict(env, PATH=directory + os.pathsep + os.environ["PATH"],
                     ROS_DOMAIN_ID="197", BRIDGE_BIND="127.0.0.1:18002",
                     CAMERA_RAW_TOPIC="/owned/image_raw")
    process = subprocess.Popen([sys.argv[1]], env=owned_env)
    try:
        wait_for(lambda: status()["state"] == "ready", seconds=30)
        assert (root / "attempt").exists()
        wait_for(lambda: status()["supervisor"] == "Supervised camera active")
        child_pid = int((root / "pid").read_text())
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        try:
            code = process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise AssertionError("Owned-camera shutdown timed out")
        assert code == 0
    try:
        os.kill(child_pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError("Owned camera process survived bridge shutdown")
    print("Camera lifecycle passed: automatic startup, retry after exit, owned-process cleanup.", flush=True)
