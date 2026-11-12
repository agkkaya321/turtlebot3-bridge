#!/usr/bin/env bash
# Run ON the robot, sent from the Mac: ssh robot 'bash -s -- check' < robot_ctl.sh
# Subcommands: check | start | stop | status | log [lines]
# No installation or internet access is required on the robot.
# Do not use set -u: ROS setup.bash scripts do not support it.
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
warn() { echo "${Y}  WARN${N}  $*"; WARNINGS=$((WARNINGS + 1)); }
bad()  { echo "${R}  FAIL${N} $*"; FAILURES=$((FAILURES + 1)); }
title() { echo; echo "${B}$*${N}"; }
WARNINGS=0
FAILURES=0

bridge_pids() { pgrep -f "$PATTERN" || true; }

# Use the same environment as run.sh to diagnose what the bridge will see.
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
    title "System"
    ok "$(uname -m), $(. /etc/os-release && echo "$PRETTY_NAME"), $(date '+%d.%m.%Y %H:%M:%S')"
    local free
    free=$(df -Pm "$HOME" | awk 'NR==2 {print $4}')
    if [ "${free:-0}" -lt 300 ]; then warn "Only ${free} MB free"; else ok "${free} MB free"; fi

    title "ROS 2 and TurtleBot3"
    if [ ! -f /opt/ros/jazzy/setup.bash ]; then
        bad "ROS 2 Jazzy missing (/opt/ros/jazzy)"
        return
    fi
    load_env
    ok "ROS $ROS_DISTRO loaded"
    for pkg in turtlebot3_bringup turtlebot3_msgs turtlebot3_node; do
        if ros2 pkg prefix "$pkg" >/dev/null 2>&1; then ok "Package $pkg"; else bad "Package $pkg not found"; fi
    done
    [ -n "${ROS_DOMAIN_ID:-}" ] && ok "ROS_DOMAIN_ID=$ROS_DOMAIN_ID" || warn "ROS_DOMAIN_ID not set (default 0)"
    [ -n "${TURTLEBOT3_MODEL:-}" ] && ok "TURTLEBOT3_MODEL=$TURTLEBOT3_MODEL" || bad "TURTLEBOT3_MODEL not set (robot.env)"
    [ -n "${LDS_MODEL:-}" ] && ok "LDS_MODEL=$LDS_MODEL" || bad "LDS_MODEL not set: bringup will not start (robot.env)"
    local bashrc_domain
    bashrc_domain=$(grep -E '^[[:space:]]*export[[:space:]]+ROS_DOMAIN_ID=' "$HOME/.bashrc" 2>/dev/null | tail -1 | sed 's/.*=//; s/["'\'' ]//g')
    if [ -n "$bashrc_domain" ] && [ "$bashrc_domain" != "${ROS_DOMAIN_ID:-}" ]; then
        warn "~/.bashrc uses ROS_DOMAIN_ID=$bashrc_domain but robot.env uses $ROS_DOMAIN_ID: SSH terminals will not see the bridge"
    fi

    title "Hardware"
    local opencr="${OPENCR_PORT:-/dev/ttyACM0}"
    if [ -e "$opencr" ]; then ok "OpenCR board: $opencr"; else bad "OpenCR missing ($opencr): check USB cable / power"; fi
    if ls /dev/ttyUSB* >/dev/null 2>&1; then ok "LiDAR : $(ls /dev/ttyUSB* | tr '\n' ' ')"; else warn "No /dev/ttyUSB*: is the LiDAR connected?"; fi
    if id -nG | grep -qw dialout; then ok "User belongs to the dialout group"; else warn "$(whoami) is not in dialout: serial access may be denied"; fi

    title "Caméra"
    local camera="${CAMERA_DEVICE:-/dev/video0}"
    if [ -e "$camera" ]; then ok "Webcam : $camera"; else warn "Aucune webcam sur $camera (brancher la caméra USB ; CAMERA_DEVICE dans robot.env)"; fi
    if command -v v4l2-ctl >/dev/null; then
        local cams
        cams=$(v4l2-ctl --list-devices 2>/dev/null | grep -v '^[[:space:]]*/dev/' | grep -v '^$' | grep -viE 'bcm2835|unicam|pisp|rpivid|hevc' | tr '\n' ' ')
        [ -n "$cams" ] && ok "Périphériques vidéo : $cams"
    fi
    if id -nG | grep -qw video; then ok "Utilisateur dans le groupe video"; else warn "$(whoami) n'est pas dans video : sudo usermod -aG video $(whoami) puis se reconnecter"; fi
    if ros2 pkg prefix usb_cam >/dev/null 2>&1; then ok "Paquet usb_cam"; else warn "Paquet usb_cam introuvable : sudo apt install ros-jazzy-usb-cam (internet)"; fi
    if pgrep -f usb_cam_node_exe >/dev/null; then ok "Pilote caméra actif (PID $(pgrep -f usb_cam_node_exe | tr '\n' ' '))"; else warn "Pilote caméra non lancé (le bridge le démarre si CAMERA_AUTOSTART=true)"; fi

    title "Bridge"
    if [ ! -x "$DIR/$BIN" ]; then
        bad "Binary missing: $DIR/$BIN"
    else
        if (cd "$DIR" && sha256sum -c --quiet SHA256SUMS >/dev/null 2>&1); then ok "Binary checksum verified (SHA256SUMS)"; else warn "SHA256 checksum differs from SHA256SUMS"; fi
        local missing
        missing=$(ldd "$DIR/$BIN" 2>/dev/null | grep "not found" || true)
        if [ -n "$missing" ]; then bad "Missing libraries:"; echo "$missing"; else ok "ROS libraries found (ldd)"; fi
    fi
    if [ -f "$DIR/robot.env" ]; then ok "robot.env found"; else warn "robot.env missing: it will be created from robot.env.example"; fi
    local pids
    pids=$(bridge_pids)
    if [ -n "$pids" ]; then
        ok "Bridge running (PID $(echo "$pids" | tr '\n' ' '))"
        local status
        status=$(http_get /status)
        if [ -n "$status" ]; then ok "HTTP : $status"; else warn "Bridge running but HTTP is silent on port $PORT (BRIDGE_BIND?)"; fi
    else
        warn "Bridge stopped"
    fi
    if pgrep -f "robot.launch.py" >/dev/null; then
        ok "TurtleBot3 bringup active (PID $(pgrep -f robot.launch.py | tr '\n' ' '))"
    else
        warn "TurtleBot3 bringup not running (the bridge starts it if ROS_AUTOSTART=true)"
    fi

    title "ROS graph (domain ${ROS_DOMAIN_ID:-0})"
    local topics services
    topics=$(timeout 15 ros2 topic list --no-daemon --spin-time 3 2>/dev/null || true)
    services=$(timeout 15 ros2 service list --no-daemon --spin-time 3 2>/dev/null || true)
    local ns="${ROBOT_NAMESPACE:-}"
    ns="${ns#/}"
    local prefix=""
    [ -n "$ns" ] && prefix="/$ns"
    for topic in cmd_vel odom sensor_state battery_state imu scan magnetic_field joint_states; do
        if echo "$topics" | grep -qx "$prefix/$topic"; then ok "Topic $prefix/$topic"; else warn "Topic $prefix/$topic missing"; fi
    done
    local camera_topic="${CAMERA_TOPIC:-$prefix/image_raw}"
    if echo "$topics" | grep -qx "$camera_topic"; then ok "Topic caméra $camera_topic"; else warn "Topic caméra $camera_topic absent"; fi
    for service in sound motor_power reset; do
        if echo "$services" | grep -qx "$prefix/$service"; then ok "Service $prefix/$service"; else warn "Service $prefix/$service missing"; fi
    done
    local others
    others=$(echo "$topics" | grep -vE "^$prefix/(cmd_vel|odom|sensor_state|battery_state|imu|scan|magnetic_field|joint_states|tf|tf_static|parameter_events|rosout|robot_description|image_raw)$" | grep -v '^$' || true)
    if [ -n "$others" ]; then ok "Autres topics : $(echo "$others" | tr '\n' ' ')"; fi

    echo
    if [ "$FAILURES" -gt 0 ]; then
        echo "${R}${B}$FAILURES failure(s)${N}, $WARNINGS warning(s)"
        return 1
    fi
    echo "${G}${B}No failures${N}, $WARNINGS warning(s)"
}

