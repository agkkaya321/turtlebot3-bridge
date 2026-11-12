# Bridge Rust → TurtleBot3 : conduite, capteurs, services et relance ROS

Le bridge se compile **sur le Mac avec Docker**, puis se copie sur le Raspberry Pi.
**Aucune installation de Rust ni de Docker n'est nécessaire sur le robot.**

**Usage normal : `../start.sh` depuis le Mac**, sur le réseau du robot. Le script
copie le bridge s'il a changé, vérifie le robot, lance le bridge, ouvre le tunnel
SSH et l'interface web (voir [docs/DEPLOIEMENT.md](../docs/DEPLOIEMENT.md)).

État des essais : compilation Docker ARM64, 33 tests Rust, 31 tests Python et smoke
test du vrai binaire (HTTP, télémétrie, services absents, observation de topic, caméra
avec une fausse webcam ROS : JPEG décodé par libjpeg, réglages, abonnement à la demande).
`start.sh` et l'interface ont été testés de bout en bout contre un **faux robot**
(conteneur Ubuntu 24.04/Jazzy avec sshd et un nœud imitant le pilote). **Aucun essai
sur le robot réel n'a encore été effectué.**

## Fonctions du robot couvertes

| Fonction TurtleBot3 | Topic / service ROS | API du bridge |
|---|---|---|
| Conduite (avance + rotation) | `/cmd_vel` (`TwistStamped` ou `Twist`) | `POST /velocity`, `/wheels`, `/speed`, `/stop` |
| Odométrie | `/odom` | `GET /telemetry` → `sensors.odom` |
| État OpenCR : couple, pare-chocs, boutons, falaise, sonar, luminosité, LED, encodeurs, batterie | `/sensor_state` | `sensors.sensor_state` |
| Batterie | `/battery_state` | `sensors.battery` |
| IMU | `/imu` | `sensors.imu` |
| LiDAR | `/scan` | `sensors.scan` (portées invalides = `null`) |
| Magnétomètre | `/magnetic_field` | `sensors.magnetic_field` |
| Roues (articulations) | `/joint_states` | `sensors.joint_states` |
| Couple des moteurs | service `/motor_power` (`std_srvs/SetBool`) | `POST /motor_power` |
| Sons OpenCR (0 à 5) | service `/sound` (`turtlebot3_msgs/Sound`) | `POST /sound` |
| Reset (odométrie / IMU) | service `/reset` (`std_srvs/Trigger`) | `POST /reset` |
| N'importe quel autre topic (ex. capteur ESP32) | découvert dans le graphe ROS | `GET /topics`, `POST /watch`, `/unwatch` |
| Caméra USB (usb_cam) | `/image_raw` (`sensor_msgs/Image`) | `GET /camera/frame`, `/camera/status`, `POST /camera/settings` |

Les noms de services suivent ceux du nœud `turtlebot3_node` de Jazzy. Ils sont à
confirmer sur le robot (`ros2 service list -t`, ou le diagnostic de `start.sh`).
L'interface signale chaque service non détecté par un point rouge.

L'observation générique accepte les types des paquets compilés dans le bridge :
`std_msgs`, `std_srvs`, `geometry_msgs`, `nav_msgs`, `sensor_msgs`, `turtlebot3_msgs`.
Un capteur ESP32 publiant par exemple un `std_msgs/Float32` ou un
`sensor_msgs/Illuminance` est donc lisible sans recompiler. Pour un autre paquet,
l'ajouter à `IDL_PACKAGE_FILTER` dans le `Dockerfile`, puis recompiler.

## API HTTP

