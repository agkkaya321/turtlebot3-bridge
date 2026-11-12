# Programmer le TurtleBot3 avec `tb3.Robot`

On écrit une classe qui hérite de `Robot`, comme un programme Arduino :

- `setup()` est appelée **une fois** au départ (facultative) ;
- `loop()` est appelée **10 fois par seconde** (obligatoire) : elle lit les capteurs
  et choisit ce que fait le robot.

```python
from tb3 import Robot

class Explorateur(Robot):
    def setup(self):
        self.sound("on")

    def loop(self):
        devant = self.front_distance()
        if devant is not None and devant < 0.30:
            self.turn(0.8)         # obstacle : tourner à gauche
        else:
            self.forward(0.08)     # sinon avancer

Explorateur().run()
```

Sans `loop()`, Python refuse de créer le robot (`TypeError: Can't instantiate abstract class`).

## Lancer un programme

1. Dans un premier terminal : `./start.sh` (ouvre le tunnel vers le bridge).
2. Dans un second terminal :

```bash
cd ~/Desktop/ROS/client
python3 exemples/eviter_obstacles.py              # bouge le robot
python3 exemples/eviter_obstacles.py --dry-run    # lit les capteurs, affiche les consignes, ne bouge pas
python3 exemples/capteurs.py --dry-run            # afficher tous les capteurs chaque seconde
```

Options de `Robot.main()` : `--url` (défaut `http://127.0.0.1:8000`), `--hz` (tours par
seconde, défaut 10), `--dry-run`. Dans un script, `MonRobot().run()` fait la même chose
avec les valeurs par défaut, et `MonRobot(hz=20, dry_run=True).run()` les change.

Exemples fournis dans `client/exemples/` : `avancer.py`, `eviter_obstacles.py`, `carre.py`, `capteurs.py`.

## Ce que fait `run()` à chaque tour

```
1. lit tous les capteurs (une requête GET /telemetry)
2. appelle loop()
3. envoie la consigne de mouvement (POST /velocity)
4. attend le tour suivant
```

- **Une consigne reste valable jusqu'à la suivante.** `forward(0.08)` une seule fois suffit
  pour avancer en continu : `run()` la renvoie à chaque tour. `stop()` l'annule.
  Après une pause `not ready` (voir ci-dessous), la consigne repart de zéro : la donner
  dans `loop()` plutôt que dans `setup()` pour que le robot reprenne.
- **`loop()` ne doit pas bloquer** : pas de `time.sleep()` ni de boucle `while` qui attend.
  Pour les durées, utiliser `every()`, `after()` et les états (voir plus bas). Si un tour
  dépasse 100 ms, un avertissement s'affiche.
- **Arrêt du robot** : Ctrl+C, `self.finish()`, une erreur dans ton code ou la perte du
  bridge pendant plus de 2 s. Le robot reçoit toujours `stop` à la fin. Si le Mac perd le
  réseau, le bridge arrête lui-même le robot après 500 ms.
- **Robot `not ready`** (moteurs coupés, bringup relancé…) : `loop()` est suspendue, la
  consigne est remise à zéro, puis le programme reprend seul quand le robot redevient `ready`.
  Il ne reprend jamais une ancienne consigne : c'est au prochain `loop()` d'en donner une.
- Au démarrage, `run()` attend que le robot soit `ready` (sauf en `--dry-run`).
- Ne pas conduire avec l'interface web pendant qu'un programme tourne : la dernière
  consigne reçue gagne.

## Mouvement

Les consignes sont vérifiées immédiatement : une vitesse trop grande lève une `ValueError`
qui explique la limite. Par défaut, **chaque roue est limitée à ±0,10 m/s**
(`MAX_SPEED_MPS` dans `~/bridge/robot.env`, au plus 0,22 m/s).

| Méthode | Effet | Exemple |
|---|---|---|
| `forward(v)` | Avancer à `v` m/s (négatif = reculer) | `self.forward(0.05)` |
| `backward(v)` | Reculer à `v` m/s | `self.backward(0.05)` |
| `turn(w)` | Tourner sur place à `w` rad/s, positif = gauche | `self.turn(-0.5)` (droite) |
| `velocity(v, w)` | Avancer et tourner en même temps (courbe) | `self.velocity(0.05, 0.4)` |
| `wheels(g, d)` | Vitesse de chaque roue en m/s | `self.wheels(0.03, 0.06)` |
| `stop()` | Consigne nulle | |
| `command` | Consigne actuelle `(m/s, rad/s)` | `v, w = self.command` |
| `max_wheel_speed()` | Limite d'une roue (m/s) donnée par le bridge | `0.1` |
| `max_turn_speed()` | Rotation sur place maximale (rad/s) | `1.25` avec 0,10 m/s |

