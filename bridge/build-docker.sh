#!/usr/bin/env bash
# Build on the Mac; Rust and ROS stay inside Docker.
set -euo pipefail
cd -- "$(dirname -- "$0")"
docker build --platform linux/arm64 --target artifact \
    --output type=local,dest=dist --progress=plain .
cp dist/Cargo.lock Cargo.lock
echo "Ready to copy to the robot: $(pwd)/dist"
