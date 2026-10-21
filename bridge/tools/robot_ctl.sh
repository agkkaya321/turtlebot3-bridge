#!/usr/bin/env bash
# Exécuté SUR le robot, envoyé par le Mac : ssh robot 'bash -s -- check' < robot_ctl.sh
# Sous-commandes : check | start | stop | status | log [lignes]
# Aucune installation ni accès internet n'est nécessaire sur le robot.
# Pas de « set -u » : les scripts setup.bash de ROS ne le supportent pas.
DIR="$HOME/bridge"
BIN="target/release/turtlebot-speed-bridge"
PATTERN="target/release/turtlebot-speed-bridge"
PORT=8000

if [ -t 1 ] || [ "${FORCE_COLOR:-}" = 1 ]; then
    G=$'\e[32m' Y=$'\e[33m' R=$'\e[31m' B=$'\e[1m' N=$'\e[0m'
else
    G="" Y="" R="" B="" N=""
fi
ok()   { echo "${G}  OK${N}    $*"; }
warn() { echo "${Y}  ATTN${N}  $*"; WARNINGS=$((WARNINGS + 1)); }
bad()  { echo "${R}  ÉCHEC${N} $*"; FAILURES=$((FAILURES + 1)); }
title() { echo; echo "${B}$*${N}"; }
WARNINGS=0
FAILURES=0

bridge_pids() { pgrep -f "$PATTERN" || true; }

# Même environnement que run.sh, pour diagnostiquer ce que verra le bridge.
load_env() {
    # shellcheck disable=SC1091
    source /opt/ros/jazzy/setup.bash 2>/dev/null || return 1
    if [ -f "$HOME/turtlebot3_ws/install/setup.bash" ]; then
        # shellcheck disable=SC1091
        source "$HOME/turtlebot3_ws/install/setup.bash"
    fi
    if [ -f "$HOME/.bashrc" ]; then
        eval "$(grep -E '^[[:space:]]*export[[:space:]]+(ROS_DOMAIN_ID|TURTLEBOT3_MODEL|LDS_MODEL|OPENCR_PORT|OPENCR_MODEL|RMW_IMPLEMENTATION|ROS_LOCALHOST_ONLY|ROS_AUTOMATIC_DISCOVERY_RANGE)=' "$HOME/.bashrc")"
    fi
    if [ -f "$DIR/robot.env" ]; then
        # shellcheck disable=SC1091
        source "$DIR/robot.env"
    fi
}

http_get() {
    if command -v curl >/dev/null; then
        curl -s --max-time 2 "http://127.0.0.1:$PORT$1"
    else
        python3 -c "import sys,urllib.request as u; print(u.urlopen('http://127.0.0.1:$PORT'+sys.argv[1],timeout=2).read().decode())" "$1" 2>/dev/null
    fi
}