Repères : 1 rad/s ≈ 57°/s ; un quart de tour = π/2 ≈ 1,57 rad. En courbe, la roue
extérieure va plus vite : `velocity(0.08, 0.5)` donne 0,04 et 0,12 m/s, refusé avec la
limite de 0,10.

## Capteurs

Tous les capteurs sont lus **une fois au début du tour** : appeler plusieurs fois la même
fonction dans `loop()` ne fait pas de requête supplémentaire.

Règle commune : **une fonction renvoie `None` si le capteur est absent ou si sa donnée a
plus d'une seconde** (`max_age=1.0`, modifiable). Toujours tester `None` avant de comparer :

```python
d = self.front_distance()
if d is not None and d < 0.3: ...
```

### LiDAR (`/scan`)

Angles en degrés : **0 = devant, 90 = gauche, -90 = droite, 180 = derrière**.

| Méthode | Renvoie |
|---|---|
| `front_distance(half_angle_deg=15)` | Distance (m) de l'obstacle le plus proche devant, à ±15° |
| `distance_at(angle_deg, half_angle_deg=5)` | Distance la plus courte autour d'un angle |
| `closest_obstacle()` | `(distance_m, angle_deg)` de l'obstacle le plus proche tout autour |
| `scan()` | Données brutes : `ranges` (m, `None` si mesure invalide), `angle_min`, `angle_increment` (rad), `range_min`, `range_max` |

```python
gauche = self.distance_at(90)
droite = self.distance_at(-90)
if gauche is not None and droite is not None:
    self.turn(0.5 if gauche > droite else -0.5)   # tourner vers le côté le plus libre

proche = self.closest_obstacle()
if proche:
    distance, angle = proche
    self.log(f"obstacle à {distance:.2f} m, {angle:.0f}°")
```

Les mesures trop proches ou trop lointaines pour le capteur valent `None` et sont ignorées.
**À vérifier au premier essai** : mettre la main devant le robot avec `capteurs.py` et
contrôler que `front_distance()` diminue (le 0° dépend du montage du LiDAR).

### Odométrie (`/odom`)

Position estimée à partir des roues, depuis le démarrage ou le dernier `reset()`.

| Méthode | Renvoie |
|---|---|
| `pose()` | `{"x", "y"}` (m), `"yaw_rad"` (orientation), `"linear_mps"`, `"angular_rad_s"` (vitesses mesurées) |
| `heading_deg()` | Orientation en degrés, de -180 à 180 (0 = direction au départ, positif = gauche) |

```python
p = self.pose()
if p and abs(p["x"]) > 0.5:     # 50 cm parcourus vers l'avant
    self.finish()
```

L'odométrie dérive avec le temps (glissements) : précise sur quelques mètres, pas plus.

### IMU (`/imu`)

| Méthode | Renvoie |
|---|---|
| `imu()` | `"yaw_rad"` (orientation du gyroscope), `"angular_velocity"` `{x, y, z}` (rad/s), `"linear_acceleration"` `{x, y, z}` (m/s²) |

```python
imu = self.imu()
if imu and abs(imu["angular_velocity"]["z"]) > 1.0:
    self.log("rotation rapide")
```

Robot posé à plat : `linear_acceleration.z` ≈ 9,8 (gravité). Un choc se voit sur `x` ou `y`.

### Magnétomètre (`/magnetic_field`)

| Méthode | Renvoie |
|---|---|
| `magnetic_field()` | `{"tesla": {"x", "y", "z"}}` |

Les moteurs et la batterie le perturbent : utile pour détecter un aimant, peu fiable comme boussole.

### Roues (`/joint_states`)

| Méthode | Renvoie |
|---|---|
| `joint_states()` | `"name"` (`wheel_left_joint`, `wheel_right_joint`), `"position_rad"`, `"velocity_rad_s"` |

Distance parcourue par une roue ≈ angle (rad) × 0,033 m (rayon de la roue du Burger).

### Batterie (`/battery_state`)

