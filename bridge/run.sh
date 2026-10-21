#!/usr/bin/env bash
# À lancer sur le Raspberry Pi après compilation, jamais sur le Mac.
set -e
cd -- "$(dirname -- "$0")"
source /opt/ros/jazzy/setup.bash
if [ -f "$HOME/turtlebot3_ws/install/setup.bash" ]; then
    source "$HOME/turtlebot3_ws/install/setup.bash"
fi
# Une session SSH non interactive (start.sh) ne lit pas ~/.bashrc : reprendre
# ses variables TurtleBot3. robot.env, chargé ensuite, reste prioritaire.
if [ -f "$HOME/.bashrc" ]; then
    eval "$(grep -E '^[[:space:]]*export[[:space:]]+(ROS_DOMAIN_ID|TURTLEBOT3_MODEL|LDS_MODEL|OPENCR_PORT|OPENCR_MODEL|RMW_IMPLEMENTATION|ROS_LOCALHOST_ONLY|ROS_AUTOMATIC_DISCOVERY_RANGE)=' "$HOME/.bashrc" || true)"
fi
# Facultatif : paramètres propres à ce robot, partagés avec le bringup enfant.
if [ -f ./robot.env ]; then
    source ./robot.env
fi
exec ./target/release/turtlebot-speed-bridge