cmd_check() {
    title "Système"
    ok "$(uname -m), $(. /etc/os-release && echo "$PRETTY_NAME"), $(date '+%d.%m.%Y %H:%M:%S')"
    local free
    free=$(df -Pm "$HOME" | awk 'NR==2 {print $4}')
    if [ "${free:-0}" -lt 300 ]; then warn "Seulement ${free} Mo libres"; else ok "${free} Mo libres"; fi

    title "ROS 2 et TurtleBot3"
    if [ ! -f /opt/ros/jazzy/setup.bash ]; then
        bad "ROS 2 Jazzy absent (/opt/ros/jazzy)"
        return
    fi
    load_env
    ok "ROS $ROS_DISTRO chargé"
    for pkg in turtlebot3_bringup turtlebot3_msgs turtlebot3_node; do
        if ros2 pkg prefix "$pkg" >/dev/null 2>&1; then ok "Paquet $pkg"; else bad "Paquet $pkg introuvable"; fi
    done
    [ -n "${ROS_DOMAIN_ID:-}" ] && ok "ROS_DOMAIN_ID=$ROS_DOMAIN_ID" || warn "ROS_DOMAIN_ID non défini (0 par défaut)"
    [ -n "${TURTLEBOT3_MODEL:-}" ] && ok "TURTLEBOT3_MODEL=$TURTLEBOT3_MODEL" || bad "TURTLEBOT3_MODEL non défini (robot.env)"
    [ -n "${LDS_MODEL:-}" ] && ok "LDS_MODEL=$LDS_MODEL" || bad "LDS_MODEL non défini : le bringup ne démarrera pas (robot.env)"
    local bashrc_domain
    bashrc_domain=$(grep -E '^[[:space:]]*export[[:space:]]+ROS_DOMAIN_ID=' "$HOME/.bashrc" 2>/dev/null | tail -1 | sed 's/.*=//; s/["'\'' ]//g')
    if [ -n "$bashrc_domain" ] && [ "$bashrc_domain" != "${ROS_DOMAIN_ID:-}" ]; then
        warn "~/.bashrc utilise ROS_DOMAIN_ID=$bashrc_domain mais robot.env $ROS_DOMAIN_ID : tes terminaux SSH ne verront pas le bridge"
    fi

    title "Matériel"
    local opencr="${OPENCR_PORT:-/dev/ttyACM0}"
    if [ -e "$opencr" ]; then ok "Carte OpenCR : $opencr"; else bad "OpenCR absente ($opencr) : câble USB / alimentation"; fi
    if ls /dev/ttyUSB* >/dev/null 2>&1; then ok "LiDAR : $(ls /dev/ttyUSB* | tr '\n' ' ')"; else warn "Aucun /dev/ttyUSB* : LiDAR non branché ?"; fi
    if id -nG | grep -qw dialout; then ok "Utilisateur dans le groupe dialout"; else warn "$(whoami) n'est pas dans dialout : accès série peut-être refusé"; fi

    title "Bridge"
    if [ ! -x "$DIR/$BIN" ]; then
        bad "Binaire absent : $DIR/$BIN"
    else
        if (cd "$DIR" && sha256sum -c --quiet SHA256SUMS >/dev/null 2>&1); then ok "Binaire intègre (SHA256SUMS)"; else warn "Empreinte SHA256 différente de SHA256SUMS"; fi
        local missing
        missing=$(ldd "$DIR/$BIN" 2>/dev/null | grep "not found" || true)
        if [ -n "$missing" ]; then bad "Bibliothèques manquantes :"; echo "$missing"; else ok "Bibliothèques ROS trouvées (ldd)"; fi
    fi
    if [ -f "$DIR/robot.env" ]; then ok "robot.env présent"; else warn "robot.env absent : sera créé depuis robot.env.example"; fi
    local pids
    pids=$(bridge_pids)
    if [ -n "$pids" ]; then
        ok "Bridge en cours (PID $(echo "$pids" | tr '\n' ' '))"
        local status
        status=$(http_get /status)
        if [ -n "$status" ]; then ok "HTTP : $status"; else warn "Bridge lancé mais HTTP muet sur le port $PORT (BRIDGE_BIND ?)"; fi
    else
        warn "Bridge arrêté"
    fi
    if pgrep -f "robot.launch.py" >/dev/null; then
        ok "Bringup TurtleBot3 actif (PID $(pgrep -f robot.launch.py | tr '\n' ' '))"
    else
        warn "Bringup TurtleBot3 non lancé (le bridge le démarre si ROS_AUTOSTART=true)"
    fi

    title "Graphe ROS (domaine ${ROS_DOMAIN_ID:-0})"
    local topics services
    topics=$(timeout 15 ros2 topic list --no-daemon --spin-time 3 2>/dev/null || true)
    services=$(timeout 15 ros2 service list --no-daemon --spin-time 3 2>/dev/null || true)
    local ns="${ROBOT_NAMESPACE:-}"
    ns="${ns#/}"
    local prefix=""
    [ -n "$ns" ] && prefix="/$ns"
    for topic in cmd_vel odom sensor_state battery_state imu scan magnetic_field joint_states; do
        if echo "$topics" | grep -qx "$prefix/$topic"; then ok "Topic $prefix/$topic"; else warn "Topic $prefix/$topic absent"; fi
    done
    for service in sound motor_power reset; do
        if echo "$services" | grep -qx "$prefix/$service"; then ok "Service $prefix/$service"; else warn "Service $prefix/$service absent"; fi
    done
    local others
    others=$(echo "$topics" | grep -vE "^$prefix/(cmd_vel|odom|sensor_state|battery_state|imu|scan|magnetic_field|joint_states|tf|tf_static|parameter_events|rosout|robot_description)$" | grep -v '^$' || true)
    if [ -n "$others" ]; then ok "Autres topics : $(echo "$others" | tr '\n' ' ')"; fi

    echo
    if [ "$FAILURES" -gt 0 ]; then
        echo "${R}${B}$FAILURES échec(s)${N}, $WARNINGS avertissement(s)"
        return 1
    fi
    echo "${G}${B}Aucun échec${N}, $WARNINGS avertissement(s)"
}

