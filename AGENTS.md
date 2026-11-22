# Contexte de travail — NextStep / TurtleBot3 Bridge

## Projet et source de vérité

- Échanger en français avec l'utilisateur.
- Projet **NextStep**, auteurs **Ali Gökkaya et Jason Condrea**.
- La racine contient `start.sh`, `bridge/`, `client/`, `ui/`, `docs/` et les
  slides locales dans `slides/dist/`.
- La présentation (`slides/dist/index.html` et tableau `d0` dans
  `slides/dist/assets/index-DwZMrydP.js`) décrit les objectifs suivants :
  1. Fabrication et prototypage.
  2. Caméra : suivi de posture et de position en temps réel ; score envisagé
     selon la stabilité et la lordose.
  3. Capteurs portés : fréquence cardiaque en BPM et saturation en oxygène.
  4. Détermination du prochain pas à partir de la posture et des paramètres
     vitaux ; laser indiquant au sol une cible pour chaque pied successivement.
  5. Conclusion de présentation.
- Les animations et valeurs vitales des slides sont simulées. Les objectifs
  présentés ne sont pas des capacités déjà développées ou validées.
- Les anciens chemins `src/nextstep/`, `setup/`, `compose.yaml` et les commandes
  `colcon` ne décrivent pas ce dépôt. Ne pas réintroduire l'ancienne architecture
  ROS Python pour suivre une documentation historique.

## Architecture actuelle

- **Mac** : client Python et interface web, communiquant en HTTP avec le robot
  via un tunnel SSH. ROS et `rclpy` ne sont pas nécessaires sur le Mac.
- **Robot** : TurtleBot3 Burger, Raspberry Pi sous Ubuntu 24.04 ARM64, ROS 2
  Jazzy, OpenCR et LiDAR. Le README vise un LDS-03 ; confirmer le matériel réel.
  ROS, les pilotes et leurs bibliothèques doivent déjà être installés.
- **`bridge/`** : bridge Rust ROS 2 ↔ HTTP, compilé pour Linux ARM64 avec
  `bridge/Dockerfile` et Docker sur le Mac. Rust et Docker ne sont pas requis
  sur le robot ; le binaire utilise les bibliothèques ROS présentes sur celui-ci.
- **`start.sh`** : connexion SSH, copie de `bridge/dist/` dans `~/bridge`,
  diagnostic, lancement du bridge, tunnel HTTP et ouverture de l'interface.
  Préparer le binaire avant de rejoindre le réseau isolé du robot.
- **`client/robot.py`** : `BridgeClient`, accès direct à l'API HTTP.
- **`client/tb3.py`** : classe `Robot`, avec `setup()` puis `loop()` à 10 Hz par
  défaut ; mouvements, capteurs et services. Le client utilise la bibliothèque
  standard Python, sans dépendance externe.
- **`client/next_step/`** : code métier NextStep et machine à états en cours
  de construction. Placer les nouveaux comportements du projet ici.
- **`client/exemples/`** et **`client/demo.py`** : exemples de lecture de capteurs
  et de mouvements ; certains commandent réellement les moteurs.
- **`ui/`** : serveur Python local et interface HTML/JavaScript sans CDN,
  utilisables sans accès internet. Habillage HyperLuv (TemplateMo), polices et
  styles locaux dans `ui/assets/`, quatre vues (pilotage, capteurs, topics ROS,
  système). `python3 -B ui/server.py --preview --port 8080` permet un aperçu
  sans accès au robot ; ce mode bloque les commandes côté serveur. Les changements
  de vue relâchent la conduite ; les raccourcis de déplacement sont limités au pilotage.
- **`slides/dist/`** : présentation web compilée avec animations 3D. Conserver
  ces fichiers intacts sauf demande portant sur les slides ; les sources de
  développement de la présentation ne sont pas fournies.

## État du développement

- Le bridge, le client et l'interface sont implémentés. `bridge/README.md`
  rapporte des validations en conteneur et contre un faux robot, mais pas encore
  sur le robot réel. Ne pas déduire une validation matérielle de la présence
  du binaire ou de tests logiciels réussis.