| Requête | Réponse |
|---|---|
| `GET /ready` | Texte `ready` ou `not ready`, HTTP 200 dans les deux cas |
| `GET /status` | JSON `status`, `reason`, `ros_alive`, `supervisor` |
| `GET /telemetry` | Capteurs (`age_ms` + `data`), topics observés, services disponibles, consigne en cours, limites |
| `GET /topics` | Topics du graphe ROS et leurs types (actualisé chaque seconde) |
| `POST /velocity` `{"linear_mps": 0.05, "angular_rad_s": 0.3}` | Publication ; rotation positive = gauche |
| `POST /wheels` `{"left_mps": -0.03, "right_mps": 0.03}` | Converti en vitesse + rotation (L = 0,160 m) |
| `POST /speed` `{"speed_mps": 0.03}` | Ancienne API, ligne droite seulement |
| `POST /stop` `{}` | Vitesse nulle, toujours acceptée |
| `POST /motor_power` `{"enabled": true}` | Active ou coupe le couple ; `false` publie zéro avant |
| `POST /sound` `{"value": 1}` | 0 off, 1 on, 2 batterie faible, 3 erreur, 4 bouton 1, 5 bouton 2 |
| `POST /reset` `{}` | Publie zéro puis appelle le service reset |
| `POST /watch` / `/unwatch` `{"topic": "/esp32/lux"}` | Observer au plus 8 topics, lus dans `/telemetry` → `watched` (pas les images) |
| `GET /camera/frame?after=N` | JPEG plus récent que l'image N (en-têtes `X-Frame-Seq`, `-Width`, `-Height`, `-Quality`, `-Encode-Ms`, `-Age-Ms`) ; `204` si rien en 2,5 s |
| `GET /camera/status` | Pilote, abonnement, images reçues / encodées / servies, i/s, kbit/s, dernière image, réglages, erreur |
| `POST /camera/settings` `{"width": 480, "quality": 60, "fps": 15, "rotate": 0}` | Réglages du flux à chaud (chaque champ facultatif) ; `rotate` 0/90/180/270 dans le sens horaire |

Les appels de service attendent au plus 2,5 s une réponse, sans bloquer la boucle
ROS ni `/status`. `motor_power` et `sound` ne demandent pas `ready` : activer les
moteurs est justement le remède à « Moteurs désactivés ».

## Client Python

Programmer un comportement : `../client/tb3.py`, sur le modèle Arduino (`setup()` puis
`loop()` 10 fois par seconde). Guide complet, capteur par capteur :
[docs/GUIDE_ROBOT.md](../docs/GUIDE_ROBOT.md).

```python
from tb3 import Robot

class Explorateur(Robot):
    def loop(self):
        d = self.front_distance()
        if d is not None and d < 0.30:
            self.turn(0.8)
        else:
            self.forward(0.08)

Explorateur().run()     # Ctrl+C : le robot s'arrête
```

Exemples : `../client/exemples/` (`--dry-run` pour lire les capteurs sans bouger).
`../client/robot.py` (`BridgeClient`) appelle directement l'API HTTP, sans boucle.
Aucune dépendance externe ; tests : `cd ../client && python3 -m unittest`.

## Readiness

`ready` exige tous les critères suivants :

- un abonné ROS compatible au topic de vitesse ;
- des messages `/odom` et `/sensor_state` horodatés et datant de moins d'une seconde ;
- une odométrie contenant des valeurs finies et une orientation non nulle ;
- `sensor_state.torque = true`, donc des moteurs signalés comme activés ;
- une mesure de batterie finie et positive ;
- une publication ROS réussie et une boucle de contrôle encore active, sans redémarrage en cours.

Le LiDAR, l'IMU et les autres capteurs ne conditionnent pas `ready` : leur absence
se voit dans l'interface (« absent » ou « ancien ») sans bloquer la conduite.
Ce sont des vérifications logicielles : elles ne certifient ni l'état mécanique ni
l'absence d'obstacle. Le bridge ne freine pas devant un obstacle.

## Vitesse et sécurité

- Chaque roue est limitée à **±0,10 m/s** par défaut (`MAX_SPEED_MPS` dans `robot.env`,
  au plus 0,22 m/s, maximum du Burger). La rotation sur place est donc limitée à
  1,25 rad/s par défaut. Une consigne qui dépasse la limite sur une roue est refusée (HTTP 400).
- Une consigne expire après **500 ms** : le serveur publie alors zéro. L'interface
  la renvoie toutes les 100 ms tant qu'une touche est maintenue, et envoie un arrêt au
  relâchement, à la perte du focus et sur toute erreur.
