"""Démarrage du vrai binaire dans Docker, sans pilotes ni matériel."""
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
           ROS_DOMAIN_ID="199", BRIDGE_BIND="127.0.0.1:18000")
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
    raise AssertionError(f"{path} {data} devait être refusé ({code})")


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
            raise RuntimeError("Le bridge a quitté pendant son démarrage")
        try:
            status = json.loads(request("/status"))
            if status["supervisor"] == "Démarrage automatique désactivé":
                break
        except (urllib.error.URLError, TimeoutError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("La boucle ROS ne démarre pas")
        time.sleep(0.1)
    assert request("/ready") == "not ready"
    assert status["ros_alive"] is False

    # Mouvement : refusé sans robot prêt, zéro toujours accepté.
    refused("/speed", {"speed_mps": 0.03}, 503)
    refused("/velocity", {"linear_mps": 0.0, "angular_rad_s": 0.5}, 503)
    refused("/wheels", {"left_mps": 0.5, "right_mps": 0.5}, 400)
    refused("/velocity", {"linear_mps": 0.08, "angular_rad_s": 0.5}, 400)
    assert json.loads(request("/speed", {"speed_mps": 0.0}))["published_to_ros"]
    assert json.loads(request("/velocity", {"linear_mps": 0, "angular_rad_s": 0}))["published_to_ros"]
    assert json.loads(request("/stop", {}))["published_to_ros"]

    # Télémétrie : capteurs absents, services listés mais indisponibles.
    telemetry = json.loads(request("/telemetry"))
    assert telemetry["sensors"] == {}, telemetry
    assert set(telemetry["services"]) == {"sound", "motor_power", "reset"}
    assert not any(s["available"] for s in telemetry["services"].values())
    assert telemetry["limits"]["wheel_mps"] == 0.1

    # Un service absent échoue vite, et /status reste servi pendant l'attente.
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
    assert time.monotonic() - started < 0.5, "/status bloqué par un appel de service"
    caller.join()
    assert outcome["seconds"] < 4, outcome
    refused("/sound", {"value": 9}, 400)

    # Observation générique : le bridge voit son propre /cmd_vel.
    refused("/watch", {"topic": "/inexistant"}, 503)
    refused("/watch", {"topic": "pas un topic"}, 400)

    def has_cmd_vel():
        names = [t["name"] for t in json.loads(request("/topics"))["topics"]]
        return "/cmd_vel" in names

    wait_for(has_cmd_vel, "/cmd_vel absent de /topics")
    assert json.loads(request("/watch", {"topic": "/cmd_vel"}))["ok"]

    def watched():
        entry = json.loads(request("/telemetry"))["watched"].get("/cmd_vel", {})
        return entry.get("data") is not None

    wait_for(watched, "Aucun message observé sur /cmd_vel")
    assert json.loads(request("/unwatch", {"topic": "/cmd_vel"}))["ok"]
    print("Smoke test OK : HTTP, boucle ROS, not ready, refus du mouvement, zéro, "
          "télémétrie, services absents, observation de topic.", flush=True)
finally:
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
    try:
        returncode = process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise RuntimeError("Le bridge ne s'arrête pas après SIGINT")
    if returncode != 0:
        raise RuntimeError(f"Arrêt du bridge en erreur : {returncode}")
