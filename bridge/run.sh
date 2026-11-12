#!/usr/bin/env bash
# Run on the Raspberry Pi after building, never on the Mac.
set -e
cd -- "$(dirname -- "$0")"
source /opt/ros/jazzy/setup.bash
if [ -f "$HOME/turtlebot3_ws/install/setup.bash" ]; then
    source "$HOME/turtlebot3_ws/install/setup.bash"
fi
# A non-interactive SSH session (start.sh) does not read ~/.bashrc: import
# its TurtleBot3 variables. robot.env is loaded afterward and takes precedence.
if [ -f "$HOME/.bashrc" ]; then
    eval "$(grep -E '^[[:space:]]*export[[:space:]]+(ROS_DOMAIN_ID|TURTLEBOT3_MODEL|LDS_MODEL|OPENCR_PORT|OPENCR_MODEL|RMW_IMPLEMENTATION|ROS_LOCALHOST_ONLY|ROS_AUTOMATIC_DISCOVERY_RANGE)=' "$HOME/.bashrc" || true)"
fi
# Optional robot-specific settings, shared with the child bringup process.
if [ -f ./robot.env ]; then
    source ./robot.env
fi
exec ./target/release/turtlebot-speed-bridge
