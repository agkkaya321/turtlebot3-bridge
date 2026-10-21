"""Client Python sans dépendance externe. À exécuter sur ton ordinateur."""

import json
import math
import sys
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

# Plafond constructeur du Burger ; le bridge applique sa propre limite (MAX_SPEED_MPS).
BURGER_MAX_SPEED = 0.22
SOUNDS = {"off": 0, "on": 1, "low_battery": 2, "error": 3, "button1": 4, "button2": 5}


def _number(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} doit être un nombre.")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} doit être fini.")
    return value


class BridgeError(RuntimeError):
    """Réponse d'erreur du bridge ; code = statut HTTP (400 consigne refusée, 503 not ready…)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class BridgeClient:
    """Accès direct à l'API HTTP du bridge. Pour programmer un comportement, voir tb3.Robot."""

    def __init__(self, url="http://127.0.0.1:8000"):
        self.url = url.rstrip("/")
        self._linear = 0.0
        self._angular = 0.0
        self._http = build_opener(ProxyHandler({}))

    # --- Requêtes HTTP -------------------------------------------------

    def _get(self, path, timeout=0.3):
        with self._http.open(self.url + path, timeout=timeout) as response:
            return json.load(response)

    def _post(self, path, payload, timeout=0.3):
        request = Request(
            self.url + path,
            data=json.dumps(payload, allow_nan=False).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._http.open(request, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise BridgeError(error.code, f"Bridge HTTP {error.code} : {detail}") from error

    # --- État -----------------------------------------------------------

    def ready(self):
        """Renvoie exactement 'ready' ou 'not ready'. Erreur si bridge inaccessible."""
        with self._http.open(self.url + "/ready", timeout=0.3) as response:
            state = response.read().decode("utf-8").strip()
        if state not in ("ready", "not ready"):
            raise RuntimeError(f"État inattendu du bridge : {state!r}")
        return state

    def status(self):
        """Détails : état, raison et action du superviseur."""
        return self._get("/status")

    def wait_until_ready(self, timeout=60.0):
        """Attendre le robot sans envoyer de consigne de mouvement."""
        timeout = float(timeout)
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("Timeout fini, positif ou nul requis.")
        deadline = time.monotonic() + timeout
        while True:
            if self.ready() == "ready":
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Le robot est toujours not ready.")
            time.sleep(min(0.2, remaining))

    # --- Capteurs -------------------------------------------------------

    def telemetry(self):
        """Tous les capteurs : odom, sensor_state, battery, imu, scan, magnetic_field,
        joint_states, ainsi que les topics observés, les services et les limites."""
        return self._get("/telemetry", timeout=1.0)

    def sensor(self, name, max_age=1.0):
        """Données d'un capteur, ou None s'il est absent ou trop ancien (secondes)."""
        entry = self.telemetry()["sensors"].get(name)
        if entry is None or entry["age_ms"] > max_age * 1000:
            return None
        return entry["data"]

    def pose(self):
        """Odométrie : {'x', 'y', 'yaw_rad', 'linear_mps', 'angular_rad_s'}."""
        return self.sensor("odom")

    def battery(self):
        return self.sensor("battery")

    def scan(self):
        """LiDAR : ranges (m, None si invalide), angle_min, angle_increment."""
        return self.sensor("scan")

    def front_distance(self, half_angle_deg=15):
        """Plus petite distance valide devant le robot, ou None."""
        data = self.scan()
        if data is None:
            return None
        half = math.radians(half_angle_deg)
        best = None
        for index, distance in enumerate(data["ranges"]):
            if distance is None:
                continue
            angle = data["angle_min"] + index * data["angle_increment"]
            angle = math.atan2(math.sin(angle), math.cos(angle))
            if abs(angle) <= half and (best is None or distance < best):
                best = distance
        return best

    def topics(self):
        return self._get("/topics", timeout=1.0)["topics"]

    def watch(self, topic):
        """Suivre n'importe quel topic (ex. capteur ESP32) dans telemetry()['watched']."""
        return self._post("/watch", {"topic": topic}, timeout=4.0)

    def unwatch(self, topic):
        return self._post("/unwatch", {"topic": topic}, timeout=4.0)

    # --- Services du robot ----------------------------------------------

    def motor_power(self, enabled):
        """Activer (True) ou couper (False) le couple des moteurs."""
        return self._post("/motor_power", {"enabled": bool(enabled)}, timeout=4.0)

    def sound(self, value=1):
        """Jouer un son OpenCR : 0..5 ou un nom de SOUNDS."""
        value = SOUNDS.get(value, value)
        return self._post("/sound", {"value": int(value)}, timeout=4.0)

    def reset(self):
        """Service reset du pilote (odométrie / IMU) ; arrête le robot avant."""
        return self._post("/reset", {}, timeout=4.0)

    # --- Mouvement ------------------------------------------------------

    def velocity(self, linear, angular=0.0):
        """m/s vers l'avant et rad/s (positif = tourner à gauche).

        Une commande expire après 500 ms côté robot. Utiliser wait()
        pour la renouveler pendant une durée, ou rappeler velocity().
        """
        linear = _number(linear, "La vitesse")
        angular = _number(angular, "La rotation")
        if abs(linear) > BURGER_MAX_SPEED:
            raise ValueError(f"Vitesse attendue entre -{BURGER_MAX_SPEED} et {BURGER_MAX_SPEED} m/s.")
        # En cas d'échec, un wait() ultérieur ne reprend pas l'ancienne vitesse.
        self._linear = self._angular = 0.0
        feedback = self._post("/velocity", {"linear_mps": linear, "angular_rad_s": angular})
        if feedback.get("published_to_ros") is not True:
            raise RuntimeError(f"Publication ROS non confirmée : {feedback}")
        self._linear, self._angular = linear, angular
        return feedback

    def forward(self, speed):
        """m/s : positif = avancer, négatif = reculer, zéro = arrêter."""
        return self.velocity(speed, 0.0)

    def turn(self, angular):
        """Rotation sur place en rad/s (positif = gauche)."""
        return self.velocity(0.0, angular)

    def wheels(self, left, right):
        """Vitesse de chaque roue en m/s."""
        left = _number(left, "La roue gauche")
        right = _number(right, "La roue droite")
        return self.velocity((left + right) / 2.0, (right - left) / 0.160)

    def stop(self):
        """Demander immédiatement une vitesse nulle."""
        return self.velocity(0.0, 0.0)

    def wait(self, seconds):
        """Renouveler la consigne pendant cette durée, sans thread caché."""
        seconds = float(seconds)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Durée finie, positive ou nulle requise.")
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.velocity(self._linear, self._angular)
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.10, remaining))

    def __enter__(self):
        self.stop()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self.stop()
        except Exception as error:
            if exc_type is None:
                raise
            # Conserver l'erreur initiale, même si le réseau est déjà perdu.
            print(f"Arrêt non confirmé : {error}", file=sys.stderr)
        return False
