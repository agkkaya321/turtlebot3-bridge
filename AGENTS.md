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
  utilisables sans accès internet.
- **`slides/dist/`** : présentation web compilée avec animations 3D. Conserver
  ces fichiers intacts sauf demande portant sur les slides ; les sources de
  développement de la présentation ne sont pas fournies.

## État du développement

- Le bridge, le client et l'interface sont implémentés. `bridge/README.md`
  rapporte des validations en conteneur et contre un faux robot, mais pas encore
  sur le robot réel. Ne pas déduire une validation matérielle de la présence
  du binaire ou de tests logiciels réussis.
- `client/next_step/main.py` contient actuellement des appels de sons et
  n'intègre pas encore la machine à états.
- Les états présents sont `initial`, `posture_checking`, `moving_backward`,
  `laser_aiming_left` et `laser_aiming_right`. Leurs actions sont encore des
  messages de console ; leurs noms ne prouvent pas un comportement fonctionnel.
  La logique de transition reste à terminer et à vérifier avant intégration.
- Caméra confirmée par l'utilisateur : **Logitech C270 HD**, branchée en USB
  au Raspberry Pi du robot pour filmer la personne qui s'entraîne. La série 2,
  tâche 6, utilise ce modèle avec `usb_cam` et `pixel_format:=mjpeg2rgb` :
  https://github.com/nembrinj/protofablab/blob/main/2026/assignments/AN_02/html/AN_02_ROS.html
- Le flux caméra n'est pas encore intégré au bridge. L'observation générique
  des topics dans `bridge/src/watch.rs` limite chaque message JSON à 32 Kio ;
  elle ne constitue pas un transport vidéo adapté. Le lieu d'exécution de
  l'analyse de posture et le transport des images restent à choisir.
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
