#!/usr/bin/env bash
# Start everything from the Mac on the robot network (no internet access required):
#   1. shared SSH connection (password requested once, or key authentication);
#   2. copy the bridge to the robot if it has changed;
#   3. robot diagnostics (ROS, packages, OpenCR, LiDAR, topics, services);
#   4. start the bridge on the robot if it is not running;
#   5. SSH tunnel to its API, then the web UI at http://127.0.0.1:8080.
#
# Usage: ./start.sh [start|check|stop|status|log|build|help]
# Variables: ROBOT_HOST (ubuntu@192.168.1.109), ROBOT_SSH_PORT (22), UI_PORT (8080),
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
# Keep the path short: macOS limits Unix socket paths to 104 characters.
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
warn() { echo "${Y}  WARN${N}  $*"; }
die()  { echo "${R}  FAIL${N} $*" >&2; exit 1; }

ssh_robot() { ssh "${SSH_OPTS[@]}" "$ROBOT_HOST" "$@"; }
# robot_ctl.sh is sent through stdin: nothing to install on the robot.
ctl() { ssh_robot bash -s -- "$@" < "$CTL"; }
master_alive() { ssh "${SSH_OPTS[@]}" -O check "$ROBOT_HOST" >/dev/null 2>&1; }
# Only close the connection opened by this script (another start.sh may use it).
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
    step "SSH connection to $ROBOT_HOST"
    if master_alive; then
        ok "Shared SSH connection already open"
        return
    fi
    if ! nc -z -G 4 "$ROBOT_IP" "$ROBOT_SSH_PORT" >/dev/null 2>&1; then
        die "Robot unreachable at $ROBOT_IP:$ROBOT_SSH_PORT.
         - Is the Mac on the robot Wi-Fi network?
         - Is the Raspberry Pi powered on (wait about 1 minute after startup)?
         - If the IP changed: ROBOT_HOST=ubuntu@NEW_IP ./start.sh"
    fi
    ok "Robot SSH port reachable"
    if ! ssh "${SSH_OPTS[@]}" -o BatchMode=yes -o ControlMaster=no "$ROBOT_HOST" true 2>/dev/null; then
        warn "No SSH key accepted by the robot."
        if [ -t 0 ]; then
            local answer
            read -r -p "        Install your SSH key on the robot (password requested once)? [Y/n] " answer
            case "$answer" in
                n|N|no|non) ;;
                *) ssh-copy-id -p "$ROBOT_SSH_PORT" -o ConnectTimeout=6 -o StrictHostKeyChecking=accept-new "$ROBOT_HOST" \
                       || warn "ssh-copy-id failed: the password will be requested below." ;;
            esac
        fi
    fi
    # Master connection: all subsequent commands reuse it.
    ssh "${SSH_OPTS[@]}" -o ControlMaster=yes -o ControlPersist=yes -fN "$ROBOT_HOST" \
        || die "SSH connection refused (credentials in sshRobot.md)"
    OPENED_MASTER=1
    ok "Shared SSH connection opened"
}

deploy() {
    step "Bridge on the robot"
    [ -x "$DIST/$BINARY" ] || die "Binary missing: run ./start.sh build (with internet access) before joining the robot network."
    local newer
    newer=$(find "$ROOT/bridge/src" "$ROOT/bridge/Cargo.toml" -newer "$DIST/$BINARY" -type f 2>/dev/null | head -1)
    if [ -n "$newer" ] || ! cmp -s "$ROOT/bridge/run.sh" "$DIST/run.sh"; then
        warn "Sources changed since the last build: run ./start.sh build (with internet access) to include them."
    fi
    local local_sum remote_sum
    local_sum=$(shasum -a 256 "$DIST/$BINARY" | awk '{print $1}')
    remote_sum=$(ssh_robot "sha256sum ~/bridge/$BINARY 2>/dev/null | cut -d' ' -f1" || true)
    if [ "$local_sum" = "$remote_sum" ] && ssh_robot "cmp -s ~/bridge/run.sh /dev/stdin" < "$DIST/run.sh"; then
        ok "Robot bridge is up to date (${local_sum:0:12})"
        return
    fi
    if [ -z "$remote_sum" ]; then
        echo "        First installation in ~/bridge"
    else
        echo "        New version: ${remote_sum:0:12} -> ${local_sum:0:12}"
        # An executable that is running cannot be replaced.
        ctl stop
    fi
    ssh_robot "mkdir -p ~/bridge/target/release"
    # dist/ does not contain robot.env: preserve the robot configuration.
    scp -q -P "$ROBOT_SSH_PORT" -o "ControlPath=$CONTROL_PATH" -r "$DIST/." "$ROBOT_HOST:bridge/" || die "Copy failed"
    ssh_robot "cd ~/bridge && chmod +x run.sh $BINARY && sha256sum -c --quiet SHA256SUMS" \
        || die "Checksum mismatch after copying"
    ok "Bridge copied and verified"
}

