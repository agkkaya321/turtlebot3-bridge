# Bridge Rust → TurtleBot3 : conduite, capteurs, services et relance ROS

Le bridge se compile **sur le Mac avec Docker**, puis se copie sur le Raspberry Pi.
**Aucune installation de Rust ni de Docker n'est nécessaire sur le robot.**

**Usage normal : `../start.sh` depuis le Mac**, sur le réseau du robot. Le script
copie le bridge s'il a changé, vérifie le robot, lance le bridge, ouvre le tunnel
SSH et l'interface web (voir [docs/DEPLOIEMENT.md](../docs/DEPLOIEMENT.md)).

Validations initiales : compilation Docker ARM64, tests Rust et Python et smoke
test du vrai binaire (HTTP, télémétrie, services absents, observation de topic).
`start.sh` et l'interface ont été testés de bout en bout contre un **faux robot**
(conteneur Ubuntu 24.04/Jazzy avec sshd et un nœud imitant le pilote).
L'utilisateur rapporte depuis un premier lancement NextStep sur le robot et une
capture caméra Brio 105 fonctionnelle avec `usb_cam`. Cela ne valide pas encore
le suivi physique ni le nouveau transport caméra HTTP sur le matériel réel.

## Fonctions du robot couvertes

| Fonction TurtleBot3 | Topic / service ROS | API du bridge |
|---|---|---|
| Conduite (avance + rotation) | `/cmd_vel` (`TwistStamped` ou `Twist`) | `POST /velocity`, `/wheels`, `/speed`, `/stop` |
| Odométrie | `/odom` | `GET /telemetry` → `sensors.odom` |
| État OpenCR : couple, pare-chocs, boutons, falaise, sonar, luminosité, LED, encodeurs, batterie | `/sensor_state` | `sensors.sensor_state` |
| Batterie | `/battery_state` | `sensors.battery` |
| IMU | `/imu` | `sensors.imu` |
| LiDAR | `/scan` | `sensors.scan` (portées invalides = `null`) |
| Caméra USB (optionnelle) | `/image_raw/compressed` (`sensor_msgs/CompressedImage`, JPEG) | `GET /camera/status`, `/camera/frame.jpg` |
| Magnétomètre | `/magnetic_field` | `sensors.magnetic_field` |
| Roues (articulations) | `/joint_states` | `sensors.joint_states` |
| Couple des moteurs | service `/motor_power` (`std_srvs/SetBool`) | `POST /motor_power` |
| Sons OpenCR (0 à 5) | service `/sound` (`turtlebot3_msgs/Sound`) | `POST /sound` |
| Reset (odométrie / IMU) | service `/reset` (`std_srvs/Trigger`) | `POST /reset` |
| N'importe quel autre topic (ex. capteur ESP32) | découvert dans le graphe ROS | `GET /topics`, `POST /watch`, `/unwatch` |

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
| `GET /camera/status` | État caméra : `disabled`, `waiting`, `ready` ou `stale`, âge, topic, supervision |
| `GET /camera/frame.jpg` | Dernier JPEG binaire ; HTTP 503 si désactivé, absent, vieux de ≥1 s ou workers occupés |
| `POST /velocity` `{"linear_mps": 0.05, "angular_rad_s": 0.3}` | Publication ; rotation positive = gauche |
| `POST /wheels` `{"left_mps": -0.03, "right_mps": 0.03}` | Converti en vitesse + rotation (L = 0,160 m) |
| `POST /speed` `{"speed_mps": 0.03}` | Ancienne API, ligne droite seulement |
| `POST /stop` `{}` | Vitesse nulle, toujours acceptée |
| `POST /motor_power` `{"enabled": true}` | Active ou coupe le couple ; `false` publie zéro avant |
| `POST /sound` `{"value": 1}` | 0 off, 1 on, 2 batterie faible, 3 erreur, 4 bouton 1, 5 bouton 2 |
| `POST /reset` `{}` | Publie zéro puis appelle le service reset |
| `POST /watch` / `/unwatch` `{"topic": "/esp32/lux"}` | Observer au plus 8 topics, lus dans `/telemetry` → `watched` |

Les appels de service attendent au plus 2,5 s une réponse, sans bloquer la boucle
ROS ni `/status`. `motor_power` et `sound` ne demandent pas `ready` : activer les
moteurs est justement le remède à « Moteurs désactivés ».

La caméra dispose de son propre nœud ROS et de deux workers HTTP avec une file bornée.
Elle conserve une seule image (maximum 2 Mio), sans passer par le JSON de `/watch`.
Les réponses JPEG sont `no-store`, avec les en-têtes `X-Camera-Sequence`,
`X-Camera-Age-Ms` (âge depuis réception par le bridge) et `X-Camera-Stamp`
(horodatage ROS d'acquisition). L'aperçu web demande au plus cinq images par seconde ;
il suspend ses requêtes quand l'onglet est masqué ou l'aperçu en pause.
Cette version propose des instantanés JPEG répétés, pas d'endpoint MJPEG continu.
La caméra n'intervient pas dans la readiness des moteurs. Activation et dépannage :
[docs/CAMERA.md](../docs/CAMERA.md).

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
| `CAMERA_ENABLED` | `false` ; `true` active la réception caméra |
| `CAMERA_AUTOSTART` | `false` ; `true` lance/supervise `usb_cam` si la caméra est activée |
| `CAMERA_DEVICE` | `/dev/video0` ; chemin USB, éventuellement `/dev/v4l/by-id/…` |
| `CAMERA_WIDTH`, `CAMERA_HEIGHT`, `CAMERA_FPS` | `640`, `480`, `15` ; limites 1920 × 1080, 30 Hz, mode à confirmer sur la caméra |
| `CAMERA_RAW_TOPIC` | `/image_raw`, préfixé par `ROBOT_NAMESPACE` ; JPEG sur ce nom + `/compressed` |
| `CMD_VEL_TOPIC`, `ODOM_TOPIC`, `SENSOR_STATE_TOPIC`, `BATTERY_TOPIC`, `IMU_TOPIC`, `SCAN_TOPIC`, `MAGNETIC_FIELD_TOPIC`, `JOINT_STATES_TOPIC` | Noms par défaut, préfixés par le namespace |
| `SOUND_SERVICE`, `MOTOR_POWER_SERVICE`, `RESET_SERVICE` | Idem pour les services |

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
| `src/camera.rs` | Réception JPEG, fraîcheur, HTTP dédié et supervision optionnelle de `usb_cam` |
| `src/supervisor.rs` | Lance, surveille et relance son groupe de processus bringup |
| `src/ros.rs` | Boucle ROS de 50 ms : capteurs, consignes, services, expiration |
| `src/velocity.rs` | Cinématique différentielle et messages `Twist`/`TwistStamped` |
| `tools/robot_ctl.sh` | Diagnostic, démarrage, arrêt et journal, exécuté sur le robot via SSH |
| `tools/smoke_test.py` | Démarrage réel et vérification HTTP dans Docker sans matériel |
| `tools/camera_smoke_test.py` | Publication ROS synthétique vers l'API JPEG du vrai binaire |
| `run.sh`, `robot.env.example` | Chargement de l'environnement du robot |
| `Dockerfile`, `build-docker.sh` | Compilation Linux ARM64 avec ROS Jazzy dans Docker |
| `../start.sh`, `../ui/`, `../client/` | Lancement depuis le Mac, interface web, client Python |

## Vérifications locales

```bash
python3 -B -m unittest discover -s ../client -p 'test_*.py'   # client Python
bash build-docker.sh                                         # tests Rust + smoke test
```
