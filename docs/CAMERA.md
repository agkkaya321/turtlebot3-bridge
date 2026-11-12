# Caméra USB via le bridge

Matériel détecté sur le robot : **Logitech Brio 105**, `/dev/video0`.
L'utilisateur a confirmé la capture avec `usb_cam`, `mjpeg2rgb`, 640 × 480 à 15 Hz.
L'intégration HTTP est testée en logiciel ; elle reste à vérifier avec cette caméra
sur le robot. Aucune analyse de posture n'est incluse.

Validation de cette version : 15 tests Rust, smoke tests du binaire ARM64 avec
publication ROS synthétique (JPEG, concurrence avec `/stop`, expiration,
récupération, pilote externe, démarrage/relance/arrêt du pilote géré), cinq tests
Python du client/proxy et vérification Chrome de l'aperçu sur grand écran et mobile.
La suite Python générale présente deux problèmes préexistants dans les tests LiDAR
(import après déplacement et fenêtre attendue de 100 cycles contre 20 dans le code).

## Activer après compilation

1. Sur le Mac, à la racine, préparer le binaire avec Docker Desktop :

   ```bash
   ./start.sh build
   ```

2. Sur le robot, les paquets `ros-jazzy-usb-cam` et
   `ros-jazzy-image-transport-plugins` doivent être installés ; l'utilisateur SSH
   doit appartenir au groupe `video`. Cette préparation a déjà été effectuée lors
   du test manuel. Si nécessaire, les installer quand le robot a internet.

3. Par SSH, modifier `~/bridge/robot.env`, en préservant ses réglages existants.
   Ajouter ou remplacer les variables suivantes :

   ```bash
   export CAMERA_ENABLED=true
   export CAMERA_AUTOSTART=true
   export CAMERA_DEVICE=/dev/video0
   export CAMERA_WIDTH=640
   export CAMERA_HEIGHT=480
   export CAMERA_FPS=15
   ```

   Le domaine ROS est celui du bridge (109 dans la configuration du projet).
   Aucun changement du launch TurtleBot3 n'est nécessaire. Si le fichier n'existe
   pas encore, partir de `bridge/robot.env.example` après le premier déploiement.

4. Arrêter avec Ctrl+C le `usb_cam` lancé manuellement, puis sur le Mac :

   ```bash
   ./start.sh stop
   ./start.sh
   ```

   Le lanceur déploie le nouveau binaire, préserve `robot.env` et ouvre l'interface.
   La carte **Caméra** affiche l'aperçu à au plus 5 images/s. Le port HTTP et le
   tunnel existants suffisent ; ROS reste installé uniquement sur le robot.

Pour garder une caméra gérée manuellement ou par un service, choisir
`CAMERA_AUTOSTART=false` et `CAMERA_ENABLED=true`. Le topic doit correspondre à
`CAMERA_RAW_TOPIC` (par défaut `/image_raw`, avec le namespace du robot si défini).

## Supervision et limites

- Découverte pendant cinq secondes avant un lancement automatique. Un éditeur
  existant sur le topic brut **ou** compressé empêche de démarrer un second pilote.
- Le bridge ne termine que le groupe `usb_cam` qu'il a lui-même démarré. Celui-ci
  est arrêté avec le bridge ; un pilote externe reste actif.
- Un pilote géré qui quitte ou ne fournit plus de JPEG valides pendant dix secondes
  est relancé avec un délai progressif de 2 à 30 secondes.
- Seule la dernière image est conservée ; pas d'enregistrement sur disque. Une image
  reçue depuis au moins une seconde n'est plus servie. Le numéro de séquence et
  l'horodatage d'acquisition permettent de détecter des répétitions côté traitement.
- Deux workers HTTP caméra et deux requêtes en attente au maximum ; saturation :
  HTTP 503. La boucle moteur et ses workers HTTP sont séparés. Vidéo et commandes
  partagent toutefois CPU, Wi-Fi et tunnel : commencer avec 640 × 480 à 15 Hz.
- Le bridge relaie les JPEG du plugin ROS ; il ne décode ni ne réencode les images.
  Il vérifie leur format déclaré, leurs marqueurs et leur taille (2 Mio maximum).
  L'âge indiqué mesure la réception dans le bridge, pas la latence complète caméra → Mac.

## Accès Python

Depuis la racine du dépôt, avec le tunnel ouvert (adapter le port à l'URL affichée) :

```python
from client.camera import CameraClient

camera = CameraClient("http://127.0.0.1:8000")
print(camera.status())
frame = camera.frame()  # CameraFrame : jpeg, sequence, age_ms, stamp
# frame.jpeg contient les octets JPEG à transmettre au consommateur d'images.
```

Depuis `client/`, utiliser `from camera import CameraClient`.
Les téléchargements et le futur traitement de posture doivent tourner hors de la
boucle de mouvement. `frame()` lève `BridgeError` (503) si aucune image récente n'est
disponible ; une perte du tunnel produit une erreur réseau. Aucune dépendance Python
externe n'est ajoutée. Les algorithmes métier pourront être placés dans
`client/next_step/`, séparément de ce transport.

## Diagnostic

Via l'URL locale du tunnel : `GET /camera/status` et `GET /camera/frame.jpg`.
La caméra fonctionne même si `/ready` indique `not ready` pour les moteurs.
`disabled` indique que `CAMERA_ENABLED` est absent ou faux ; un changement de
`robot.env` demande un redémarrage du bridge.

Si le topic brut existe mais aucun JPEG n'arrive, vérifier sur le robot :

```bash
source /opt/ros/jazzy/setup.bash
source ~/bridge/robot.env
ros2 topic list -t
ros2 topic hz /image_raw/compressed
```

Adapter le topic si nécessaire. Vérifier le plugin `compressed_image_transport`
et sa configuration JPEG, puis redémarrer `usb_cam` après une installation de plugins.
Consulter `./start.sh log 100` sur le Mac pour les erreurs du pilote.
L'absence de calibration n'empêche pas l'aperçu ; la calibration reste à prévoir
pour des mesures géométriques. `CAMERA_ENABLED=false` désactive le module au
prochain redémarrage.
