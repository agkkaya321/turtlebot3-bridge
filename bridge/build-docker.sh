#!/usr/bin/env bash
# Compilation sur le Mac ; Rust et ROS restent dans Docker.
set -euo pipefail
cd -- "$(dirname -- "$0")"
docker build --platform linux/arm64 --target artifact \
    --output type=local,dest=dist --progress=plain .
cp dist/Cargo.lock Cargo.lock
echo "Prêt à copier sur le robot : $(pwd)/dist"
