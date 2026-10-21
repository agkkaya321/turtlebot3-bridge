"""Programmer le TurtleBot3 comme un Arduino : setup() une fois, loop() en boucle.

    from tb3 import Robot

    class Avance(Robot):
        def loop(self):
            self.forward(0.05)

    Avance().run()

À chaque tour (10 par seconde par défaut), run() lit tous les capteurs en une
requête, appelle loop(), puis envoie la consigne de mouvement au bridge. Une
consigne reste valable jusqu'à la suivante : run() la renouvelle à chaque tour,
le bridge arrêtant le robot si elle n'arrive plus pendant 500 ms.
Guide complet : docs/GUIDE_ROBOT.md.
"""

import abc
import argparse
import math
import signal
import sys
import threading
import time

from robot import SOUNDS, BridgeClient, BridgeError, _number

WHEEL_SEPARATION = 0.160
# Limite par défaut du bridge (MAX_SPEED_MPS), utilisée tant que /telemetry ne l'a pas donnée.
DEFAULT_WHEEL_LIMIT = 0.10
# Coupure réseau tolérée (s) avant d'abandonner ; le robot, lui, s'arrête après 500 ms.
OFFLINE_LIMIT = 2.0


def _interrupt(signum, frame):
    raise KeyboardInterrupt


