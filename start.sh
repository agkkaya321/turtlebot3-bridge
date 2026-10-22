#!/usr/bin/env bash
# Démarre tout depuis le Mac, sur le réseau du robot (aucun accès internet requis) :
#   1. connexion SSH partagée (mot de passe demandé une seule fois, ou clé) ;
#   2. copie du bridge sur le robot s'il a changé ;
#   3. diagnostic du robot (ROS, paquets, OpenCR, LiDAR, topics, services) ;
#   4. lancement du bridge sur le robot s'il ne tourne pas ;
#   5. tunnel SSH vers son API, puis interface web sur http://127.0.0.1:8080.
#
# Usage : ./start.sh [start|check|stop|status|log|build|help]
# Variables : ROBOT_HOST (ubuntu@192.168.1.109), ROBOT_SSH_PORT (22), UI_PORT (8080),
#             LOCAL_PORT (8000), NO_BROWSER=1, SKIP_CHECK=1
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
ROBOT_HOST="${ROBOT_HOST:-ubuntu@192.168.1.109}"
ROBOT_SSH_PORT="${ROBOT_SSH_PORT:-22}"
UI_PORT="${UI_PORT:-8080}"
LOCAL_PORT="${LOCAL_PORT:-8000}"
REMOTE_PORT=8000
DIST="$ROOT/bridge/dist"
BINARY="target/release/turtlebot-speed-bridge"
CTL="$ROOT/bridge/tools/robot_ctl.sh"
# Chemin court : macOS limite les sockets Unix à 104 caractères.
CONTROL_PATH="/tmp/tb3-ssh-%C"
SSH_OPTS=(-p "$ROBOT_SSH_PORT" -o "ControlPath=$CONTROL_PATH" -o ConnectTimeout=6
          -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=3)
ROBOT_IP="${ROBOT_HOST#*@}"

if [ -t 1 ]; then
    G=$'\e[32m' Y=$'\e[33m' R=$'\e[31m' B=$'\e[1m' N=$'\e[0m'
else
    G="" Y="" R="" B="" N=""
fi
step() { echo; echo "${B}==> $*${N}"; }
ok()   { echo "${G}  OK${N}    $*"; }
warn() { echo "${Y}  ATTN${N}  $*"; }
die()  { echo "${R}  ÉCHEC${N} $*" >&2; exit 1; }

ssh_robot() { ssh "${SSH_OPTS[@]}" "$ROBOT_HOST" "$@"; }
# robot_ctl.sh est envoyé par stdin : rien à installer sur le robot.
ctl() { ssh_robot bash -s -- "$@" < "$CTL"; }
master_alive() { ssh "${SSH_OPTS[@]}" -O check "$ROBOT_HOST" >/dev/null 2>&1; }
# Ne fermer que la connexion ouverte par ce script (un autre start.sh peut l'utiliser).
OPENED_MASTER=0
close_master() {
    if [ "$OPENED_MASTER" = 1 ]; then
        ssh "${SSH_OPTS[@]}" -O exit "$ROBOT_HOST" >/dev/null 2>&1 || true
    fi
}