- La perte de readiness annule la consigne ; une ancienne consigne n'est jamais restaurée.
- `published_to_ros: true` signifie que la publication a réussi, pas que le moteur a
  exécuté la consigne.

Pour le premier essai, dégager les roues sur un support stable, fermer teleop et les
autres publishers de vitesse, puis vérifier l'arrêt et le sens du mouvement à faible vitesse.

## Démarrage et relance automatiques du bringup

ROS 2 n'a pas de serveur central à lancer comme `roscore`. Avec `ROS_AUTOSTART=true`
(défaut), le bridge lance `ros2 launch turtlebot3_bringup robot.launch.py` s'il ne
détecte aucun pilote après cinq secondes, le relance s'il se termine ou si l'odométrie
et l'état du robot disparaissent durablement (après trente secondes de calibration),
avec un délai de 2, 4, 8… jusqu'à 60 s entre les tentatives.

Si les pilotes tournent déjà (bringup manuel ou service), le bridge les observe sans
les tuer ni en lancer un second. Pour observer seulement, `ROS_AUTOSTART=false`.

## Caméra

```
usb_cam ──/image_raw (rgb8 1280×720, ~2,7 Mo)──► boucle ROS (dépose la dernière image)
                                                    │
                       thread d'encodage ◄──────────┘   (seulement si quelqu'un regarde)
                       convert.rs : RVB/BGR/YUYV… -> RVB, réduction par moyenne de zone,
                                    rotation (webcam montée en portrait)
                       jpeg.rs    : YCbCr 4:2:0, DCT 8×8, quantification, Huffman
                                                    │  ~15 Ko à 480 px, qualité 60
HTTP GET /camera/frame?after=N ◄────────────────────┘  toujours la dernière image
```

- **Pilote** (`camera/driver.rs`) : `ros2 run usb_cam usb_cam_node_exe` avec
  `pixel_format:=mjpeg2rgb` (guide du cours), lancé 5 s après le démarrage si aucun
  nœud ne publie le topic et si la webcam existe ; relancé avec délai croissant s'il
  s'arrête ; arrêté avec le bridge. Un pilote déjà lancé (ex. `usbcam_robot.launch.py`)
  est utilisé tel quel.
- **Compression** (`camera/convert.rs`, `camera/jpeg.rs`) : encodeur JPEG baseline
  écrit pour le bridge, sans bibliothèque. Testé contre libjpeg (`djpeg`) : même PSNR
  que `cjpeg` à qualité égale, tailles non multiples de 16, gris, couleurs saturées.
- **Transport** : le client demande l'image suivante après avoir reçu la précédente
  (`after=N`). Aucune file ne se forme dans le tunnel SSH : si le Wi-Fi ralentit, la
  cadence baisse mais l'image reste récente. L'attente se fait hors des lecteurs HTTP
  de la conduite (4 attentes simultanées au plus).
- **Économie** : sans requête depuis 5 s, le bridge se désabonne de l'image brute et
  n'encode plus rien.
- **Isolation** : aucune erreur caméra ne remonte à la boucle de conduite ; un réglage
  invalide dans `robot.env` garde la valeur par défaut.

Test à la main, tunnel ouvert par `start.sh` :

```bash
curl -s http://127.0.0.1:8000/camera/status | python3 -m json.tool
curl -s -o image.jpg http://127.0.0.1:8000/camera/frame && open image.jpg
```

## Configuration sur le robot (`~/bridge/robot.env`)

`run.sh` charge ROS Jazzy, `~/turtlebot3_ws/install/setup.bash` s'il existe, les
variables TurtleBot3 exportées dans `~/.bashrc` (`LDS_MODEL`, `ROS_DOMAIN_ID`…,
car une session SSH non interactive ne lit pas ce fichier), puis `robot.env`, prioritaire.

