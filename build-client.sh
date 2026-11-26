#!/usr/bin/env bash
# Bundle the NextStep client and its dependencies for the current Mac.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"
BUILD_PYTHON="${BUILD_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
POSE_ASSET="$PROJECT_ROOT/client/next_step/posture_analysis/pose_landmarker_lite.task"

if [[ "$(uname -s)" != Darwin ]]; then
    echo "This script builds the macOS client; use ./start.sh build for the Linux bridge." >&2
    exit 1
fi
if [[ ! -x "$BUILD_PYTHON" || ! -f "$POSE_ASSET" ]]; then
    echo "Prepare .venv and the MediaPipe model as described in docs/POSTURE.md." >&2
    exit 1
fi
export PYINSTALLER_CONFIG_DIR="$PROJECT_ROOT/build/.cache/pyinstaller"
export MPLCONFIGDIR="$PROJECT_ROOT/build/.cache/matplotlib"
export XDG_CACHE_HOME="$PROJECT_ROOT/build/.cache"
mkdir -p "$PYINSTALLER_CONFIG_DIR" "$MPLCONFIGDIR"

if ! "$BUILD_PYTHON" -c 'import PyInstaller, cv2, mediapipe' >/dev/null; then
    echo "Install the posture dependencies and PyInstaller in .venv (see docs/POSTURE.md)." >&2
    exit 1
fi

"$BUILD_PYTHON" -m PyInstaller \
    --noconfirm --onedir --name nextstep \
    --distpath "$PROJECT_ROOT/build" \
    --workpath "$PROJECT_ROOT/build/.work" \
    --specpath "$PROJECT_ROOT/build/.spec" \
    --paths "$PROJECT_ROOT/client" \
    --collect-all mediapipe \
    --add-data "$POSE_ASSET:next_step/posture_analysis" \
    "$PROJECT_ROOT/client/next_step/main.py"

# Do not run the executable here: it starts the test selected in main.py.
echo "Client ready: $PROJECT_ROOT/build/nextstep/nextstep"
