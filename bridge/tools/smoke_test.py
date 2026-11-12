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

env = dict(os.environ, ROS_AUTOSTART="false", CAMERA_AUTOSTART="false", ROS_LOCALHOST_ONLY="1",
           ROS_DOMAIN_ID="199", BRIDGE_BIND="127.0.0.1:18000")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(path, data=None, timeout=2):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request("http://127.0.0.1:18000" + path, data=body,
                                 headers={"Content-Type": "application/json"})
    with opener.open(req, timeout=timeout) as response:
        return response.read().decode()


def camera_frame(after=0):
    """(statut, en-têtes, octets) de GET /camera/frame."""
    with opener.open(f"http://127.0.0.1:18000/camera/frame?after={after}", timeout=5) as response:
        return response.status, response.headers, response.read()


# Fausse caméra : image rgb8 160×120 à 10 Hz, comme usb_cam (mjpeg2rgb).
FAKE_CAMERA = """
import array, rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
rclpy.init()
node = Node("fake_camera")
publisher = node.create_publisher(Image, "/image_raw", 10)
w, h = 160, 120
pixels = array.array("B", bytes(v for y in range(h) for x in range(w)
                                for v in (x * 255 // w, y * 255 // h, 128)))
def tick():
    msg = Image()
    msg.header.stamp = node.get_clock().now().to_msg()
    msg.width, msg.height, msg.encoding, msg.step = w, h, "rgb8", w * 3
    msg.data = pixels
    publisher.publish(msg)
node.create_timer(0.1, tick)
try:
    rclpy.spin(node)
except KeyboardInterrupt:
    pass
"""


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

    # Caméra sans image : pas d'abonnement tant que personne ne regarde, puis 204.
    camera = json.loads(request("/camera/status"))
    assert camera["topic"] == "/image_raw" and camera["subscribed"] is False, camera
    assert "désactivé" in camera["driver"] or "Recherche" in camera["driver"], camera
    started = time.monotonic()
    assert camera_frame()[0] == 204
    assert 2 < time.monotonic() - started < 4.5
    # Pendant l'attente vidéo, l'API de conduite répond toujours vite.
    waiters = [threading.Thread(target=camera_frame) for _ in range(4)]
    for waiter in waiters:
        waiter.start()
    time.sleep(0.2)
    started = time.monotonic()
    assert json.loads(request("/stop", {}))["published_to_ros"]
    assert time.monotonic() - started < 0.5, "conduite bloquée par la vidéo"
    for waiter in waiters:
        waiter.join()

    # Fausse caméra : le bridge s'abonne, compresse et sert un JPEG valide.
    fake = subprocess.Popen([sys.executable, "-c", FAKE_CAMERA], env=env)
    try:
        frame = {}

        def got_frame():
            status, headers, data = camera_frame(frame.get("seq", 0))
            if status == 200:
                frame.update(seq=int(headers["X-Frame-Seq"]), headers=headers, data=data)
            return status == 200

        wait_for(got_frame, "Aucune image servie par /camera/frame", seconds=20)
        headers, data = frame["headers"], frame["data"]
        assert headers["Content-Type"] == "image/jpeg"
        assert data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9"
        assert (headers["X-Frame-Width"], headers["X-Frame-Height"]) == ("160", "120")
        decoded = subprocess.run(["djpeg", "-pnm"], input=data, capture_output=True, check=True)
        assert decoded.stderr == b"" and decoded.stdout.startswith(b"P6\n160 120\n255\n")
        # Image suivante : seulement plus récente que la précédente.
        previous = frame["seq"]
        wait_for(got_frame, "Pas d'image suivante", seconds=5)
        assert frame["seq"] > previous

        # Réglages à chaud : 80 px de large -> 80×60.
        refused("/camera/settings", {"width": 10}, 400)
        refused("/camera/settings", {"bitrate": 1}, 400)
        refused("/camera/settings", {"rotate": 45}, 400)
        reply = json.loads(request("/camera/settings", {"width": 80, "quality": 40, "fps": 10}))
        assert reply["settings"] == {"width": 80, "quality": 40, "fps": 10, "rotate": 0}, reply

        def small_frame():
            return got_frame() and frame["headers"]["X-Frame-Width"] == "80"

        wait_for(small_frame, "Réglage width non appliqué", seconds=5)
        assert frame["headers"]["X-Frame-Height"] == "60"
        # Webcam montée en portrait : 80×60 tourné de 90° -> 60×80.
        assert json.loads(request("/camera/settings", {"rotate": 90}))["settings"]["rotate"] == 90

        def portrait_frame():
            return got_frame() and frame["headers"]["X-Frame-Width"] == "60"

        wait_for(portrait_frame, "Rotation non appliquée", seconds=5)
        assert frame["headers"]["X-Frame-Height"] == "80"
        decoded = subprocess.run(["djpeg", "-pnm"], input=frame["data"], capture_output=True, check=True)
        assert decoded.stdout.startswith(b"P6\n60 80\n255\n")
        camera = json.loads(request("/camera/status"))
        assert camera["subscribed"] is True and camera["active"] is True, camera
        assert camera["source"] == {"width": 160, "height": 120, "encoding": "rgb8"}, camera
        frames = camera["frames"]
        assert frames["received"] >= frames["encoded"] >= frames["served"] >= 3, camera
        assert camera["error"] is None, camera
        # Une image ne passe pas par l'observation JSON générique.
        assert "Caméra" in refused("/watch", {"topic": "/image_raw"}, 503)["error"]
        # Sans spectateur pendant 5 s, l'abonnement est retiré.
        wait_for(lambda: json.loads(request("/camera/status"))["subscribed"] is False,
                 "Abonnement caméra conservé sans spectateur", seconds=10)
    finally:
        fake.send_signal(signal.SIGINT)
        try:
            fake.wait(timeout=5)
        except subprocess.TimeoutExpired:
            fake.kill()
    print("Smoke test OK : HTTP, boucle ROS, not ready, refus du mouvement, zéro, "
          "télémétrie, services absents, observation de topic, caméra (JPEG, réglages, "
          "abonnement à la demande).", flush=True)
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