cmd_start() {
    if [ -n "$(bridge_pids)" ]; then
        echo "Bridge already running."
        return 0
    fi
    cd "$DIR" || { echo "Directory $DIR missing"; return 1; }
    if [ ! -f robot.env ]; then
        cp robot.env.example robot.env
        echo "robot.env created from robot.env.example: check ROS_DOMAIN_ID and LDS_MODEL."
    fi
    chmod +x "$BIN" run.sh
    [ -f bridge.log ] && mv -f bridge.log bridge.log.1
    # Also monitor run.sh while ROS loads, before exec replaces it with the binary.
    # --wait preserves monitoring even if setsid must fork a child process.
    setsid --wait nohup bash run.sh > bridge.log 2>&1 < /dev/null &
    local launcher=$! i response pids
    for i in $(seq 1 60); do
        sleep 0.5
        pids=$(bridge_pids)
        if ! kill -0 "$launcher" 2>/dev/null && [ -z "$pids" ]; then
            wait "$launcher" 2>/dev/null || true
            echo "The bridge stopped during startup:"
            tail -n 30 bridge.log
            return 1
        fi
        if [ -n "$pids" ] && response=$(http_get /ready 2>/dev/null) && [ -n "$response" ]; then
            echo "Bridge started (PID $(bridge_pids | tr '\n' ' '))."
            return 0
        fi
    done
    echo "Startup timed out : the process is still active, but the HTTP API is not responding."
    echo "Startup may complete later; check with ./start.sh status from the Mac."
    tail -n 30 bridge.log
    return 1
}

cmd_stop() {
    if [ -z "$(bridge_pids)" ]; then
        echo "Bridge already stopped."
        return 0
    fi
    # SIGINT : le bridge publie zéro puis arrête le bringup et la caméra qu'il a lancés.
    pkill -INT -f "$PATTERN"
    local i
    for i in $(seq 1 30); do
        [ -z "$(bridge_pids)" ] && { echo "Bridge stopped."; return 0; }
        sleep 0.5
    done
    echo "The bridge is not responding to SIGINT; forcing shutdown."
    pkill -KILL -f "$PATTERN"
    echo "Vérifier qu'aucun bringup ni pilote caméra orphelin ne tourne : pgrep -af 'robot.launch.py|usb_cam'"
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
    log) tail -n "${2:-200}" "$DIR/bridge.log" 2>/dev/null || echo "No bridge.log yet" ;;
    *) echo "Usage: robot_ctl.sh check|start|stop|status|log [n]"; exit 2 ;;
esac
