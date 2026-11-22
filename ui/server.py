"""Local web UI server, started by start.sh on the Mac.

- sert index.html ;
- relaie /api/* vers le bridge (tunnel SSH), donc pas de CORS ;
- relaie les images de la caméra sur des connexions gardées ouvertes ;
- /local/* exécute robot_ctl.sh sur le robot par la connexion SSH partagée.
Bibliothèque standard uniquement : fonctionne sans internet.
"""

import argparse
import http.client
import json
import mimetypes
import queue
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import ProxyHandler, Request, build_opener
from posture import PostureStore

HERE = Path(__file__).resolve().parent
MAX_BODY = 4096
opener = build_opener(ProxyHandler({}))
POSTURE = PostureStore()


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--preview", action="store_true",
                        help="Aperçu de l'interface sans accès au bridge ni au robot")
    parser.add_argument("--bridge", default="http://127.0.0.1:8000")
    parser.add_argument("--robot", default="ubuntu@192.168.1.109")
    parser.add_argument("--ssh-port", default="22")
    parser.add_argument("--control-path", default="/tmp/tb3-ssh-%C")
    parser.add_argument("--ctl", default=str(HERE.parent / "bridge/tools/robot_ctl.sh"))
    return parser.parse_args()


ARGS = parse_args()
BRIDGE = urlparse(ARGS.bridge)
# Connexions gardées ouvertes vers le bridge pour la vidéo : une image ne paie
# pas l'ouverture d'un nouveau canal dans le tunnel SSH (un aller-retour Wi-Fi).
CAMERA_POOL = queue.LifoQueue(maxsize=4)


def frame_headers(headers):
    """En-têtes X-Frame-* (taille, qualité, âge…) transmis à l'interface."""
    return {k: v for k, v in headers.items() if k.lower().startswith("x-frame-")}


def robot_ctl(*arguments, timeout=60):
    """Run robot_ctl.sh on the robot and return (exit code, output)."""
    command = ["ssh", "-p", ARGS.ssh_port, "-o", f"ControlPath={ARGS.control_path}", "-o", "BatchMode=yes",
               "-o", "ConnectTimeout=6", ARGS.robot, "bash", "-s", "--", *arguments]
    try:
        with open(ARGS.ctl, "rb") as script:
            result = subprocess.run(command, stdin=script, capture_output=True,
                                    timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "Timed out"
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    return result.returncode, output


class Handler(BaseHTTPRequestHandler):
    server_version = "TB3UI/1"

    def log_message(self, fmt, *args):
        # UI requests (10 Hz) would flood the terminal.
        pass

    def send(self, code, body, kind="application/json", extra=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def body(self, max_size=MAX_BODY):
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > max_size:
            raise ValueError("Request body too large")
        return self.rfile.read(length) if length else b""

    def proxy(self, method):
        path = self.path[len("/api"):] or "/"
        try:
            data = self.body() if method == "POST" else None
        except ValueError as error:
            return self.send(413, {"error": str(error)})
        request = Request(ARGS.bridge + path, data=data, method=method,
                          headers={"Content-Type": "application/json"})
        try:
            with opener.open(request, timeout=5) as response:
                return self.send(response.status, response.read(),
                                 response.headers.get("Content-Type", "application/json"),
                                 frame_headers(response.headers))
        except HTTPError as error:
            return self.send(error.code, error.read(),
                             error.headers.get("Content-Type", "application/json"))
        except (URLError, TimeoutError, ConnectionError) as error:
            reason = getattr(error, "reason", error)
            return self.send(502, {"error": f"Bridge unreachable: {reason}", "bridge": False})

    def camera_frame(self):
        """GET /api/camera/frame : le bridge attend au plus 2,5 s une image."""
        path = self.path[len("/api"):]
        while True:
            try:
                connection, reused = CAMERA_POOL.get_nowait(), True
            except queue.Empty:
                connection = http.client.HTTPConnection(BRIDGE.hostname, BRIDGE.port or 80, timeout=6)
                reused = False
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                data = response.read()
                break
            except (OSError, http.client.HTTPException) as error:
                connection.close()
                if not reused:
                    return self.send(502, {"error": f"Bridge injoignable : {error}", "bridge": False})
                # Connexion fermée pendant l'inactivité : essayer la suivante ou une neuve.
        if response.will_close:
            connection.close()
        else:
            try:
                CAMERA_POOL.put_nowait(connection)
            except queue.Full:
                connection.close()
        return self.send(response.status, data, response.getheader("Content-Type", "application/json"),
                         frame_headers(response.headers))

    def do_GET(self):
        url = urlparse(self.path)
        if url.path.startswith("/assets/"):
            asset = (HERE / url.path.lstrip("/")).resolve()
            if not asset.is_relative_to(HERE / "assets") or not asset.is_file():
                return self.send(404, {"error": "Not found"})
            return self.send(200, asset.read_bytes(),
                             mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
        if url.path == "/local/info":
            return self.send(200, {"robot": ARGS.robot, "bridge": ARGS.bridge,
                                   "preview": ARGS.preview})
        if ARGS.preview and (url.path.startswith("/api/") or
                             url.path in ("/local/log", "/local/check")):
            return self.send(503, {"error": "Mode aperçu : robot déconnecté", "preview": True})
        if url.path == "/local/posture":
            return self.send(200, POSTURE.snapshot())
        if url.path == "/api/camera/frame":
            return self.camera_frame()
        if url.path in ("/", "/index.html"):
            return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if url.path.startswith("/api/"):
            return self.proxy("GET")
        if url.path == "/local/log":
            lines = parse_qs(url.query).get("lines", ["200"])[0]
            lines = str(max(10, min(2000, int(lines)))) if lines.isdigit() else "200"
            code, output = robot_ctl("log", lines, timeout=15)
            return self.send(200, {"code": code, "output": output})
        if url.path == "/local/check":
            code, output = robot_ctl("check", timeout=90)
            return self.send(200, {"code": code, "output": output})
        return self.send(404, {"error": "Not found"})

    def do_POST(self):
        url = urlparse(self.path)
        if ARGS.preview:
            return self.send(403, {"error": "Commandes désactivées en mode aperçu", "preview": True})
        if url.path == "/local/posture":
            try:
                POSTURE.update(json.loads(self.body(max_size=750_000)))
            except (ValueError, UnicodeDecodeError) as error:
                return self.send(400, {"error": str(error)})
            return self.send(200, {"ok": True})
        if url.path.startswith("/api/"):
            return self.proxy("POST")
        actions = {"/local/restart": ("stop", "start"), "/local/stop": ("stop",),
                   "/local/start": ("start",)}
        if url.path in actions:
            outputs, code = [], 0
            for step in actions[url.path]:
                code, output = robot_ctl(step, timeout=40)
                outputs.append(output)
                if code != 0:
                    break
            return self.send(200, {"code": code, "output": "\n".join(outputs)})
        return self.send(404, {"error": "Not found"})


def main():
    server = ThreadingHTTPServer(("127.0.0.1", ARGS.port), Handler)
    server.daemon_threads = True
    mode = "aperçu local, sans robot" if ARGS.preview else f"bridge {ARGS.bridge}"
    print(f"UI: http://127.0.0.1:{server.server_port}  ({mode})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