cmd_start() {
    if [ -n "$(bridge_pids)" ]; then
        echo "Bridge déjà en cours."
        return 0
    fi
    cd "$DIR" || { echo "Dossier $DIR absent"; return 1; }
    if [ ! -f robot.env ]; then
        cp robot.env.example robot.env
        echo "robot.env créé depuis robot.env.example : vérifier ROS_DOMAIN_ID et LDS_MODEL."
    fi
    chmod +x "$BIN" run.sh
    [ -f bridge.log ] && mv -f bridge.log bridge.log.1
    # setsid : le bridge survit à la fermeture de la session SSH.
    setsid nohup bash run.sh > bridge.log 2>&1 < /dev/null &
    local i
    for i in 1 2 3 4 5 6 7 8 9 10; do
        sleep 0.5
        if [ -z "$(bridge_pids)" ]; then
            echo "Le bridge s'est arrêté au démarrage :"
            tail -n 30 bridge.log
            return 1
        fi
        if http_get /ready >/dev/null 2>&1 && [ -n "$(http_get /ready)" ]; then
            echo "Bridge démarré (PID $(bridge_pids | tr '\n' ' '))."
            return 0
        fi
    done
    echo "Bridge lancé mais HTTP pas encore prêt ; voir bridge.log."
}

cmd_stop() {
    if [ -z "$(bridge_pids)" ]; then
        echo "Bridge déjà arrêté."
        return 0
    fi
    # SIGINT : le bridge publie zéro puis arrête le bringup qu'il a lancé.
    pkill -INT -f "$PATTERN"
    local i
    for i in $(seq 1 30); do
        [ -z "$(bridge_pids)" ] && { echo "Bridge arrêté."; return 0; }
        sleep 0.5
    done
    echo "Le bridge ne répond pas à SIGINT ; arrêt forcé."
    pkill -KILL -f "$PATTERN"
    echo "Vérifier qu'aucun bringup orphelin ne tourne : pgrep -af robot.launch.py"
}

cmd_status() {
    local pids
    pids=$(bridge_pids)
    if [ -z "$pids" ]; then
        echo "stopped"
        return 0
    fi
    echo "running $(echo "$pids" | tr '\n' ' ')"
    http_get /status
    echo
}

case "${1:-check}" in
    check) cmd_check ;;
    start) cmd_start ;;
    stop) cmd_stop ;;
    status) cmd_status ;;
    log) tail -n "${2:-200}" "$DIR/bridge.log" 2>/dev/null || echo "Pas encore de bridge.log" ;;
    *) echo "Usage : robot_ctl.sh check|start|stop|status|log [n]"; exit 2 ;;
esac