check() {
    step "Robot diagnostics"
    if ctl check; then
        ok "Diagnostics found no blocking failures"
    else
        warn "Diagnostics reported failures (see above); the bridge will still be started."
    fi
}

start_bridge() {
    step "Starting bridge"
    ctl start || die "Bridge startup not confirmed (see logs above)"
}

TUNNEL=""
UI_PID=""
cleanup() {
    trap - EXIT INT TERM
    echo
    step "Shutting down"
    if [ -n "$TUNNEL" ]; then
        # Final explicit stop: the command expires after 500 ms regardless.
        curl -s --max-time 1 -X POST -H 'Content-Type: application/json' -d '{}' \
            "http://127.0.0.1:$TUNNEL/stop" >/dev/null 2>&1 || true
        ssh "${SSH_OPTS[@]}" -O cancel -L "$TUNNEL:127.0.0.1:$REMOTE_PORT" "$ROBOT_HOST" >/dev/null 2>&1 || true
    fi
    if [ -n "$UI_PID" ]; then kill "$UI_PID" 2>/dev/null || true; fi
    close_master
    echo "  UI and tunnel closed. Bridge status: ./start.sh status; stop: ./start.sh stop."
}

open_tunnel() {
    step "Tunnel to the bridge API"
    TUNNEL=$(free_port "$LOCAL_PORT") || die "No free local port starting at $LOCAL_PORT"
    ssh "${SSH_OPTS[@]}" -O forward -L "$TUNNEL:127.0.0.1:$REMOTE_PORT" "$ROBOT_HOST" >/dev/null \
        || die "Unable to open the tunnel"
    ok "http://127.0.0.1:$TUNNEL -> robot:127.0.0.1:$REMOTE_PORT"
    local i status=""
    for i in $(seq 1 40); do
        status=$(curl -s --max-time 1 "http://127.0.0.1:$TUNNEL/status" || true)
        [ -n "$status" ] && break
        sleep 0.5
    done
    if [ -z "$status" ]; then
        warn "The bridge is not responding through the tunnel (BRIDGE_BIND in robot.env must be 127.0.0.1:8000)."
    else
        ok "Bridge : $status"
        case "$status" in
            *'"not ready"'*) warn "Robot not ready: normal during roughly 30 s of bringup calibration; the reason is displayed in the UI." ;;
        esac
    fi
}

start_ui() {
    step "Web UI"
    local port
    port=$(free_port "$UI_PORT") || die "No free port for the UI"
    python3 "$ROOT/ui/server.py" --port "$port" --bridge "http://127.0.0.1:$TUNNEL" \
        --robot "$ROBOT_HOST" --ssh-port "$ROBOT_SSH_PORT" --control-path "$CONTROL_PATH" --ctl "$CTL" &
    UI_PID=$!
    local i
    for i in $(seq 1 20); do
        curl -s --max-time 1 "http://127.0.0.1:$port/local/info" >/dev/null 2>&1 && break
        kill -0 "$UI_PID" 2>/dev/null || die "The UI server stopped"
        sleep 0.25
    done
    ok "http://127.0.0.1:$port"
    if [ "${NO_BROWSER:-0}" != 1 ]; then open "http://127.0.0.1:$port"; fi
    echo
    echo "  ${B}Ready.${N} Ctrl+C closes the UI and tunnel (the robot receives a stop command)."
}

watch_link() {
    # Monitor the SSH connection; the UI stays open and reports connection loss.
    while kill -0 "$UI_PID" 2>/dev/null; do
        if ! master_alive; then
            warn "SSH connection lost: run ./start.sh again once the robot is reachable."
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
        command -v docker >/dev/null || die "Docker not found"
        docker info >/dev/null 2>&1 || die "Start Docker Desktop (internet access is needed for the first build)"
        bash "$ROOT/bridge/build-docker.sh"
        ;;
    help|-h|--help) usage ;;
    *) usage; exit 2 ;;
esac
