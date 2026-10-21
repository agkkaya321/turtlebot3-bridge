# Contrôler un TurtleBot3 avec des scripts Python simples

**Recommandation : écrire tes scripts sur ton ordinateur, les exécuter sur le Raspberry Pi du robot par SSH, et masquer ROS derrière une petite classe `Robot`.** Tu conserves les pilotes du robot et tu programmes avec des méthodes comme `robot.leftSpeed(0.05)`.

Ce guide vise les essais sur un robot réel. Tu as confirmé disposer, ou prévoir de disposer, d’un accès SSH. Il inclut une première bibliothèque à copier dans un fichier Python et les commandes pour lancer tes scripts. La syntaxe des exemples et les calculs de consigne ont été vérifiés localement avec des doubles Python, sans simulation ROS ; la communication et les arrêts restent à valider sur le matériel.

Le [cours fourni](https://github.com/nembrinj/protofablab/blob/main/2026/assignments/AN_01/html/AN_01_ROS-Tbot3-Install.html) utilise **Ubuntu 24.04, ROS 2 Jazzy et le modèle Burger** dans sa configuration. Je pars de cette base ; le modèle et l’installation effective du robot restent à vérifier. Sources consultées le 15 octobre 2026. Le code ci-dessous n’a pas été testé sur ton robot.

## 1. Où tourne chaque chose ?

```text
Ton ordinateur, notamment ton Mac
  └── éditeur + SSH : copier les fichiers et lancer une commande
        │ Wi-Fi
        ▼
Raspberry Pi du TurtleBot3, sous Ubuntu
  └── ton script Python
        └── ta bibliothèque Robot
              └── ROS 2 : topic /cmd_vel
                    └── pilote TurtleBot3 → carte OpenCR → moteurs
```

Un **topic** est un canal de messages. `/cmd_vel` transporte une consigne de déplacement. Un **nœud** est un programme qui participe à ROS ; ta bibliothèque en crée un pour toi.

Avec cette organisation, ROS est nécessaire sur le Raspberry Pi, mais **pas sur ton Mac**. Ton ordinateur sert de poste de développement et de terminal distant. Les commandes de moteurs circulent localement sur le robot.

Pour ce besoin, tu n’as pas besoin de Gazebo, de simulation, de cartographie, de Nav2 ou de RViz. Cela ne dispense pas des installations demandées séparément pour les autres activités du cours.

Je garderais ROS : il fournit déjà l’accès aux moteurs et, plus tard, aux capteurs. Piloter directement les moteurs avec le SDK DYNAMIXEL demanderait de reprendre une partie de cette intégration. Une passerelle HTTP ou WebSocket pourrait venir ensuite si tu veux une application de contrôle distante ; SSH suffit pour lancer des scripts.

## 2. Le résultat visé

Voici le script que tu pourras écrire avec la bibliothèque de la section 6 :

```python
from robot import Robot

with Robot() as robot:
    robot.wheels(0.05, 0.05)   # Les deux roues avancent à 5 cm/s.
    robot.wait(2.0)            # Maintenir cette commande pendant 2 secondes.
    robot.stop()

    robot.leftSpeed(-0.03)    # Roue gauche vers l'arrière.
    robot.rightSpeed(0.03)    # Roue droite vers l'avant.
    robot.wait(1.0)           # Rotation sur place vers la gauche.
    robot.stop()
```

Les vitesses sont des **consignes en mètres par seconde au niveau de la roue**, pas des pourcentages de puissance, des PWM ou des tours par minute. Une valeur positive fait avancer la roue, une valeur négative la fait reculer, quelle que soit l’orientation mécanique du moteur.

`leftSpeed()` conserve la consigne de droite et inversement. Pour changer les deux simultanément, privilégie `wheels(gauche, droite)` : deux appels séparés passent brièvement par un état intermédiaire.

Dans cette première version, **utilise `robot.wait()` pour maintenir un mouvement**, car cette méthode renvoie les commandes périodiquement. `time.sleep()`, `input()` ou un long calcul ne le font pas. La section 7 explique cette limite et comment faire évoluer la bibliothèque.

## 3. Préparer le robot une fois

### Obtenir les informations de connexion

Auprès du cours, récupère le nom d’utilisateur SSH, l’adresse IP du robot, le modèle exact, le `ROS_DOMAIN_ID` attribué et la façon dont les pilotes sont démarrés. Vérifie aussi que tu peux créer un dossier dans ton compte sur le Raspberry Pi.

Dans les exemples, **`UTILISATEUR` et `IP_DU_ROBOT` sont à remplacer** par les vraies valeurs. Ce ne sont pas des identifiants prédéfinis.

Depuis ton ordinateur, connecté au réseau du robot :

```bash
ssh UTILISATEUR@IP_DU_ROBOT
```

Les commandes suivantes se font **dans cette session SSH, sur le robot**, avec Bash :

```bash
bash
ls /opt/ros
source /opt/ros/jazzy/setup.bash

# Si les paquets du robot ont été compilés dans ce workspace :
if [ -f "$HOME/turtlebot3_ws/install/setup.bash" ]; then
    source "$HOME/turtlebot3_ws/install/setup.bash"
fi

printenv ROS_DISTRO ROS_DOMAIN_ID TURTLEBOT3_MODEL LDS_MODEL
ros2 pkg prefix turtlebot3_bringup
/usr/bin/python3 -c 'import rclpy; from geometry_msgs.msg import TwistStamped; print("Python ROS disponible")'
```

Si `jazzy` n’existe pas, commence par identifier la version réellement installée. Le cours décrit principalement l’installation du poste de travail ; il ne prouve pas que le Raspberry Pi a déjà été préparé. Si les pilotes manquent, fais préparer le robot selon le [guide officiel du SBC](https://emanual.robotis.com/docs/en/platform/turtlebot3/sbc_setup/) et la version retenue par le cours avant de poursuivre.

Utilise le Python système Ubuntu (`/usr/bin/python3`). `rclpy` n’est pas une bibliothèque à installer simplement avec `pip install rclpy` sur ton Mac. Évite pour commencer les environnements Conda et les environnements virtuels qui ne voient pas les paquets ROS.

### Préparer un petit dossier de travail

Sur le robot :

```bash
mkdir -p ~/robot_scripts
cd ~/robot_scripts
nano env.sh
```

Contenu proposé pour `env.sh`, **à adapter aux informations du robot** :

```bash
source /opt/ros/jazzy/setup.bash
if [ -f "$HOME/turtlebot3_ws/install/setup.bash" ]; then
    source "$HOME/turtlebot3_ws/install/setup.bash"
fi

export TURTLEBOT3_MODEL=burger
export ROS_DOMAIN_ID=101  # EXEMPLE : remplacer par le domaine attribué.

# Conserver la configuration LDS_MODEL déjà installée sur le robot.
# Si elle manque, ajouter ici la valeur correspondant au LiDAR réel.
```

Charge ce fichier dans **chaque terminal ROS** :

```bash
source ~/robot_scripts/env.sh
```

Le pilote et ton script doivent utiliser le même domaine. Le domaine sert à séparer les groupes de nœuds sur le réseau ; il ne remplace pas l’adresse IP SSH. Si les pilotes sont lancés automatiquement, reprends leur domaine existant. [Documentation ROS sur les domaines](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Concepts/Intermediate/About-Domain-ID.rst).

Le cours suggère des identifiants comme 101, 102, etc. ROS recommande généralement 0–101 pour éviter certains conflits de ports : conserve l’affectation du cours si elle est imposée, mais signale ce point en cas de problème réseau. Ne choisis pas un domaine déjà utilisé par un autre groupe.

## 4. Démarrer les pilotes et vérifier le robot

Le **bringup** est le lancement des programmes qui relient ROS au matériel. S’il tourne déjà, il ne faut pas en démarrer un deuxième.

Dans un premier terminal SSH :

```bash
source ~/robot_scripts/env.sh
ros2 node list
ros2 topic list -t
```

Si les pilotes ne sont pas lancés et que l’environnement correspond à celui du robot :

```bash
ros2 launch turtlebot3_bringup robot.launch.py
```

Laisse ce terminal ouvert. Cette commande est celle du [bringup officiel](https://emanual.robotis.com/docs/en/platform/turtlebot3/bringup/). Le [fichier de lancement Jazzy](https://github.com/ROBOTIS-GIT/turtlebot3/blob/jazzy/turtlebot3_bringup/launch/robot.launch.py) utilise aussi `LDS_MODEL` : si cette variable manque, renseigne le modèle réel du LiDAR dans `env.sh`, puis recharge-le. Ne choisis pas une valeur au hasard.

Dans un **deuxième terminal SSH**, charge aussi `env.sh`, puis vérifie :

```bash
source ~/robot_scripts/env.sh
ros2 topic list -t
ros2 topic type /cmd_vel
ros2 topic info /cmd_vel --verbose
ros2 param get /turtlebot3_node wheels.separation
```

Il faut un abonnement du pilote sur le topic de commande. Une simple présence dans la liste des topics ne prouve pas que les moteurs sont prêts. Si le cours utilise un namespace, les noms peuvent être `/robot101/cmd_vel` et `/robot101/turtlebot3_node` : adapte les commandes et l’argument `topic` de la bibliothèque.

**Attention au type de message :** la configuration Burger de la branche Jazzy consultée active `geometry_msgs/msg/TwistStamped`. Certaines installations utilisent `geometry_msgs/msg/Twist`. Le type observé sur ton robot décide de la configuration à utiliser. [Paramètres officiels Burger](https://github.com/ROBOTIS-GIT/turtlebot3/blob/jazzy/turtlebot3_bringup/param/burger.yaml), [gestion des deux types](https://github.com/ROBOTIS-GIT/turtlebot3/blob/jazzy/turtlebot3_node/include/turtlebot3_node/twist_subscriber.hpp).

| Résultat de `ros2 topic type /cmd_vel` | Construction Python |
|---|---|
| `geometry_msgs/msg/TwistStamped` | `Robot()` |
| `geometry_msgs/msg/Twist` | `Robot(stamped=False)` |
| Topic absent ou plusieurs types | Corriger la configuration avant d’envoyer un mouvement |

Pour une première prise en main au clavier, si le paquet est disponible :

```bash
ros2 run turtlebot3_teleop teleop_keyboard
```

`w/x` modifient la vitesse linéaire, `a/d` la rotation et `s` ou espace demandent l’arrêt. **Arrête et quitte teleop avant de lancer ton script.** Deux programmes qui publient sur `/cmd_vel` peuvent se contredire. [Téléopération officielle](https://emanual.robotis.com/docs/en/platform/turtlebot3/basic_operation/).

## 5. Comment traduire `leftSpeed()` et `rightSpeed()` ?

L’interface standard commande la vitesse du robot entier : `linear.x` en m/s et `angular.z` en rad/s. Le [pilote TurtleBot3](https://github.com/ROBOTIS-GIT/turtlebot3/blob/jazzy/turtlebot3_node/src/turtlebot3.cpp) transmet ces consignes à l’OpenCR.

Ta bibliothèque convertit les vitesses des roues selon la géométrie d’un robot différentiel :

```text
g = vitesse de la roue gauche, en m/s
d = vitesse de la roue droite, en m/s
L = distance entre les deux roues, en mètres

vitesse linéaire v = (g + d) / 2
vitesse angulaire ω = (d - g) / L
```

Pour un Burger standard, le paramétrage officiel donne `L = 0.160 m`. Vérifie cette valeur sur le robot si sa mécanique a été modifiée. Le rayon des roues n’intervient pas ici, puisque l’API utilise des m/s ; il deviendrait nécessaire pour proposer des rad/s ou des tours/minute. [Géométrie Burger](https://github.com/ROBOTIS-GIT/turtlebot3/blob/jazzy/turtlebot3_bringup/param/burger.yaml).

| Gauche | Droite | Mouvement demandé |
|---:|---:|---|
| `0.05` | `0.05` | Avancer tout droit |
| `-0.05` | `-0.05` | Reculer tout droit |
| `-0.03` | `0.03` | Tourner sur place vers la gauche |
| `0.03` | `-0.03` | Tourner sur place vers la droite |
| `0.00` | `0.05` | Tourner en avançant autour de la roue gauche |

Il s’agit de consignes : elles ne garantissent pas une vitesse réelle parfaite. La transmission, les limites du pilote, la quantification des commandes et l’adhérence ont un effet. Pour « avancer exactement de 50 cm », il faudra utiliser le retour d’odométrie, pas seulement une durée.

## 6. Une première bibliothèque directement utilisable

Crée `robot.py` dans `~/robot_scripts/` et copie le code suivant. Il vise un **Burger**, un script exécuté dans le thread principal, un seul objet `Robot` et aucun autre programme commandant les moteurs.

Cette version utilise une publication toutes les 50 ms pendant `wait()`, limite les consignes de chaque roue à ±0,10 m/s et attend un abonné compatible avant de commencer. Ce plafond est un choix prudent pour les premiers essais, pas la vitesse maximale constructeur. Un abonné compatible ne constitue pas une confirmation de bon fonctionnement du matériel.

La couche ROS repose sur `rclpy`, l’API Python officielle. Les scripts qui l’utilisent peuvent être lancés comme des fichiers Python ordinaires une fois l’environnement ROS chargé ; créer un paquet et relancer `colcon build` à chaque modification n’est pas nécessaire ici. [Tutoriel Python officiel](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Tutorials/Beginner-Client-Libraries/Writing-A-Simple-Py-Publisher-And-Subscriber.rst).

```python
# robot.py
import math
import signal
import time

import rclpy
from geometry_msgs.msg import Twist, TwistStamped
from rclpy.signals import SignalHandlerOptions


class Robot:
    def __init__(self, *, topic="/cmd_vel", stamped=True,
                 wheel_separation=0.160):
        self.separation = float(wheel_separation)
        if not math.isfinite(self.separation) or self.separation <= 0:
            raise ValueError("La distance entre roues doit être positive.")
        self.topic = topic
        self.stamped = stamped
        self.max_speed = 0.10
        self.left = self.right = 0.0
        self.node = self.pub = None
        self.old_handlers = {}

    def __enter__(self):
        if rclpy.ok():
            raise RuntimeError("Utiliser un seul Robot dans un script autonome.")
        # Laisser Python traiter les signaux afin d'envoyer l'arrêt
        # AVANT de fermer la connexion ROS.
        rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
        try:
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                self.old_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, self._interrupt)
            self.node = rclpy.create_node("simple_robot")
            msg_type = TwistStamped if self.stamped else Twist
            self.pub = self.node.create_publisher(msg_type, self.topic, 1)
            deadline = time.monotonic() + 5.0
            while self.pub.get_subscription_count() == 0:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Aucun abonné compatible : vérifier bringup, "
                        "domaine, topic et type Twist/TwistStamped."
                    )
                rclpy.spin_once(self.node, timeout_sec=0.05)
            self.stop()
            return self
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _interrupt(signum, frame):
        raise KeyboardInterrupt("Interruption du script robot")

    def _publish(self):
        if self.pub is None or not rclpy.ok():
            raise RuntimeError("Utiliser Robot dans un bloc with.")
        msg = TwistStamped() if self.stamped else Twist()
        if self.stamped:
            msg.header.stamp = self.node.get_clock().now().to_msg()
            msg.header.frame_id = "base_link"
            twist = msg.twist
        else:
            twist = msg
        twist.linear.x = (self.left + self.right) / 2.0
        twist.angular.z = (self.right - self.left) / self.separation
        self.pub.publish(msg)

    def wheels(self, left, right):
        left, right = float(left), float(right)
        if not all(math.isfinite(x) and abs(x) <= self.max_speed
                   for x in (left, right)):
            raise ValueError("Vitesses finies requises, entre -0.10 et 0.10 m/s.")
        self.left, self.right = left, right
        self._publish()

    def leftSpeed(self, speed):
        self.wheels(speed, self.right)

    def rightSpeed(self, speed):
        self.wheels(self.left, speed)

    def velocity(self, linear, angular=0.0):
        linear, angular = float(linear), float(angular)
        self.wheels(linear - angular * self.separation / 2.0,
                    linear + angular * self.separation / 2.0)

    def wait(self, seconds):
        seconds = float(seconds)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Durée finie et positive ou nulle requise.")
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._publish()
            rclpy.spin_once(self.node, timeout_sec=0.0)
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    def stop(self):
        self.left = self.right = 0.0
        for _ in range(3):
            self._publish()
            time.sleep(0.05)

    def close(self):
        try:
            if self.pub is not None and rclpy.ok():
                self.stop()
        finally:
            if self.node is not None:
                self.node.destroy_node()
                self.node = self.pub = None
            if rclpy.ok():
                rclpy.shutdown()
            for sig, handler in self.old_handlers.items():
                signal.signal(sig, handler)
            self.old_handlers.clear()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False
```

Le bloc `with` demande l’arrêt à la fin normale du script, à la sortie sur exception et lors des signaux traités, dont Ctrl+C. La répétition des messages d’arrêt augmente les chances de livraison ; ce n’est pas un acquittement du moteur.

### Créer ton premier script

Crée `demo.py` **dans le même dossier** :

```python
# demo.py
from robot import Robot


def main():
    with Robot() as robot:
        robot.wheels(0.03, 0.03)
        robot.wait(1.0)
        robot.stop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Script interrompu ; commande d'arrêt envoyée si ROS disponible.")
```

Si ton topic utilise `Twist`, remplace `Robot()` par `Robot(stamped=False)`. Pour un topic préfixé, utilise par exemple `Robot(topic="/robot101/cmd_vel")`. Si la séparation des roues diffère, renseigne également `wheel_separation` ; les valeurs proposées sont destinées au Burger.

Sur le robot, dans le deuxième terminal SSH :

```bash
source ~/robot_scripts/env.sh
cd ~/robot_scripts
/usr/bin/python3 demo.py
```

Pour chaque nouveau comportement, ajoute simplement un autre fichier Python à côté de `robot.py`.

## 7. Ce que l’arrêt garantit, et les limites de cette version

Fais le premier essai avec les roues dégagées du sol sur un support stable, puis au sol dans un espace libre, à faible vitesse et avec l’interrupteur accessible. Vérifie le sens des roues, `stop()` et Ctrl+C avant un parcours. Cette bibliothèque ne détecte pas les obstacles.

`wait()` maintient la dernière consigne et **n’arrête pas automatiquement à son retour**. Le mouvement suivant peut donc s’enchaîner sans arrêt ; appelle `stop()` pour une pause immobile. Pour attendre à l’arrêt, fais `robot.stop()` puis `robot.wait(1)`.

Cette version ne publie pas en arrière-plan. Pendant un calcul long ou un appel bloquant, elle ne renouvelle plus les consignes. Il faut vérifier que le contrôleur du robot arrête effectivement les roues quand il ne reçoit plus de commande, et après quel délai. **Le code fourni n’ajoute pas un watchdog indépendant.** La présence d’un horodatage dans `TwistStamped` ne suffit pas à garantir cette protection.

Un `kill -9`, un plantage du système ou une panne de communication peuvent empêcher l’envoi de l’arrêt final. Avant de compter sur l’arrêt à la perte de commandes, valide le comportement du contrôleur avec les roues dégagées et une possibilité de couper les moteurs. Si aucun timeout n’est effectif, il faut en configurer un ou ajouter un superviseur local avant de faire des essais où le script peut se bloquer.

**Une coupure Wi-Fi ne signifie pas nécessairement que le robot s’arrête.** Le script tourne sur le Raspberry Pi et peut continuer ; la perte de session SSH peut n’être détectée qu’après un délai. Les signaux de fermeture sont traités s’ils arrivent au programme, mais ce n’est pas un arrêt d’urgence. Pour un arrêt sur perte du poste de contrôle, il faut un mécanisme explicite de renouvellement d’autorisation et un timeout surveillé sur le robot.

Pour une version plus évoluée, sépare le moteur de publication du code utilisateur : un exécuteur ROS traite les capteurs, et un superviseur expire les commandes si le script ne renouvelle pas son autorisation. Un thread qui republie indéfiniment la dernière vitesse sans expiration peut au contraire prolonger un mouvement quand ton script est bloqué.

## 8. Le flux de travail quotidien le plus simple

Crée `run.sh` dans `~/robot_scripts/` :

```bash
#!/usr/bin/env bash
set -e
cd -- "$(dirname -- "$0")"
source ./env.sh
if [ "$#" -eq 0 ]; then
    set -- demo.py
fi
exec /usr/bin/python3 "$@"
```

Depuis le robot :

```bash
bash ~/robot_scripts/run.sh demo.py
```

Depuis ton ordinateur, une fois les pilotes démarrés :

```bash
ssh -t UTILISATEUR@IP_DU_ROBOT 'bash ~/robot_scripts/run.sh demo.py'
```

L’option `-t` fournit un terminal distant pour les interruptions interactives. `run.sh` charge explicitement ROS, car les commandes SSH non interactives ne chargent pas toujours la configuration habituelle du shell.

Pour éditer localement, crée `robot.py` et `demo.py` dans un dossier de ton ordinateur, puis copie-les depuis ce dossier :

```bash
scp robot.py demo.py UTILISATEUR@IP_DU_ROBOT:~/robot_scripts/
```

Autre possibilité : ouvrir `~/robot_scripts/` avec ton éditeur via SSH et modifier directement les fichiers distants. Au quotidien, tu démarres les pilotes une fois, tu modifies un script, puis tu relances `run.sh`. Aucun serveur web à mettre en place.

## 9. Ajouter ensuite des commandes plus intelligentes

La petite bibliothèque peut évoluer progressivement :

| Méthode souhaitée | Ce qu’il faut ajouter derrière |
|---|---|
| `robot.forward(speed)` | Un raccourci vers `wheels(speed, speed)` |
| `robot.turnRate(omega)` | Un raccourci vers `velocity(0.0, omega)` |
| `robot.forwardFor(speed, seconds)` | Une commande, `wait(seconds)` et un `stop()` dans un `finally` |
| `robot.moveDistance(0.50)` | Lire `/odom`, mesurer la progression et corriger la vitesse jusqu’à la cible |
| `robot.turnDegrees(90)` | Lire l’orientation, gérer le passage de ±π et arrêter dans une tolérance |
| `robot.frontDistance()` | Lire `/scan` et calculer une distance valide dans un secteur devant le robot |
| `robot.batteryVoltage()` | Lire `/battery_state` |

Ces méthodes supplémentaires ne sont **pas implémentées** dans le code ci-dessus. Les [topics standard TurtleBot3](https://emanual.robotis.com/docs/en/platform/turtlebot3/basic_operation/) fournissent notamment l’odométrie, le LiDAR et l’état de la batterie.

Pour les mouvements avec retour capteur, ajoute une durée maximale, une détection des données trop anciennes et un arrêt sur erreur. Pour le LiDAR, utilise `angle_min` et `angle_increment` au lieu de supposer que l’indice zéro représente l’avant ; traite les valeurs non finies et les plages invalides. La réception des capteurs doit utiliser un QoS compatible avec leurs publishers, souvent le profil ROS dédié aux données de capteurs.

L’odométrie améliore le contrôle d’une distance ou d’un angle, mais dérive avec le glissement des roues. Une durée seule est encore moins précise. Tu peux construire une première version utile sans cartographie ni navigation autonome.

## 10. Si quelque chose ne fonctionne pas

| Symptôme | Vérification utile |
|---|---|
| `ros2: command not found` | Tu es bien en SSH sur le robot et tu as chargé `env.sh`. |
| `No module named rclpy` | Utiliser `/usr/bin/python3` après avoir chargé ROS ; vérifier les paquets Python ROS installés. |
| Paquet `turtlebot3_bringup` introuvable | Charger le bon workspace ou faire préparer les pilotes du robot. |
| Erreur `LDS_MODEL` | Reprendre la valeur du LiDAR réellement installé. |
| Aucun abonné compatible après cinq secondes | Vérifier bringup, `ROS_DOMAIN_ID`, namespace et type de message. |
| `/cmd_vel` existe mais le robot ne bouge pas | Vérifier l’abonnement du pilote, ses logs, l’alimentation, l’OpenCR et l’état des moteurs. |
| Le robot s’arrête pendant une pause Python | Utiliser `robot.wait()` ; `time.sleep()` ne renouvelle pas les commandes. |
| Mouvement incohérent | Arrêter les autres publishers de vitesse ; vérifier `ros2 topic info /cmd_vel --verbose`. |
| Mauvaise rotation | Vérifier le modèle, l’écartement des roues et les signes de vitesse. |
| Topics absents après un changement de domaine | Recharger le même environnement partout, puis `ros2 daemon stop` et relancer la commande de diagnostic. |

Si l’exécution sur le Raspberry Pi devient impossible, le même principe peut fonctionner depuis un ordinateur sous Ubuntu avec ROS 2 Jazzy : le script publie alors sur le réseau. Il faut résoudre la découverte ROS, le domaine et les pare-feu. Avec l’accès SSH dont tu disposes, l’exécution locale sur le robot reste le point de départ le plus simple.
