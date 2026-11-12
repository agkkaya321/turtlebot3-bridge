# TurtleBot3 Bridge

Piloter et programmer un **TurtleBot3 Burger** (ROS 2 Jazzy, Raspberry Pi) depuis un Mac,
sur le réseau Wi-Fi du robot, sans internet une fois les pilotes ROS installés.

- **Bridge Rust** sur le robot : expose les moteurs, les capteurs et les services ROS
  via une petite API HTTP, avec arrêt automatique si les consignes n'arrivent plus.
- **`start.sh`** sur le Mac : déploie le bridge, diagnostique le robot, ouvre un tunnel SSH
  et une interface web.
- **Client Python `tb3.Robot`** : programmer un comportement façon Arduino (`setup()` puis `loop()`).
- **Caméra USB optionnelle** : images JPEG via le même tunnel, aperçu web et `CameraClient`.
  Voir [l’activation de la caméra](docs/CAMERA.md).

```
Mac                                                     Raspberry Pi (TurtleBot3)
┌──────────────────────────┐                            ┌──────────────────────────────┐
│ interface web :8080      │                            │ bridge Rust 127.0.0.1:8000   │
│ programme Python (tb3)   ├── HTTP ─► tunnel SSH ─────►│   │                          │
│ start.sh                 │           127.0.0.1:8000   │   ▼                          │
└──────────────────────────┘                            │ ROS 2 Jazzy : turtlebot3_node│
                                                        │ LiDAR, OpenCR, moteurs       │
                                                        └──────────────────────────────┘
```

## Démarrage rapide

**1. Compiler** (sur le Mac, avec internet et Docker Desktop lancé, une seule fois) :

```bash
./start.sh build
```

**2. Lancer** (Mac connecté au Wi-Fi du robot) :

```bash
./start.sh
```

Le script copie le bridge sur le robot s'il a changé, lance le diagnostic et le bridge,
puis ouvre l'interface sur http://127.0.0.1:8080. Ctrl+C ferme l'interface ; le bridge
continue sur le robot (`./start.sh stop` pour l'arrêter).

**3. Programmer** (dans un second terminal) :

```python
from tb3 import Robot

class Explorateur(Robot):
    def loop(self):                      # appelée 10 fois par seconde
        d = self.front_distance()
        if d is not None and d < 0.30:
            self.turn(0.8)
        else:
            self.forward(0.08)

Explorateur().run()                      # Ctrl+C : le robot s'arrête
```

```bash
cd client
python3 exemples/capteurs.py --dry-run   # lire les capteurs sans bouger
python3 exemples/eviter_obstacles.py
```

## Commandes de `start.sh`

| Commande | Effet |
|---|---|
| `./start.sh` | Déploiement, diagnostic, bridge, tunnel et interface web |
| `./start.sh check` | Diagnostic seul |
| `./start.sh status` | Le bridge tourne-t-il ? |
| `./start.sh log [n]` | Dernières lignes du journal du bridge |
| `./start.sh stop` | Arrête le bridge et le bringup qu'il a lancé |
| `./start.sh build` | Recompile le bridge dans Docker |

Adresse du robot par défaut : `ubuntu@192.168.1.109`. Autre adresse :
`ROBOT_HOST=ubuntu@AUTRE_IP ./start.sh`.

## Organisation

```
.
├── start.sh            Lancement depuis le Mac
├── bridge/             Bridge Rust (ROS 2 ↔ HTTP), compilé dans Docker pour ARM64
│   ├── src/            Code source
│   ├── tools/          robot_ctl.sh (diagnostic sur le robot), smoke_test.py
│   ├── run.sh          Charge l'environnement ROS puis lance le bridge sur le robot
│   └── robot.env.example
├── client/             Client Python, sans dépendance externe
│   ├── tb3.py          Classe Robot à hériter : setup() / loop()
│   ├── robot.py        BridgeClient : accès direct à l'API HTTP
│   ├── camera.py       CameraClient : images JPEG et état de la caméra
│   ├── exemples/       avancer, eviter_obstacles, carre, capteurs
│   └── test_*.py       Tests (python3 -m unittest)
├── ui/                 Interface web locale (server.py + index.html, sans CDN)
└── docs/
    ├── GUIDE_ROBOT.md            Programmer avec tb3.Robot, capteur par capteur
    ├── DEPLOIEMENT.md            Compilation, déploiement et dépannage
    └── GUIDE_TURTLEBOT3_PYTHON.md  Notes du cours (approche rclpy directe)
```

## Documentation

- [docs/GUIDE_ROBOT.md](docs/GUIDE_ROBOT.md) : toutes les fonctions du client Python (mouvement,
  LiDAR, odométrie, IMU, batterie, OpenCR, topics ESP32, temps et états).
- [docs/DEPLOIEMENT.md](docs/DEPLOIEMENT.md) : compilation, lancement, interface web, dépannage.
- [docs/CAMERA.md](docs/CAMERA.md) : Brio 105, activation, API et accès Python.
- [bridge/README.md](bridge/README.md) : API HTTP, readiness, sécurité, configuration `robot.env`.

## Matériel visé

TurtleBot3 Burger, Raspberry Pi sous Ubuntu 24.04 (aarch64), ROS 2 Jazzy, LiDAR LDS-03,
carte OpenCR. Les identifiants SSH ne sont pas versionnés (fichier local `sshRobot.md`).

## Sécurité

- Vitesse limitée à ±0,10 m/s par roue par défaut (`MAX_SPEED_MPS`, au plus 0,22).
- Une consigne expire après 500 ms : le robot s'arrête si le Mac, le Wi-Fi ou le programme s'arrêtent.
- Le bridge ne freine pas devant un obstacle : c'est au programme de le faire.
- Premier essai : robot sur un support, roues dans le vide.

## Tests

```bash
cd client && python3 -m unittest      # client Python (sans robot)
./start.sh build                      # tests Rust + smoke test du binaire dans Docker
```