| Méthode | Renvoie |
|---|---|
| `battery_voltage()` | Tension en V (≈ 12,6 chargée, recharger vers 11) |
| `battery()` | `"voltage_v"`, `"percentage"` (0 à 1, ou `None` si inconnu), `"current_a"`, `"present"` |

```python
v = self.battery_voltage()
if v is not None and v < 11.0 and self.every(30):
    self.sound("low_battery")
```

### Carte OpenCR (`/sensor_state`)

| Méthode | Renvoie |
|---|---|
| `torque()` | `True` si les moteurs sont alimentés |
| `button()` | Boutons de l'OpenCR, entier (0 = aucun appuyé) |
| `encoders()` | `(gauche, droite)` en ticks ; 4096 ticks par tour de roue ≈ 0,05 mm par tick |
| `bumper()`, `cliff()`, `sonar()`, `illumination()` | Entrées des capteurs optionnels de l'OpenCR |
| `sensor_state()` | Tout ce qui précède, plus `"led"` et `"battery_v"` |

```python
def loop(self):
    if self.button():          # démarrer quand on appuie sur un bouton de l'OpenCR
        self.goto("roule")
```

Le Burger de base n'a ni pare-chocs, ni capteur de vide, ni sonar, ni capteur de lumière :
ces valeurs restent à 0 sans accessoire branché. **À vérifier** : quelle valeur de
`button()` correspond à quel bouton (appuyer en regardant `capteurs.py` ou l'interface web).

### Autres topics ROS (ESP32, capteur ajouté…)

Le bridge peut suivre n'importe quel topic ROS (8 au maximum) dont le type est standard
(`std_msgs`, `sensor_msgs`, `geometry_msgs`, `nav_msgs`…).

| Méthode | Effet |
|---|---|
| `watch(topic)` | Commencer à recevoir le topic : à appeler dans `setup()` |
| `watched(topic)` | Dernier message reçu (dictionnaire), ou `None` |
| `unwatch(topic)` | Arrêter de le suivre |

```python
def setup(self):
    self.watch("/esp32/lux")          # par exemple un std_msgs/Float32

def loop(self):
    msg = self.watched("/esp32/lux")
    if msg is not None and msg["data"] < 50:
        self.stop()                    # trop sombre
```

La liste des topics existants est dans l'onglet « Topics ROS » de l'interface web, ou via
`self.bridge.topics()`.

### Tout le reste

`self.telemetry()` renvoie la photo complète du tour (capteurs, topics suivis, services
détectés, limites). `self.sensor(nom)` lit un capteur par son nom brut.

## Actions

Ces actions sont exécutées **tout de suite** et attendent la réponse du robot (jusqu'à
3 s) : les appeler dans `setup()`, ou rarement dans `loop()` (avec `every()` par exemple).

| Méthode | Effet |
|---|---|
| `sound(nom)` | Son de l'OpenCR : `"off"`, `"on"`, `"low_battery"`, `"error"`, `"button1"`, `"button2"` (ou 0 à 5) |
| `motor_power(True/False)` | Alimenter ou couper les moteurs. Coupés, le robot est `not ready` et `loop()` est suspendue |
| `reset()` | Remettre l'odométrie et l'IMU à zéro (le robot s'arrête) |
| `status()` | État du bridge : `status`, `reason`… |

En `--dry-run`, ces actions sont réellement exécutées (seul le mouvement est désactivé).

## Temps et états

`loop()` ne doit jamais attendre : on mesure le temps à la place.

| Outil | Signification |
|---|---|
| `self.t` | Secondes depuis le premier tour |
| `self.tick` | Numéro du tour (0, 1, 2…) |
| `every(s)` | Vrai au premier appel, puis toutes les `s` secondes (une horloge par ligne de code) |
| `goto("nom")` | Passer dans un état ; son chronomètre repart de zéro |
| `self.state` | État courant (`None` tant que `goto()` n'a pas été appelé) |
| `self.state_time` | Secondes passées dans l'état courant |
| `after(s)` | Vrai si l'état courant dure depuis au moins `s` secondes |
| `finish()` | Terminer le programme à la fin du tour |
| `log(...)` | Comme `print()`, précédé du temps écoulé |

Une suite d'actions s'écrit avec des états (voir `client/exemples/carre.py`) :

```python
class AllerRetour(Robot):
    def setup(self):
        self.goto("aller")

    def loop(self):
        if self.state == "aller":
            self.forward(0.06)
            if self.after(3):
                self.goto("demi-tour")
        elif self.state == "demi-tour":
            self.turn(1.0)
            if self.after(3.14):          # π rad à 1 rad/s
                self.goto("retour")
        elif self.state == "retour":
            self.forward(0.06)
            if self.after(3):
                self.finish()
```

Les attributs de ton choix (`self.cotes = 0` dans `setup()`) servent de mémoire entre deux tours.

## Suivi LiDAR NextStep

`client/next_step/main.py` active l'état `UserFollowState` (identifiant 1,
nom `user_follow`) et appelle sa méthode `loop()` à chaque cycle. Ce programme
commande désormais les moteurs lorsqu'une cible est détectée.

L'extraction, indépendante du robot, se trouve dans `client/next_step/lidar.py` :

1. Convertir les rayons en coordonnées cartésiennes dans le repère du scan
   (x devant, y à gauche) et garder `x > 0` et `R < 3` mètres. La ROI est un
   demi-disque avant : la limitation latérale à ±0,5 m est supprimée.
   `ROI_MAX_DISTANCE` dans `lidar.py` règle ce rayon. Il s'agit de la distance
   euclidienne depuis le LiDAR (`R = sqrt(x*x + y*y)`), distincte de la distance
   de Manhattan utilisée pour la vitesse. Les points à 3 m ou au-delà sont
   exclus avant la formation des clusters.
2. Regrouper les rayons consécutifs distants de moins de 15 cm. Un rayon invalide
   ou hors ROI coupe le cluster. La jonction du début et de la fin d'un scan
   à 360° est prise en compte.
3. Garder les clusters dont le diamètre (distance maximale entre deux points)
   est compris entre 5 et 20 cm inclus. Le centre est la moyenne des points.
4. Former des paires de candidats dont les centres sont espacés de 10 à 65 cm,
   avec une différence de profondeur x de 40 cm maximum et un écart latéral y
   d'au moins 8 cm. Le milieu des centres donne la position de chaque paire.
5. Sans historique, sélectionner la paire dont le milieu est le plus proche
   du LiDAR. En suivi, sélectionner celle dont le milieu est le plus proche
   de la dernière cible observée, à 50 cm maximum. Si les deux meilleurs scores
   diffèrent de moins de 15 cm, la cible reste ambiguë et le robot s'arrête.
   Ainsi, quatre candidats ou plus n'impliquent plus systématiquement un arrêt.

Si aucune paire ne peut être associée en suivi, une jambe seule peut être
retenue à proximité de la dernière cible, avec la même limite de saut et le
même critère d'ambiguïté. À l'acquisition, un cluster seul n'est utilisé que
s'il est l'unique candidat. Deux candidats incompatibles ne sont pas moyennés.

La mémoire `TargetTracker` conserve la dernière position pendant 1 seconde
sans observation acceptée, afin de retrouver la cible après une brève perte.
Elle ne produit aucune consigne à partir de cette position mémorisée seule.
Après expiration, une nouvelle acquisition est possible et l'ancienne moyenne
de distance est effacée. Les numéros des clusters changent entre scans :
l'association utilise leurs positions, pas ces numéros.

Ces paramètres de sélection sont des heuristiques réglables dans `lidar.py` :

| Constante | Valeur | Rôle |
|---|---|---|
| `PAIR_MIN_SEPARATION` / `PAIR_MAX_SEPARATION` | 0,10 / 0,65 m | Écart entre centres |
| `PAIR_MAX_DEPTH_DIFFERENCE` | 0,40 m | Tolérance de décalage avant/arrière |
| `PAIR_MIN_LATERAL_SEPARATION` | 0,08 m | Écart latéral minimal |
| `SELECTION_MARGIN` | 0,15 m | Différence minimale entre les deux meilleurs scores |
| `TRACK_MAX_JUMP` | 0,50 m | Distance maximale à la dernière position observée |
| `TRACK_TIMEOUT` | 1 s | Oubli de la cible sans observation acceptée |

Les réglages sont en tête de
`client/next_step/finite_state_machine/states/user_follow_state.py` :

| Constante | Valeur | Rôle |
|---|---|---|
| `DISTANCE_THRESHOLD` | 1,5 m | Distance de Manhattan souhaitée |
| `REACTIVITY_CONSTANT` | 0,5 | Gain proportionnel |
| `SLIDING_WINDOW_SIZE` | 100 | Nombre maximal de mesures conservées |
| `SCAN_MAX_AGE` | 0,5 s | Âge maximal accepté du scan |

À chaque cycle valide, l'état ajoute `abs(x_target) + abs(y_target)` dans son
propre buffer. La moyenne utilise les mesures disponibles au démarrage, puis
les 100 dernières valeurs. La vitesse est `0.5 * (moyenne - 1.5)`, bornée par
`robot.max_wheel_speed()` : `forward(v)` si positive, `backward(-v)` si négative,
`stop()` si nulle. Aucune rotation n'est commandée. `Robot.run()` transmet la
consigne au bridge après la boucle ; aucun accès ROS direct n'est nécessaire.

Un scan absent ou périmé, ou une cible indéterminée, entraîne une consigne nulle
et vide le buffer de distance. L'entrée et la sortie de l'état font de même
et effacent aussi la mémoire de position. Les mesures
sont ajoutées par cycle, même si le scan n'a pas changé entre deux cycles.
À 10 Hz, la fenêtre représente environ 10 secondes et retarde la réaction aux
changements de distance : la consigne de 1,5 m n'est pas une garantie de sécurité.

L'extraction est testée sur des scans synthétiques ; la sélection est aussi
vérifiée sur des centres retranscrits des journaux utilisateur, sans disposer
des rayons réels correspondants. Le comportement corrigé reste à valider sur
le robot. Des objets de taille similaire peuvent être retenus comme jambes ;
le suivi n'identifie pas une personne
et n'intègre pas d'évitement d'obstacles, notamment pendant le recul. Le repère
du LiDAR doit être aligné avec celui du robot pour interpréter x comme l'avant.

### Diagnostic du suivi

Le journal du suivi est activé par défaut (`DEBUG_FOLLOW = True` dans
`user_follow_state.py`). La commande habituelle, depuis `client/`, suffit :

```bash
python3 next_step/main.py
```

Toutes les secondes (`DEBUG_INTERVAL`), une seule ligne résume le suivi :

```text
Jambes détectées — distance : 1.20 m — ajustement : recule.
Jambes détectées — distance : 1.50 m — position maintenue.
Jambes non détectées — arrêt.
```

La distance affichée est la distance euclidienne instantanée entre le LiDAR et
la cible sélectionnée. La commande continue d'utiliser la distance de Manhattan
lissée ; l'ajustement affiché correspond à la consigne, pas à une mesure de
mouvement effectif. Le mode `--dry-run` ajoute `[simulation, sans mouvement]`.

Les détails des clusters, la cause d'une perte de cible, les angles et les temps
restent disponibles dans `state.diagnostics`, sans affichage supplémentaire.
Les valeurs de contrôle sont accessibles via `state.r_smooth`, `state.raw_speed`
et `state.speed`. L'affichage simple peut être désactivé avec `DEBUG`.

`Main.verbose = False` masque les messages techniques de démarrage, les
transitions initiales, les consignes chiffrées en simulation et les avertissements
« Tour trop lent ». Les erreurs de connexion et les messages d'arrêt restent
visibles. `Robot` conserve ses diagnostics habituels pour les autres programmes ;
les durées du dernier tour restent accessibles dans `robot.cycle_timings_ms`.

## Erreurs fréquentes

| Message | Cause |
|---|---|
| `Bridge injoignable sur http://127.0.0.1:8000` | `./start.sh` ne tourne pas (tunnel fermé) |
| `En attente du robot : …` | Robot `not ready` ; la raison est affichée (calibration ≈ 30 s, moteurs désactivés…) |
| `Consigne trop rapide` | Une roue dépasse la limite ; réduire la vitesse ou la rotation |
| `Tour trop lent` | `loop()` contient un `sleep()`, une action lente, ou le Wi-Fi est lent |
| `TypeError: '<' not supported … NoneType` | Capteur à `None` : tester `is not None` avant de comparer |

## Accès bas niveau

`self.bridge` est un `BridgeClient` (fichier `client/robot.py`) qui appelle directement l'API HTTP
du bridge. Il sert aux scripts séquentiels sans `loop()` (`demo.py`), mais ne renouvelle
pas les consignes tout seul : préférer `tb3.Robot`.
