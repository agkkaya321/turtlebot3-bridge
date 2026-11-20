# Analyse de posture NextStep

L'analyse s'exécute sur le Mac. Le Raspberry Pi fournit les JPEG via le bridge
existant ; aucune installation de MediaPipe sur le robot n'est nécessaire.

## Préparer le Mac avec internet

Dans un environnement virtuel Python compatible avec MediaPipe :

```bash
# Seulement si aucun environnement virtuel n'existe encore :
python3 -m venv .venv
.venv/bin/python -m pip install -r client/next_step/posture_analysis/requirements.txt
curl -fL -o client/next_step/posture_analysis/pose_landmarker_lite.task \
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task
```

`opencv-contrib-python` fournit `cv2` et est aussi utilisé par MediaPipe : ne pas
installer en parallèle une autre distribution OpenCV dans cet environnement.
Le modèle et `.venv/` sont ignorés par Git. Préparer les deux avant de rejoindre
le réseau isolé du robot. Aucun téléchargement automatique n'a lieu au lancement.
Un autre modèle peut être indiqué par `--pose-model CHEMIN` ou `POSE_MODEL`.

## Lancer l'analyse

Après avoir ouvert le tunnel et l'interface avec `./start.sh`, dans un second terminal :

```bash
.venv/bin/python client/next_step/main.py --dry-run \
  --url http://127.0.0.1:8000 --ui-url http://127.0.0.1:8080
```

Utiliser les deux ports affichés par `start.sh` s'ils diffèrent. Relancer le serveur
de l'interface s'il était déjà ouvert avant la mise à jour. Aucune recompilation
Rust n'est nécessaire pour cette modification.

NextStep commence désormais dans `posture_checking` (état 2), avec une consigne
de mouvement nulle. `--dry-run` inhibe les commandes moteurs, mais utilise le
vrai flux caméra. La carte **Caméra** affiche les points visibles et les connexions
du squelette directement sur sa vue principale, avec l'image exacte analysée.
Lorsque MediaPipe est actif, l'interface utilise ce flux local et ne demande pas
un deuxième flux brut au robot. Si l'analyse devient inactive ou expire, elle
revient automatiquement à la caméra brute. **Pause** fige la vue et suspend ses
requêtes d'images ; le détecteur Python continue son travail. **Capture** enregistre
l'image affichée avec ses points. Le cadrage suit la rotation et les dimensions
de l'image, en portrait comme en paysage.

L'analyse continue sans limite de temps lorsqu'aucune personne n'est détectée.
La console affiche « La personne n'est pas sur l'image » uniquement au changement
de situation, sans compte à rebours. Ctrl+C ou une sortie d'état libèrent le
détecteur. **L'interface, le bridge et le Raspberry Pi restent allumés.**

Les logs techniques OpenCV/MediaPipe (informations, avertissements et debug)
sont filtrés, y compris les messages natifs C++. Les erreurs restent visibles.
Une caméra coupée, un flux invalide ou l'absence de réponse de MediaPipe sont
signalés sans arrêt automatique lié à l'absence de personne.
Les images affichées expirent après 3 secondes pour éviter de conserver une
ancienne posture à l'écran si le processus disparaît.

Le suivi LiDAR reste disponible explicitement avec `--state user_follow` ;
sans `--dry-run`, ce mode peut déplacer le robot.

## Organisation et routes HTTP

- `BridgeClient.camera_frame(after)` : `GET /camera/frame?after=N` par le tunnel,
  renvoie `(jpeg, frame_nb)` ou `None` sur HTTP 204, avec un délai HTTP de 4 s.
- `decode_live_stream.py` : `LiveStreamDecoder.get_image()` décode le JPEG et
  fournit `(bgr_frame, timestamp_ms)` ; `bgr_to_rgb()` convertit en RGB. Les
  timestamps de réception sont strictement croissants. Après un 204, le curseur
  est remis à zéro pour récupérer un bridge redémarré.
- `posture_detector.py` remplace `mediapipe_test.py`. Un thread acquiert les
  images, fournit `rgb_frame` et `timestamp_ms` à `detect_async()` et publie le
  dernier résultat. Le callback conserve l'image exacte associée aux points.
  Les opérations HTTP et MediaPipe ne bloquent pas la boucle FSM à 10 Hz.
- `POST /local/posture` sur **le serveur UI du Mac** reçoit
  `{timestamp_ms, image, poses}` : JPEG base64 et jusqu'à une pose de 33 points
  `{x, y, visibility}`. `{stopped: true}` efface le résultat.
- `GET /local/posture` renvoie le dernier résultat avec `active` et `age_ms`,
  ou `{active: false, image: null, poses: []}` s'il a expiré. Les données sont
  conservées uniquement en mémoire et ne transitent pas de nouveau par le robot.

Les anciens exemples `decode_image.py` et `openCV_test.py` restent des scripts
de tutoriel indépendants. Ils ne sont pas exécutés par la FSM.

API de référence : [MediaPipe PoseLandmarker — LIVE_STREAM et detect_async](https://developers.google.com/edge/api/mediapipe/python/mp/tasks/vision/PoseLandmarker).
Il peut ignorer des images lorsqu'il est occupé ; l'UI dessine donc sur l'image
du callback, et non sur une autre image du flux.

## Vérifier sans robot

```bash
.venv/bin/python -B -m unittest discover -s client -p 'test_*.py'
python3 -B -m unittest discover -s ui -p 'test_*.py'
```

Les tests couvrent l'acquisition, le décodage JPEG et la conversion des couleurs
(si OpenCV est installé), l'attente sans délai d'arrêt, les résultats anciens,
le filtrage des logs, la sortie de l'état et l'expiration de l'affichage.
Ils ne constituent pas une validation du
suivi de posture sur la C270 ni un score clinique.

Vérification locale effectuée avec MediaPipe 0.10.35 et OpenCV 4.14.0 :
vrai callback LIVE_STREAM sur des images sans personne servies par un faux
bridge HTTP et effacement de l'UI à la sortie. Affichage
du squelette vérifié dans Chrome avec 33 points synthétiques. La détection d'une
personne et le suivi sur le flux réel de la C270 restent à confirmer.