- `client/next_step/main.py` conserve la FSM dans `self.fsm` et appelle sa
  méthode `loop()` à chaque cycle de `Robot` (10 Hz par défaut).
- Les états présents sont `initial`, `posture_checking`, `user_follow`,
  `laser_aiming_left` et `laser_aiming_right`. `user_follow` remplace
  `moving_backward` (identifiant 1) et commande désormais les déplacements.
  L'état de posture analyse la caméra avec MediaPipe sur le Mac ; les actions
  de laser restent des messages de console.
  Chaque état dispose de `enter()`, `loop()`, `exit()` et de `self.robot`.
  Le mécanisme de transition par identifiant est intégré ; les conditions de
  transition métier restent à définir.
- Le suivi LiDAR utilise `client/next_step/leg_detection/lidar.py` pour extraire une ou deux
  jambes candidates dans un demi-disque avant de rayon strictement inférieur
  à 3 m depuis le LiDAR (`x > 0`, sans limite latérale supplémentaire).
  La limite radiale est réglée par `ROI_MAX_DISTANCE`. `UserFollowState` applique
  une distance de Manhattan, une moyenne sur 100 cycles (fenêtre partielle au
  démarrage), un gain de 0,5 et une consigne de distance de 1,5 m. La vitesse
  est bornée par `Robot.max_wheel_speed()`.
- La sélection LiDAR compare les paires de candidats de largeur 5–20 cm :
  écart de 10–65 cm, différence de profondeur ≤40 cm, écart latéral ≥8 cm.
  Elle choisit la paire la plus proche à l'acquisition, puis la plus proche
  de la dernière cible observée (saut maximal 50 cm). Deux scores séparés
  de moins de 15 cm restent ambigus. Une jambe seule peut être suivie près
  de la cible précédente ; sans historique, elle doit être l'unique candidat.
  `TargetTracker` oublie sa cible après 1 s sans observation acceptée.
  Absence de cible, ambiguïté ou scan vieux de plus de 0,5 s : arrêt et buffer
  de distance vidé, même si la position précédente est encore mémorisée.
  L'entrée et la sortie de l'état remettent consigne, mémoire et buffer à zéro.
  `--state user_follow` active cet état et peut déplacer le robot sans `--dry-run`.
  `Main.setup()` active désormais `posture_checking` par défaut, à vitesse nulle.
  Un premier lancement du suivi sur le robot est rapporté par l'utilisateur,
  avec des tours dépassant 100 ms ; la détection des jambes et le suivi physique
  restent à confirmer. Tests automatisés sur scans synthétiques et sélection
  vérifiée sur des centres retranscrits des logs (pas de replay de scans réels) ; pas
  d'identification de personne ni d'évitement d'obstacles intégré.
- Le journal de `UserFollowState` est activé par défaut, une fois par seconde
  (`DEBUG`, `DEBUG_INTERVAL`) : une ligne indiquant jambes détectées
  ou non, distance euclidienne instantanée à la cible et ajustement
  (avance/recule/position maintenue). En simulation, le message le précise.
  Les détails restent en mémoire (`diagnostics`, `r_smooth`, `raw_speed`,
  `speed`). `Main.verbose = False` masque les diagnostics techniques et les
  avertissements de durée ; les erreurs de connexion et d'arrêt restent visibles.
- Caméra confirmée par l'utilisateur : **Logitech C270 HD**, branchée en USB
  au Raspberry Pi du robot pour filmer la personne qui s'entraîne. La série 2,
  tâche 6, utilise ce modèle avec `usb_cam` et `pixel_format:=mjpeg2rgb` :
  https://github.com/nembrinj/protofablab/blob/main/2026/assignments/AN_02/html/AN_02_ROS.html