port_free() { ! lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
free_port() {
    local port=$1 last=$(($1 + 20))
    while [ "$port" -le "$last" ]; do
        if port_free "$port"; then echo "$port"; return 0; fi
        port=$((port + 1))
    done
    return 1
}

connect() {
    step "Connexion SSH à $ROBOT_HOST"
    if master_alive; then
        ok "Connexion SSH partagée déjà ouverte"
        return
    fi
    if ! nc -z -G 4 "$ROBOT_IP" "$ROBOT_SSH_PORT" >/dev/null 2>&1; then
        die "Robot injoignable sur $ROBOT_IP:$ROBOT_SSH_PORT.
         - Le Mac est-il sur le réseau Wi-Fi du robot ?
         - Le Raspberry Pi est-il allumé (attendre ~1 min après démarrage) ?
         - Si l'IP a changé : ROBOT_HOST=ubuntu@NOUVELLE_IP ./start.sh"
    fi
    ok "Port SSH du robot joignable"
    if ! ssh "${SSH_OPTS[@]}" -o BatchMode=yes -o ControlMaster=no "$ROBOT_HOST" true 2>/dev/null; then
        warn "Pas de clé SSH acceptée par le robot."
        if [ -t 0 ]; then
            local answer
            read -r -p "        Installer ta clé SSH sur le robot (mot de passe demandé une fois) ? [O/n] " answer
            case "$answer" in
                n|N|non) ;;
                *) ssh-copy-id -p "$ROBOT_SSH_PORT" -o ConnectTimeout=6 -o StrictHostKeyChecking=accept-new "$ROBOT_HOST" \
                       || warn "ssh-copy-id a échoué : le mot de passe sera demandé ci-dessous." ;;
            esac
        fi
    fi
    # Connexion maîtresse : toutes les commandes suivantes la réutilisent.
    ssh "${SSH_OPTS[@]}" -o ControlMaster=yes -o ControlPersist=yes -fN "$ROBOT_HOST" \
        || die "Connexion SSH refusée (identifiants dans sshRobot.md)"
    OPENED_MASTER=1
    ok "Connexion SSH partagée ouverte"
}

deploy() {
    step "Bridge sur le robot"
    [ -x "$DIST/$BINARY" ] || die "Binaire absent : lancer ./start.sh build (avec internet) avant de rejoindre le réseau du robot."
    local newer
    newer=$(find "$ROOT/bridge/src" "$ROOT/bridge/Cargo.toml" -newer "$DIST/$BINARY" -type f 2>/dev/null | head -1)
    if [ -n "$newer" ] || ! cmp -s "$ROOT/bridge/run.sh" "$DIST/run.sh"; then
        warn "Sources modifiées depuis la dernière compilation : ./start.sh build (avec internet) pour les inclure."
    fi
    local local_sum remote_sum
    local_sum=$(shasum -a 256 "$DIST/$BINARY" | awk '{print $1}')
    remote_sum=$(ssh_robot "sha256sum ~/bridge/$BINARY 2>/dev/null | cut -d' ' -f1" || true)
    if [ "$local_sum" = "$remote_sum" ] && ssh_robot "cmp -s ~/bridge/run.sh /dev/stdin" < "$DIST/run.sh"; then
        ok "Bridge du robot à jour (${local_sum:0:12})"
        return
    fi
    if [ -z "$remote_sum" ]; then
        echo "        Première installation dans ~/bridge"
    else
        echo "        Nouvelle version : ${remote_sum:0:12} -> ${local_sum:0:12}"
        # Un exécutable en cours d'utilisation ne peut pas être remplacé.
        ctl stop
    fi
    ssh_robot "mkdir -p ~/bridge/target/release"
    # dist/ ne contient pas robot.env : la configuration du robot est conservée.
    scp -q -P "$ROBOT_SSH_PORT" -o "ControlPath=$CONTROL_PATH" -r "$DIST/." "$ROBOT_HOST:bridge/" || die "Copie impossible"
    ssh_robot "cd ~/bridge && chmod +x run.sh $BINARY && sha256sum -c --quiet SHA256SUMS" \
        || die "Empreinte incorrecte après copie"
    ok "Bridge copié et vérifié"
}

check() {
    step "Diagnostic du robot"
    if ctl check; then
        ok "Diagnostic sans échec bloquant"
    else
        warn "Le diagnostic signale des échecs (voir ci-dessus) ; le bridge sera quand même lancé."
    fi
}

start_bridge() {
    step "Démarrage du bridge"
    ctl start || die "Démarrage du bridge non confirmé (voir le journal ci-dessus)"
}

