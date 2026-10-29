# Contexte de travail — NextStep

## Projet et source de vérité

- Échanger en français avec l'utilisateur.
- Racine du workspace : ce dossier, contenant `src/`, `setup/` et `dist/`.
  Le sous-dossier `ROS/` est un ancien projet IDE Java ; ne pas le prendre pour
  la racine Python et ne pas le supprimer sans demande.
- Projet **NextStep**, auteurs **Ali Gökkaya et Jason Condrea**.
- Contexte extrait des cinq slides de `dist/index.html` et du tableau `d0`
  dans `dist/assets/index-DwZMrydP.js` :
  1. Fabrication et prototypage.
  2. Caméra : suivi de posture et de position en temps réel ; score envisagé
     selon la stabilité et la lordose.
  3. Capteurs portés : fréquence cardiaque en BPM et oxygénation en pourcentage.
  4. Prédiction du prochain pas à partir de la posture et des paramètres vitaux ;
     laser indiquant au sol une cible pour chaque pied successivement.
  5. Conclusion de présentation.
- Les animations et valeurs vitales des slides sont simulées. Les objectifs
  présentés ne sont pas des capacités déjà développées ou validées.
- Le socle, le nœud `nextstep_health` et le script autonome
  `src/nextstep/nextstep/avancer_3_secondes.py` sont implémentés. Ce dernier envoie
  directement une vitesse de 0,05 m/s pendant 3 secondes sur `/cmd_vel`
  (`TwistStamped`), puis l'arrêt ; il commande un mouvement réel lorsqu'il est
  exécuté sur le robot. Ne pas l'exécuter sur le matériel pour une vérification.
  Modèles de caméra, capteurs, laser, algorithmes et interfaces métier restent
  à préciser. Voir `LANCER_AVANCER.md` pour la procédure SSH sans Docker.

## Environnement

- Hôte observé : macOS Apple Silicon, Python 3.12, Docker Desktop, PyCharm.
- Exécution ROS : Ubuntu 24.04, ROS 2 **Jazzy**, Python **3.12**, Gazebo Harmonic,
  TurtleBot3 Burger ; architecture native arm64. Ne pas migrer de distribution
  ROS ni remplacer les scripts existants sans nécessité liée à la demande.
- `.venv/bin/python` : outils locaux/slides seulement. `rclpy` provient de ROS
  dans Docker, pas de pip sur macOS.
- `compose.yaml`, service `ros-dev`, interpréteur **`/usr/local/bin/ros-python`**,
  racine locale montée dans `/ws`. Ce wrapper charge les environnements ROS
  même si PyCharm ignore l'ENTRYPOINT. Ne pas l'appeler récursivement.
- `setup/Dockerfile.python` étend l'image Jazzy existante. `setup/dev.sh image`
  construit d'abord cette base seulement si elle est absente.
- `setup/run.sh` garde le workflow de simulation ; `setup/robot.sh` celui du
  robot réel. Les volumes et le réseau de développement/simulation sont partagés.
- Domaine simulation **30** ; domaine des tests **87** ; robot réel **109**.
  `setup/robot.env` conserve la configuration robot ; l'IP doit être confirmée
  sur le matériel. La découverte DDS Docker → robot n'est pas validée.

## Commandes de référence (depuis la racine)

```bash
./setup/dev.sh init       # crée .venv, installe pytest, écrit l'identifiant .env
./setup/dev.sh image      # construit l'image Python de développement
./setup/dev.sh build      # colcon build --symlink-install --base-paths /ws/src
./setup/dev.sh check      # contexte rclpy, messages et index des paquets
./setup/dev.sh test       # publication/abonnement DDS réel, nécessite Docker
./setup/dev.sh node       # diagnostic /nextstep/health
./setup/dev.sh shell      # shell Ubuntu avec ROS chargé
./setup/dev.sh python -c 'import rclpy; print(rclpy.__file__)'
./setup/dev.sh slides     # http://127.0.0.1:5174
./setup/run.sh desktop    # bureau de simulation, port 6080
./setup/run.sh sim        # Gazebo
```

Sans le venv : `python3 -m http.server 5174 --bind 127.0.0.1 --directory dist`.
`python -m http.server:5174` est une syntaxe incorrecte.

## Conventions de développement

- Sources métier Python dans `src/nextstep/nextstep/`, paramètres dans `config/`,
  lancements dans `launch/`. Conserver le paquet compatible `ament_python`.
- Déclarer les dépendances ROS dans `package.xml` et les installer dans l'image.
  Ne pas installer silencieusement des paquets dans un conteneur jetable.
- Préférer des fonctions Python indépendantes de ROS pour les futurs calculs,
  avec des nœuds ROS responsables des messages, horloges et paramètres.
- Ne pas ajouter de bibliothèque de vision/ML sans besoin concret. Ne pas
  présenter un score clinique ou une recommandation de pas comme validés.
- Le nœud de diagnostic ne doit pas commander les moteurs ou le laser.
- Conserver `dist/` intact : seul le résultat compilé des slides est fourni.
- Ne pas versionner `.venv`, `.env`, caches, logs, rosbag ou données de personnes.
  Les métadonnées du paquet (contact/licence) sont provisoires, pas une décision
  de publication sous licence libre.
- Ne pas compiler simultanément le workspace depuis plusieurs terminaux.
- Après changement Python/ROS : compiler et exécuter les vérifications adaptées.
  Le test ROS est ignoré sur le Mac ; un skip ne valide pas le fonctionnement ROS.
- Ne pas confondre la validation CLI de l'interpréteur et une validation du
  débogueur dans l'interface PyCharm. La sélection du SDK Docker est propre à l'IDE.
- Dans `.idea/NextStep.iml`, utiliser `$PROJECT_DIR$` pour la racine et les
  chemins du projet. `$MODULE_DIR$/..` a fait inclure le Bureau dans PyCharm.
- `cleanup.sh` détruit les artefacts Docker du projet ; ne pas le lancer comme
  opération de routine. Ne pas lancer de commande de mouvement sur le robot
  dans le cadre d'un simple contrôle de l'environnement.

## Documentation

- `README.md` : démarrage et configuration de PyCharm.
- `setup/README.md` : simulation, volumes et robot.
- `setup/GUIDE_TURTLEBOT3.md` : historique et commandes du TP matériel.
- `LANCER_AVANCER.md` : copier et exécuter le script de mouvement sur le robot.
- Mettre ce contexte à jour si les choix matériels, les interfaces ou
  l'architecture du projet évoluent.
