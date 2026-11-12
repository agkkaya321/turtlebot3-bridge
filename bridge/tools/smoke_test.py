"""Start the real binary in Docker, without drivers or hardware."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

env = dict(os.environ, ROS_AUTOSTART="false", ROS_LOCALHOST_ONLY="1",
           ROS_DOMAIN_ID="199", BRIDGE_BIND="127.0.0.1:18000", CAMERA_ENABLED="false")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(path, data=None, timeout=2):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request("http://127.0.0.1:18000" + path, data=body,
                                 headers={"Content-Type": "application/json"})
    with opener.open(req, timeout=timeout) as response:
        return response.read().decode()


def refused(path, data, code, timeout=2):
    try:
        request(path, data, timeout)
    except urllib.error.HTTPError as error:
        assert error.code == code, (path, error.code, error.read())
        return json.loads(error.read() or b"{}")
    raise AssertionError(f"{path} {data} should have been rejected ({code})")


def wait_for(check, message, seconds=10):
    deadline = time.monotonic() + seconds
    while not check():
        if time.monotonic() >= deadline:
            raise RuntimeError(message)
        time.sleep(0.1)


process = subprocess.Popen([sys.argv[1]], env=env)
try:
    deadline = time.monotonic() + 20
    while True:
        if process.poll() is not None:
            raise RuntimeError("The bridge exited during startup")
        try:
            status = json.loads(request("/status"))
            if status["supervisor"] == "Automatic startup disabled":
                break
        except (urllib.error.URLError, TimeoutError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("The ROS loop is not starting")
        time.sleep(0.1)
    assert request("/ready") == "not ready"
    assert status["ros_alive"] is False
    assert json.loads(request("/camera/status"))["state"] == "disabled"
    refused("/camera/frame.jpg", None, 503)

    # Motion is rejected unless the robot is ready; zero velocity is always accepted.
    refused("/speed", {"speed_mps": 0.03}, 503)
    refused("/velocity", {"linear_mps": 0.0, "angular_rad_s": 0.5}, 503)
    refused("/wheels", {"left_mps": 0.5, "right_mps": 0.5}, 400)
    refused("/velocity", {"linear_mps": 0.08, "angular_rad_s": 0.5}, 400)
    assert json.loads(request("/speed", {"speed_mps": 0.0}))["published_to_ros"]
    assert json.loads(request("/velocity", {"linear_mps": 0, "angular_rad_s": 0}))["published_to_ros"]
    assert json.loads(request("/stop", {}))["published_to_ros"]

    # Telemetry: sensors missing, services listed but unavailable.
    telemetry = json.loads(request("/telemetry"))
    assert telemetry["sensors"] == {}, telemetry
    assert set(telemetry["services"]) == {"sound", "motor_power", "reset"}
    assert not any(s["available"] for s in telemetry["services"].values())
    assert telemetry["limits"]["wheel_mps"] == 0.1

    # A missing service fails quickly, and /status stays available while waiting.
    outcome = {}

    def call_sound():
        started = time.monotonic()
        outcome["body"] = refused("/sound", {"value": 1}, 503, timeout=6)
        outcome["seconds"] = time.monotonic() - started

    caller = threading.Thread(target=call_sound)
    caller.start()
    time.sleep(0.3)
    started = time.monotonic()
    json.loads(request("/status"))
    assert time.monotonic() - started < 0.5, "/status blocked by a service call"
    caller.join()
    assert outcome["seconds"] < 4, outcome
    refused("/sound", {"value": 9}, 400)

    # Generic watching: the bridge sees its own /cmd_vel.
    refused("/watch", {"topic": "/nonexistent"}, 503)
    refused("/watch", {"topic": "not a topic"}, 400)

    def has_cmd_vel():
        names = [t["name"] for t in json.loads(request("/topics"))["topics"]]
        return "/cmd_vel" in names

    wait_for(has_cmd_vel, "/cmd_vel missing from /topics")
    assert json.loads(request("/watch", {"topic": "/cmd_vel"}))["ok"]

    def watched():
        entry = json.loads(request("/telemetry"))["watched"].get("/cmd_vel", {})
        return entry.get("data") is not None

    wait_for(watched, "No message observed on /cmd_vel")
    assert json.loads(request("/unwatch", {"topic": "/cmd_vel"}))["ok"]
    print("Smoke test passed: HTTP, ROS loop, not ready, rejected motion, zero velocity, "
          "telemetry, missing services, and topic watching.", flush=True)
finally:
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
    try:
        returncode = process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise RuntimeError("The bridge did not stop after SIGINT")
    if returncode != 0:
        raise RuntimeError(f"Bridge shutdown failed: {returncode}")