class Robot(abc.ABC):
    """Classe de base : hériter, écrire loop() (obligatoire) et setup() (facultatif)."""

    def __init__(self, url="http://127.0.0.1:8000", hz=10, dry_run=False):
        hz = _number(hz, "hz")
        if not 1 <= hz <= 50:
            raise ValueError("hz doit être compris entre 1 et 50.")
        self.bridge = BridgeClient(url)
        self.hz = hz
        self.dry_run = bool(dry_run)
        self.t = 0.0          # secondes depuis le premier tour
        self.tick = 0         # numéro du tour en cours
        self.state = None     # état courant, changé par goto()
        self._state_since = 0.0
        self._start = None
        self._telemetry = {}
        self._fetched_at = None
        self._command = (0.0, 0.0)
        self._shown = None
        self._every = {}
        self._finished = False
        self._paused = False
        self._offline_since = {}   # par type de requête : lecture ou envoi
        self._last_overrun = -math.inf

    # --- À écrire dans la classe fille ------------------------------------

    def setup(self):
        """Appelée une fois avant le premier tour. Facultative."""

    @abc.abstractmethod
    def loop(self):
        """Appelée à chaque tour : lire les capteurs, choisir une consigne. Ne pas bloquer."""

    # --- Exécution --------------------------------------------------------

    @classmethod
    def main(cls):
        """Lancer depuis la ligne de commande : --url, --hz, --dry-run."""
        parser = argparse.ArgumentParser(description=cls.__doc__)
        parser.add_argument("--url", default="http://127.0.0.1:8000")
        parser.add_argument("--hz", type=float, default=10)
        parser.add_argument("--dry-run", action="store_true",
                            help="Lire les capteurs et afficher les consignes sans bouger")
        args = parser.parse_args()
        cls(url=args.url, hz=args.hz, dry_run=args.dry_run).run()

    def run(self):
        """Boucle principale. Ctrl+C, finish() ou une erreur arrêtent le robot."""
        name = type(self).__name__
        mode = " (dry-run : aucun mouvement)" if self.dry_run else ""
        print(f"{name} : bridge {self.bridge.url}, {self.hz:g} Hz{mode}")
        if threading.current_thread() is threading.main_thread():
            # kill / fermeture du terminal : même arrêt propre que Ctrl+C.
            signal.signal(signal.SIGTERM, _interrupt)
        try:
            if not self.dry_run:
                self._wait_ready()
            self._refresh()
            self._start = time.monotonic()
            self.setup()
            self._start = time.monotonic()
            self._state_since = 0.0
            period = 1.0 / self.hz
            next_tick = self._start
            while not self._finished:
                began = time.monotonic()
                self.t = began - self._start
                self._network(self._refresh)
                if self._paused:
                    self._check_resume()
                if not self._paused:
                    self.loop()
                    self._network(self._send)
                self.tick += 1
                self._pace(began, period)
                next_tick += period
                delay = next_tick - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_tick = time.monotonic()
        except KeyboardInterrupt:
            print("\nArrêt demandé (Ctrl+C).")
        finally:
            self._halt()

    def finish(self):
        """Terminer le programme à la fin de ce tour ; le robot est arrêté."""
        self._finished = True

    def log(self, *values):
        """print() précédé du temps écoulé."""
        print(f"[{self.t:7.2f} s]", *values)

    # --- Mouvement (consigne envoyée à la fin du tour) ---------------------

    def velocity(self, linear, angular=0.0):
        """m/s vers l'avant (négatif = reculer) et rad/s (positif = gauche)."""
        linear = _number(linear, "La vitesse")
        angular = _number(angular, "La rotation")
        half = angular * WHEEL_SEPARATION / 2.0
        left, right = linear - half, linear + half
        limit = self.max_wheel_speed()
        if max(abs(left), abs(right)) > limit + 1e-9:
            raise ValueError(
                f"Consigne trop rapide : roues {left:+.3f} / {right:+.3f} m/s, "
                f"limite ±{limit:.2f} m/s par roue (MAX_SPEED_MPS dans robot.env).")
        self._command = (linear, angular)

    def forward(self, speed):
        """Avancer en ligne droite à speed m/s (négatif = reculer)."""
        self.velocity(speed, 0.0)

    def backward(self, speed):
        """Reculer en ligne droite à speed m/s."""
        self.velocity(-abs(_number(speed, "La vitesse")), 0.0)

    def turn(self, angular):
        """Tourner sur place à angular rad/s (positif = gauche)."""
        self.velocity(0.0, angular)

    def wheels(self, left, right):
        """Vitesse de chaque roue en m/s."""
        left = _number(left, "La roue gauche")
        right = _number(right, "La roue droite")
        self.velocity((left + right) / 2.0, (right - left) / WHEEL_SEPARATION)

    def stop(self):
        """Consigne nulle."""
        self._command = (0.0, 0.0)

    @property
    def command(self):
        """Consigne actuelle : (m/s, rad/s)."""
        return self._command

    def max_wheel_speed(self):
        """Vitesse maximale d'une roue acceptée par le bridge (m/s)."""
        return self._telemetry.get("limits", {}).get("wheel_mps") or DEFAULT_WHEEL_LIMIT

    def max_turn_speed(self):
        """Rotation sur place maximale (rad/s)."""
        return 2.0 * self.max_wheel_speed() / WHEEL_SEPARATION

    # --- Capteurs (photo prise au début du tour) --------------------------

    def _age_ms(self, age_ms):
        late = (time.monotonic() - self._fetched_at) * 1000 if self._fetched_at else 0.0
        return age_ms + late

    def sensor(self, name, max_age=1.0):
        """Données brutes d'un capteur du bridge, ou None si absent ou plus vieux que max_age s."""
        entry = self._telemetry.get("sensors", {}).get(name)
        if entry is None or self._age_ms(entry["age_ms"]) > max_age * 1000:
            return None
        return entry["data"]

    # LiDAR
    def scan(self, max_age=1.0):
        """Balayage : ranges (m, None si invalide), angle_min, angle_increment, range_min, range_max."""
        return self.sensor("scan", max_age)

    def _rays(self):
        """(angle en degrés dans [-180, 180[, distance) pour chaque mesure valide."""
        data = self.scan()
        if data is None:
            return []
        rays = []
        for index, distance in enumerate(data["ranges"]):
            if distance is None:
                continue
            angle = data["angle_min"] + index * data["angle_increment"]
            rays.append((math.degrees(math.atan2(math.sin(angle), math.cos(angle))), distance))
        return rays

    def distance_at(self, angle_deg, half_angle_deg=5):
        """Plus petite distance (m) autour de angle_deg (0 = devant, 90 = gauche), ou None."""
        best = None
        for angle, distance in self._rays():
            gap = (angle - angle_deg + 180) % 360 - 180
            if abs(gap) <= half_angle_deg and (best is None or distance < best):
                best = distance
        return best

    def front_distance(self, half_angle_deg=15):
        """Obstacle le plus proche devant (±half_angle_deg), en m, ou None."""
        return self.distance_at(0, half_angle_deg)

    def closest_obstacle(self):
        """(distance en m, angle en degrés) de l'obstacle le plus proche, ou None."""
        rays = self._rays()
        if not rays:
            return None
        angle, distance = min(rays, key=lambda ray: ray[1])
        return distance, angle

    # Odométrie
    def pose(self, max_age=1.0):
        """Position estimée : x, y (m), yaw_rad, linear_mps, angular_rad_s."""
        return self.sensor("odom", max_age)

    def heading_deg(self):
        """Orientation selon l'odométrie, en degrés dans [-180, 180], ou None."""
        pose = self.pose()
        if pose is None or pose["yaw_rad"] is None:
            return None
        return math.degrees(pose["yaw_rad"])

    # IMU, magnétomètre, roues
    def imu(self, max_age=1.0):
        """yaw_rad, angular_velocity {x,y,z} (rad/s), linear_acceleration {x,y,z} (m/s²)."""
        return self.sensor("imu", max_age)

    def magnetic_field(self, max_age=1.0):
        """tesla {x, y, z}."""
        return self.sensor("magnetic_field", max_age)

    def joint_states(self, max_age=1.0):
        """name, position_rad, velocity_rad_s des deux roues."""
        return self.sensor("joint_states", max_age)

    # Batterie
    def battery(self, max_age=1.0):
        """voltage_v, percentage (0..1 ou None), current_a, present."""
        return self.sensor("battery", max_age)

    def battery_voltage(self):
        """Tension de la batterie en V, ou None."""
        battery = self.battery()
        if battery and battery["voltage_v"] is not None:
            return battery["voltage_v"]
        state = self.sensor_state()
        return state["battery_v"] if state else None

    # Carte OpenCR
    def sensor_state(self, max_age=1.0):
        """bumper, cliff, sonar, illumination, led, button, torque, left_encoder,
        right_encoder, battery_v."""
        return self.sensor("sensor_state", max_age)

    def _state_field(self, field):
        state = self.sensor_state()
        return None if state is None else state[field]

    def button(self):
        """Boutons de l'OpenCR (entier, 0 = aucun), ou None."""
        return self._state_field("button")

    def bumper(self):
        """Pare-chocs (entier, 0 = aucun contact), ou None."""
        return self._state_field("bumper")

    def cliff(self):
        """Capteur de vide (valeur brute), ou None."""
        return self._state_field("cliff")

    def sonar(self):
        """Sonar (valeur brute), ou None."""
        return self._state_field("sonar")

    def illumination(self):
        """Capteur de luminosité (valeur brute), ou None."""
        return self._state_field("illumination")

    def torque(self):
        """True si les moteurs sont alimentés, ou None."""
        return self._state_field("torque")

    def encoders(self):
        """(gauche, droite) en ticks d'encodeur, ou None."""
        state = self.sensor_state()
        return None if state is None else (state["left_encoder"], state["right_encoder"])

    # Autres topics (ESP32…)
    def watch(self, topic):
        """Commencer à recevoir un topic ROS (à appeler dans setup())."""
        return self.bridge.watch(topic)

    def unwatch(self, topic):
        return self.bridge.unwatch(topic)

    def watched(self, topic, max_age=1.0):
        """Dernier message d'un topic observé, ou None si rien de récent."""
        entry = self._telemetry.get("watched", {}).get(topic)
        if entry is None or entry["age_ms"] is None:
            return None
        if self._age_ms(entry["age_ms"]) > max_age * 1000:
            return None
        return entry["data"]

    def telemetry(self):
        """Photo complète renvoyée par le bridge au début du tour."""
        return self._telemetry

    # --- Actions (immédiates ; jusqu'à 3 s d'attente) ----------------------

    def sound(self, value="on"):
        """Son OpenCR : nom de SOUNDS ou 0..5."""
        return self.bridge.sound(SOUNDS.get(value, value))

    def motor_power(self, enabled):
        """Activer (True) ou couper (False) le couple des moteurs."""
        return self.bridge.motor_power(enabled)

    def reset(self):
        """Remettre l'odométrie et l'IMU à zéro (le robot s'arrête)."""
        return self.bridge.reset()

    def status(self):
        """État du bridge : status, reason, ros_alive, supervisor."""
        return self.bridge.status()

    # --- Temps et états ----------------------------------------------------

    def every(self, seconds, key=None):
        """Vrai au premier appel, puis toutes les `seconds` secondes (une horloge par ligne)."""
        if key is None:
            caller = sys._getframe(1)
            key = (caller.f_code.co_filename, caller.f_lineno)
        last = self._every.get(key)
        if last is None or self.t - last >= seconds:
            self._every[key] = self.t
            return True
        return False

    def goto(self, state):
        """Passer à un autre état ; state_time repart de zéro."""
        if state != self.state:
            self.state = state
            self._state_since = self.t

    @property
    def state_time(self):
        """Secondes passées dans l'état courant."""
        return self.t - self._state_since

    def after(self, seconds):
        """Vrai si l'état courant dure depuis au moins `seconds` secondes."""
        return self.state_time >= seconds

    # --- Interne -----------------------------------------------------------

    def _refresh(self):
        self._telemetry = self.bridge.telemetry()
        self._fetched_at = time.monotonic()

    def _send(self):
        linear, angular = self._command
        if self.dry_run:
            if self._command != self._shown:
                self.log(f"[dry-run] consigne {linear:+.3f} m/s, {angular:+.3f} rad/s")
                self._shown = self._command
            return
        try:
            self.bridge.velocity(linear, angular)
        except BridgeError as error:
            if error.code != 503:
                raise
            self._pause(error)

    def _pause(self, error):
        # Comme le bridge, ne jamais reprendre une ancienne consigne après une perte de ready.
        self._command = (0.0, 0.0)
        self._paused = True
        reason = error
        try:
            status = self.status()
            if status.get("status") != "ready":
                reason = status.get("reason")
        except Exception:
            pass
        self.log(f"Robot not ready ({reason}) : pause, reprise automatique.")

    def _check_resume(self):
        try:
            ready = self.bridge.ready() == "ready"
        except OSError:
            return
        if ready:
            self._paused = False
            self.log("Robot ready : reprise.")

    def _network(self, action):
        """Exécuter une requête en tolérant une courte coupure réseau."""
        kind = action.__name__
        try:
            action()
        except OSError as error:   # URLError, timeout, connexion refusée
            now = time.monotonic()
            since = self._offline_since.setdefault(kind, now)
            if since == now:
                self.log(f"Bridge injoignable ({error}) : nouvel essai…")
            elif now - since > OFFLINE_LIMIT:
                raise ConnectionError(
                    f"Bridge injoignable depuis {OFFLINE_LIMIT:g} s : tunnel fermé ou Wi-Fi perdu ? "
                    "(./start.sh doit tourner)") from error
            return
        if self._offline_since.pop(kind, None) is not None:
            self.log("Bridge de nouveau joignable.")

    def _pace(self, began, period):
        spent = time.monotonic() - began
        if spent > period and began - self._last_overrun > 5.0:
            self._last_overrun = began
            self.log(f"Tour trop lent : {spent * 1000:.0f} ms pour {period * 1000:.0f} ms prévus "
                     "(loop() bloquante ou réseau lent).")

    def _wait_ready(self):
        try:
            state = self.bridge.ready()
        except OSError as error:
            raise ConnectionError(
                f"Bridge injoignable sur {self.bridge.url} : lancer ./start.sh d'abord.") from error
        last_report = -math.inf
        while state != "ready":
            if time.monotonic() - last_report > 5.0:
                last_report = time.monotonic()
                print(f"En attente du robot : {self.status().get('reason')}")
            time.sleep(0.5)
            state = self.bridge.ready()

    def _halt(self):
        # Aucune consigne n'a pu partir avant la fin du premier tour.
        if self.dry_run or self.tick == 0:
            return
        last = None
        for _ in range(3):
            try:
                self.bridge.stop()
                print("Robot arrêté.")
                return
            except Exception as error:
                last = error
        print(f"Arrêt non confirmé ({last}) : le bridge arrêtera le robot sous 500 ms.",
              file=sys.stderr)