- Le bridge expose le flux caméra en JPEG via `GET /camera/frame?after=N`.
  `client/next_step/posture_analysis/decode_live_stream.py` l'acquiert et le
  convertit BGR → RGB. `posture_detector.py` remplace `mediapipe_test.py` et
  exécute MediaPipe LIVE_STREAM sur le Mac, hors de la boucle FSM.
  `posture_checking` maintient une consigne nulle et continue sans limite de
  temps sans personne détectée, sans compte à rebours ni arrêt pour absence.
  L'absence est signalée dans la console uniquement au changement de situation.
  Les logs techniques natifs OpenCV/MediaPipe sont filtrés ; les erreurs restent
  visibles. Les images anciennes continuent d'expirer pour éviter un affichage figé.
  Le programme libère le détecteur à la sortie ; le bridge et l'UI restent ouverts.
  `POST/GET /local/posture` sur le serveur UI transporte en mémoire l'image
  analysée et ses 33 points ; l'affichage expire après 3 s. La caméra principale
  affiche ce flux avec les points, sans deuxième vue ni acquisition brute UI
  simultanée ; elle revient au flux brut si l'analyse est inactive. Pause et
  Capture s'appliquent à cette vue unique. URL UI configurable
  par `--ui-url`. OpenCV/MediaPipe et le modèle `.task` sont requis uniquement
  pour l'analyse de posture ; voir `docs/POSTURE.md`. Pas de validation matérielle
  de cette analyse ni de score clinique implémenté.
- Capteurs portés, commande du laser, algorithmes de posture et de choix du pas,
  ainsi que leurs interfaces restent à préciser.
- Ne pas présenter un score clinique ou une recommandation de pas comme validés.

## Connexion et configuration

- Adresse SSH par défaut : `ubuntu@192.168.1.109`, configurable avec
  `ROBOT_HOST`. Confirmer l'adresse et l'accès au réseau sur place.
- API sur le robot : `127.0.0.1:8000`. Tunnel local sur le port 8000 et interface
  sur le port 8080 par défaut ; `start.sh` choisit un port suivant libre si
  nécessaire. Utiliser les URL affichées par le script.
- Variables du lanceur : `ROBOT_HOST`, `ROBOT_SSH_PORT`, `LOCAL_PORT`, `UI_PORT`,
  `NO_BROWSER=1`, `SKIP_CHECK=1` ; voir `start.sh` pour leur comportement.
- Configuration active : `~/bridge/robot.env`, préservée au déploiement.
  Le modèle `bridge/robot.env.example` définit le domaine ROS **109**, le modèle
  `burger`, `CMD_VEL_TYPE=stamped`, `ROS_AUTOSTART=true` et
  `BRIDGE_BIND=127.0.0.1:8000`. Adapter aux valeurs réelles du robot et des pilotes.
- `bridge/run.sh` charge ROS Jazzy, le workspace TurtleBot3 s'il existe, reprend
  les variables TurtleBot3 de `~/.bashrc`, puis charge `robot.env`, prioritaire.
- Le Mac passe par HTTP/SSH ; il n'a pas à découvrir le robot par DDS.
- Garder les identifiants hors du code et de cette documentation. `sshRobot.md`
  est un fichier local éventuel, ignoré par Git ; ne pas supposer sa présence.

## Commandes de référence

Depuis la racine du dépôt, sur le Mac :

```bash
./start.sh build         # Docker : tests Rust, compilation ARM64 et smoke test
./start.sh               # déploiement, bridge, tunnel et interface
./start.sh check         # diagnostic du robot via SSH
./start.sh status        # état du bridge
./start.sh log 100       # dernières lignes du journal
./start.sh stop          # arrête le bridge et le bringup qu'il a lancé
ROBOT_HOST=ubuntu@AUTRE_IP ./start.sh
```

- Docker Desktop doit être démarré pour compiler ; internet est nécessaire
  pour récupérer les images et dépendances non disponibles localement.
