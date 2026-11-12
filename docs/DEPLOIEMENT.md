# Compiler sur le Mac, lancer sur le TurtleBot3

Cible : **Linux ARM64 (`aarch64`), Ubuntu 24.04, ROS 2 Jazzy**.
Rust et Docker sont utilisés uniquement sur le Mac. Sur le robot, ROS Jazzy,
les pilotes TurtleBot3 et leurs bibliothèques doivent déjà être installés.
Le binaire utilise ces bibliothèques : il n'embarque pas ROS.

## 1. Compiler (avec internet, avant d'aller sur le réseau du robot)

Le réseau du robot n'a pas internet : compiler **avant** de le rejoindre.
Démarrer Docker Desktop, puis :

```bash
cd /Users/aaa/Desktop/ROS
./start.sh build
```

Le résultat est dans `bridge/dist/` (exécutable ARM64, `run.sh`,
`robot.env.example`, `SHA256SUMS`, `build-info.txt`). Le script exécute les tests
Rust et le smoke test du vrai binaire. Ne pas lancer ce binaire sous macOS.

## 2. Tout lancer depuis le Mac

Connecter le Mac au Wi-Fi du robot, puis :

```bash
cd /Users/aaa/Desktop/ROS
./start.sh
```

Le script :

1. vérifie que le port SSH du robot répond, propose d'installer ta clé SSH une fois,
   puis ouvre une connexion SSH partagée (le mot de passe n'est demandé qu'une fois) ;
2. copie `bridge/dist/` dans `~/bridge` si l'empreinte du binaire diffère, sans
   toucher à `~/bridge/robot.env`. Il arrête d'abord l'ancienne version si elle tourne ;
3. lance un diagnostic : ROS, paquets TurtleBot3, `ROS_DOMAIN_ID`, `TURTLEBOT3_MODEL`,
   `LDS_MODEL`, OpenCR (`/dev/ttyACM0`), LiDAR (`/dev/ttyUSB*`), bibliothèques (`ldd`),
   bridge, bringup, et présence des topics et services attendus ;
4. démarre le bridge en arrière-plan (`~/bridge/bridge.log`) s'il ne tourne pas.
   À la première utilisation, `robot.env` est créé depuis `robot.env.example` ;
5. ouvre le tunnel `127.0.0.1:8000` vers l'API du bridge, puis l'interface web
   sur `http://127.0.0.1:8080` dans le navigateur.

Ctrl+C ferme l'interface et le tunnel, après avoir envoyé un arrêt au robot. Le
bridge **continue** sur le robot ; le relancer plus tard est immédiat.

| Commande | Effet |
|---|---|
| `./start.sh` | Tout ce qui précède |
| `./start.sh check` | Diagnostic seul |
| `./start.sh status` | Bridge en cours ? État HTTP |
| `./start.sh log [n]` | Dernières lignes de `~/bridge/bridge.log` |
| `./start.sh stop` | Arrête le bridge et le bringup qu'il a lancé |
| `./start.sh build` | Recompile dans Docker (internet nécessaire la première fois) |

Variables utiles : `ROBOT_HOST=ubuntu@AUTRE_IP ./start.sh` si l'adresse change,
`UI_PORT`, `LOCAL_PORT`, `NO_BROWSER=1`, `SKIP_CHECK=1`. Si un port est déjà pris,
le suivant libre est utilisé.

## 3. L'interface web

- **Conduite** : pavé directionnel ou `W A S D` / flèches (maintenir), `Espace` = arrêt,
  curseurs de vitesse et de rotation, mode roues indépendantes.
- **LiDAR** en vue de dessus, avec la distance de l'obstacle devant (±15°).
- **Odométrie** avec tracé de la trajectoire.
- **Robot (OpenCR)** : batterie, couple, pare-chocs, boutons, falaise, sonar,
  luminosité, LED, encodeurs. **IMU**, magnétomètre et roues.
- **Caméra** : vidéo en direct de la webcam USB, compressée en JPEG sur le robot ;
  réglages Fluide / Équilibré / Qualité, rotation (webcam montée en portrait),
  pause, capture d'une image. Sous l'image :
  résolution, images/s, taille, débit, temps d'encodage et âge de l'image.
- **Actions** : couple des moteurs, six sons, reset. Un point vert ou rouge indique
  si le service a été détecté sur le robot.
- **Topics ROS** : liste du graphe et observation de n'importe quel topic (ex. ESP32).
- **Système** : diagnostic complet, journal, redémarrage ou arrêt du bridge (via SSH).

Rien n'est chargé depuis internet : l'interface fonctionne sur le réseau isolé du robot.

## 4. Premier déplacement

Placer le robot sur un support stable, roues dégagées, et fermer les autres outils
de commande de vitesse (teleop). Attendre `ready` en haut de l'interface : la
calibration du bringup prend environ 30 s. Si l'état reste `not ready`, la raison
s'affiche à côté. « Moteurs désactivés » : bouton **Activer** dans Actions.

## Si quelque chose ne va pas

| Symptôme | Piste |
|---|---|
| `Robot injoignable` | Mac sur le bon Wi-Fi ? Raspberry allumé ? IP changée → `ROBOT_HOST=` |
| `LDS_MODEL non défini` | L'ajouter dans `~/bridge/robot.env` (`export LDS_MODEL=LDS-02` ou `LDS-01`/`LDS-03` selon le LiDAR) |
| `Bibliothèques manquantes` | Paquets ROS du robot différents de `build-info.txt` ; vérifier le workspace sourcé dans `run.sh` |
| Topics absents | Bringup arrêté, ou `ROS_DOMAIN_ID` différent entre robot.env et le bringup existant |
| Service rouge dans l'interface | Nom différent sur ce robot : `ros2 service list -t`, puis `SOUND_SERVICE=`… dans robot.env |
| `not ready` permanent | Lire la raison ; `./start.sh log` pour les messages du bringup |
| Caméra : « Aucune webcam sur /dev/video0 » | Brancher la webcam ; `v4l2-ctl --list-devices` sur le robot, puis `CAMERA_DEVICE=` dans robot.env |
| Caméra : « usb_cam arrêté » | `./start.sh log` ; groupe `video` (`groups`), paquet `ros-jazzy-usb-cam` |
| Caméra : image verte ou illisible | `CAMERA_PIXEL_FORMAT=mjpeg2rgb` (défaut) ou `yuyv2rgb` dans robot.env |
| Vidéo saccadée | Réglage **Fluide** dans l'interface ; Wi-Fi chargé ou robot loin du point d'accès |
| Caméra : usb_cam refuse 1280×720 | `CAMERA_SOURCE_SIZE=640x480` dans robot.env (modes : `v4l2-ctl --list-formats-ext`) |
| Personne coupée en haut ou en bas | Webcam montée en portrait + rotation 90° dans l'interface, ou reculer le robot |

Le même diagnostic sans `start.sh`, depuis le Mac :

```bash
ssh ubuntu@192.168.1.109 'bash -s -- check' < bridge/tools/robot_ctl.sh
```

La compilation et les tests en conteneur ne valident pas encore le matériel,
les versions exactes installées sur le robot ou les relances de ses pilotes.
