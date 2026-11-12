#!/bin/bash
# Double-click: starts a small local server and opens the presentation.
cd "$(dirname "$0")"
PORT=8770
(sleep 1; open "http://localhost:$PORT/") &
exec python3 -m http.server "$PORT" --bind 127.0.0.1