- Ne pas exécuter le binaire Linux de `bridge/dist/` directement sous macOS.
- `./start.sh` agit sur le robot : ce n'est pas une simple vérification locale.
- Ctrl+C ferme l'interface et le tunnel après une demande d'arrêt du mouvement ;
  le bridge continue sur le robot. `./start.sh stop` arrête le bridge.
- Les commandes SSH peuvent proposer l'installation d'une clé via `ssh-copy-id`.

Pour consulter les slides uniquement, sans connexion au robot :

```bash
python3 -m http.server 5174 --bind 127.0.0.1 --directory slides/dist
```

Ouvrir ensuite `http://127.0.0.1:5174`.

## Vérifications et conventions

- Préférer des fonctions Python indépendantes du transport pour les calculs
  métier. Utiliser `Robot` ou `BridgeClient` pour accéder au robot.
- Ne pas ajouter de bibliothèque de vision/ML sans besoin concret, ni installer
  `rclpy` par pip sur macOS pour contourner l'architecture du bridge.
- Tests locaux sans robot, depuis la racine :

```bash
python3 -B -m unittest discover -s client -p 'test_*.py'
python3 -B -m unittest discover -s bridge/tools -p 'test_*.py'
```

- Après modification du bridge Rust, `./start.sh build` exécute les tests Rust
  et le smoke test HTTP du vrai binaire dans Docker. La sortie est générée dans
  `bridge/dist/` ; le script met également à jour `bridge/Cargo.lock` depuis
  l'artefact. Ne pas modifier manuellement les fichiers générés.
- Pour les scripts shell modifiés, utiliser `bash -n` et les tests adaptés.
  Vérifier l'interface dans le navigateur si son comportement est modifié.
- Adapter les vérifications au changement ; une modification documentaire ne
  nécessite ni compilation Docker ni lancement sur le robot.
- Éviter plusieurs compilations simultanées écrivant dans `bridge/dist/`.
- Ne pas versionner environnements virtuels, caches, identifiants, configuration
  propre au robot, logs ou données de personnes. Consulter `.gitignore` : les
  slides et artefacts compilés sont actuellement ignorés, ainsi que les motifs
  globaux `*.toml`, `*.xml` et `*.iml`. Vérifier les fichiers suivis avant un ajout.

## Commandes matérielles et limites

- Ne pas lancer de commande de mouvement ou de laser sur le matériel pour
  une simple vérification du code ou de l'environnement.
- Les premiers essais de mouvement se font à faible vitesse, roues dégagées
  sur un support stable, sans autre programme publiant des consignes de vitesse.
- Limite par défaut : **±0,10 m/s par roue**, configurable via `MAX_SPEED_MPS`
  jusqu'à 0,22 m/s. Une consigne expire après **500 ms** ; le bridge publie alors
  une vitesse nulle. Cela ne constitue pas une validation de l'arrêt physique.
- Le bridge ne freine pas automatiquement devant un obstacle : le comportement
  utilisateur doit le gérer. L'état `ready` ne garantit pas l'absence d'obstacle.
- Le mode `--dry-run` du client inhibe les mouvements ; il ne remplace pas les
  tests unitaires sans réseau et ne signifie pas que tout accès au robot est simulé.
- Avec `ROS_AUTOSTART=true`, le bridge peut lancer et relancer le bringup ROS.
  Préserver les pilotes déjà lancés par un autre processus.

## Documentation

- `README.md` : vue d'ensemble, démarrage et organisation.
- `bridge/README.md` : API HTTP, capteurs, services, readiness et configuration.
- `docs/GUIDE_ROBOT.md` : programmation avec `tb3.Robot`.
- `docs/DEPLOIEMENT.md` : compilation, déploiement, interface et dépannage.
  Ses exemples de chemin absolu sont historiques ; utiliser la racine réelle.
- `docs/GUIDE_TURTLEBOT3_PYTHON.md` : notes du cours sur l'approche directe
  `rclpy`, distincte du client HTTP utilisé dans ce dépôt.
- Mettre ce contexte à jour si le matériel, les interfaces, l'architecture ou
  l'état de validation du projet évoluent.