TUNNEL=""
UI_PID=""
cleanup() {
    trap - EXIT INT TERM
    echo
    step "Fermeture"
    if [ -n "$TUNNEL" ]; then
        # Dernier arrêt explicite : la consigne expire de toute façon en 500 ms.
        curl -s --max-time 1 -X POST -H 'Content-Type: application/json' -d '{}' \
            "http://127.0.0.1:$TUNNEL/stop" >/dev/null 2>&1 || true
        ssh "${SSH_OPTS[@]}" -O cancel -L "$TUNNEL:127.0.0.1:$REMOTE_PORT" "$ROBOT_HOST" >/dev/null 2>&1 || true
    fi
    if [ -n "$UI_PID" ]; then kill "$UI_PID" 2>/dev/null || true; fi
    close_master
    echo "  Interface et tunnel fermés. État du bridge : ./start.sh status ; arrêt : ./start.sh stop."
}

open_tunnel() {
    step "Tunnel vers l'API du bridge"
    TUNNEL=$(free_port "$LOCAL_PORT") || die "Aucun port local libre à partir de $LOCAL_PORT"
    ssh "${SSH_OPTS[@]}" -O forward -L "$TUNNEL:127.0.0.1:$REMOTE_PORT" "$ROBOT_HOST" >/dev/null \
        || die "Ouverture du tunnel impossible"
    ok "http://127.0.0.1:$TUNNEL -> robot:127.0.0.1:$REMOTE_PORT"
    local i status=""
    for i in $(seq 1 40); do
        status=$(curl -s --max-time 1 "http://127.0.0.1:$TUNNEL/status" || true)
        [ -n "$status" ] && break
        sleep 0.5
    done
    if [ -z "$status" ]; then
        warn "Le bridge ne répond pas via le tunnel (BRIDGE_BIND dans robot.env doit être 127.0.0.1:8000)."
    else
        ok "Bridge : $status"
        case "$status" in
            *'"not ready"'*) warn "Robot not ready : normal pendant ~30 s de calibration du bringup ; la raison s'affiche dans l'interface." ;;
        esac
    fi
}

start_ui() {
    step "Interface web"
    local port
    port=$(free_port "$UI_PORT") || die "Aucun port libre pour l'interface"
    python3 "$ROOT/ui/server.py" --port "$port" --bridge "http://127.0.0.1:$TUNNEL" \
        --robot "$ROBOT_HOST" --ssh-port "$ROBOT_SSH_PORT" --control-path "$CONTROL_PATH" --ctl "$CTL" &
    UI_PID=$!
    local i
    for i in $(seq 1 20); do
        curl -s --max-time 1 "http://127.0.0.1:$port/local/info" >/dev/null 2>&1 && break
        kill -0 "$UI_PID" 2>/dev/null || die "Le serveur de l'interface s'est arrêté"
        sleep 0.25
    done
    ok "http://127.0.0.1:$port"
    if [ "${NO_BROWSER:-0}" != 1 ]; then open "http://127.0.0.1:$port"; fi
    echo
    echo "  ${B}Prêt.${N} Ctrl+C ferme l'interface et le tunnel (le robot reçoit un arrêt)."
}

watch_link() {
    # Surveille la connexion SSH ; l'interface reste ouverte et signale la perte.
    while kill -0 "$UI_PID" 2>/dev/null; do
        if ! master_alive; then
            warn "Connexion SSH perdue : relancer ./start.sh une fois le robot de nouveau joignable."
            break
        fi
        sleep 3
    done
    wait "$UI_PID" 2>/dev/null || true
}

usage() { sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; }

case "${1:-start}" in
    start)
        trap cleanup EXIT
        trap 'exit 130' INT TERM
        connect
        deploy
        if [ "${SKIP_CHECK:-0}" != 1 ]; then check; fi
        start_bridge
        open_tunnel
        start_ui
        watch_link
        ;;
    check|stop|status|log)
        trap close_master EXIT
        connect
        if [ "$1" = check ]; then ctl check || true; else ctl "$1" "${2:-200}"; fi
        ;;
    build)
        command -v docker >/dev/null || die "Docker absent"
        docker info >/dev/null 2>&1 || die "Démarrer Docker Desktop (et avoir internet pour la première compilation)"
        bash "$ROOT/bridge/build-docker.sh"
        ;;
    help|-h|--help) usage ;;
    *) usage; exit 2 ;;
esac