| Variable | Défaut / usage |
|---|---|
| `ROS_DOMAIN_ID`, `TURTLEBOT3_MODEL`, `LDS_MODEL` | Valeurs du robot ; le diagnostic les affiche |
| `ROS_AUTOSTART` | `true` ; `false` pour observer sans lancer de pilotes |
| `ROBOT_NAMESPACE` | Vide ; ex. `robot101` préfixe topics, services et bringup |
| `CMD_VEL_TYPE` | `stamped` ; `twist` pour une installation utilisant `Twist` |
| `MAX_SPEED_MPS` | `0.10` ; limite par roue, au plus `0.22` |
| `BRIDGE_BIND` | `127.0.0.1:8000` (garder cette valeur pour le tunnel de `start.sh`) |
| `CMD_VEL_TOPIC`, `ODOM_TOPIC`, `SENSOR_STATE_TOPIC`, `BATTERY_TOPIC`, `IMU_TOPIC`, `SCAN_TOPIC`, `MAGNETIC_FIELD_TOPIC`, `JOINT_STATES_TOPIC` | Noms par défaut, préfixés par le namespace |
| `SOUND_SERVICE`, `MOTOR_POWER_SERVICE`, `RESET_SERVICE` | Idem pour les services |
| `CAMERA_AUTOSTART` | `true` : lancer usb_cam si aucune caméra n'est publiée |
| `CAMERA_DEVICE`, `CAMERA_PIXEL_FORMAT` | `/dev/video0`, `mjpeg2rgb` |
| `CAMERA_SOURCE_SIZE`, `CAMERA_SOURCE_FPS` | `1280x720`, `15` : demandés à usb_cam (16:9 = toute la largeur du capteur) |
| `CAMERA_TOPIC` | `/image_raw` (préfixé par le namespace) |
| `CAMERA_WIDTH`, `CAMERA_QUALITY`, `CAMERA_FPS`, `CAMERA_ROTATE` | `480`, `60`, `15`, `0` : flux envoyé (modifiable depuis l'interface) ; largeur avant rotation |

La [configuration Burger Jazzy](https://github.com/ROBOTIS-GIT/turtlebot3/blob/jazzy/turtlebot3_bringup/param/burger.yaml)
utilise `TwistStamped`. Si `ros2 topic type /cmd_vel` donne `geometry_msgs/msg/Twist`,
choisir `CMD_VEL_TYPE=twist`. Une incompatibilité de type reste `not ready`.

## Organisation des fichiers

| Fichier | Rôle |
|---|---|
| `src/main.rs` | Assemble les modules et réessaie l'initialisation ROS en cas d'erreur |
| `src/config.rs` | Variables d'environnement, limites et délais |
| `src/http.rs` | Routes HTTP |
| `src/state.rs` | État partagé, commandes et télémétrie |
| `src/health.rs` | Fraîcheur des capteurs et état des moteurs (readiness) |
| `src/sensors.rs` | Conversion des messages capteurs en JSON |
| `src/services.rs` | Services son, couple moteur et reset, sans blocage |
| `src/watch.rs` | Observation générique de topics |
| `src/supervisor.rs` | Lance, surveille et relance son groupe de processus bringup |
| `src/ros.rs` | Boucle ROS de 50 ms : capteurs, consignes, services, expiration |
| `src/velocity.rs` | Cinématique différentielle et messages `Twist`/`TwistStamped` |
| `src/camera/` | Caméra : `driver.rs` (usb_cam), `convert.rs`, `jpeg.rs` (compression), `hub.rs` (état partagé, thread d'encodage), `http.rs` (routes) |
| `tools/robot_ctl.sh` | Diagnostic, démarrage, arrêt et journal, exécuté sur le robot via SSH |
| `tools/smoke_test.py` | Démarrage réel et vérification HTTP dans Docker sans matériel |
| `run.sh`, `robot.env.example` | Chargement de l'environnement du robot |
| `Dockerfile`, `build-docker.sh` | Compilation Linux ARM64 avec ROS Jazzy dans Docker |
| `../start.sh`, `../ui/`, `../client/` | Lancement depuis le Mac, interface web, client Python |

## Vérifications locales

```bash
python3 -B -m unittest discover -s ../client -p 'test_*.py'   # client Python
bash build-docker.sh                                         # tests Rust + smoke test
```
