"""Serveur local de l'interface web, lancé par start.sh sur le Mac.

- sert index.html ;
- relaie /api/* vers le bridge (tunnel SSH), donc pas de CORS ;
- /local/* exécute robot_ctl.sh sur le robot par la connexion SSH partagée.
Bibliothèque standard uniquement : fonctionne sans internet.
"""

import argparse
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import ProxyHandler, Request, build_opener

HERE = Path(__file__).resolve().parent
MAX_BODY = 4096
opener = build_opener(ProxyHandler({}))


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--bridge", default="http://127.0.0.1:8000")
    parser.add_argument("--robot", default="ubuntu@192.168.1.109")
    parser.add_argument("--ssh-port", default="22")
    parser.add_argument("--control-path", default="/tmp/tb3-ssh-%C")
    parser.add_argument("--ctl", default=str(HERE.parent / "bridge/tools/robot_ctl.sh"))
    return parser.parse_args()


ARGS = parse_args()


def robot_ctl(*arguments, timeout=60):
    """Exécute robot_ctl.sh sur le robot ; renvoie (code, sortie)."""
    command = ["ssh", "-p", ARGS.ssh_port, "-o", f"ControlPath={ARGS.control_path}", "-o", "BatchMode=yes",
               "-o", "ConnectTimeout=6", ARGS.robot, "bash", "-s", "--", *arguments]
    try:
        with open(ARGS.ctl, "rb") as script:
            result = subprocess.run(command, stdin=script, capture_output=True,
                                    timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "Délai dépassé"
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    return result.returncode, output


class Handler(BaseHTTPRequestHandler):
    server_version = "TB3UI/1"

    def log_message(self, fmt, *args):
        # Les requêtes de l'interface (10 Hz) noieraient le terminal.
        pass

    def send(self, code, body, kind="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("Corps trop volumineux")
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
                                 response.headers.get("Content-Type", "application/json"))
        except HTTPError as error:
            return self.send(error.code, error.read(),
                             error.headers.get("Content-Type", "application/json"))
        except (URLError, TimeoutError, ConnectionError) as error:
            reason = getattr(error, "reason", error)
            return self.send(502, {"error": f"Bridge injoignable : {reason}", "bridge": False})

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if url.path.startswith("/api/"):
            return self.proxy("GET")
        if url.path == "/local/info":
            return self.send(200, {"robot": ARGS.robot, "bridge": ARGS.bridge})
        if url.path == "/local/log":
            lines = parse_qs(url.query).get("lines", ["200"])[0]
            lines = str(max(10, min(2000, int(lines)))) if lines.isdigit() else "200"
            code, output = robot_ctl("log", lines, timeout=15)
            return self.send(200, {"code": code, "output": output})
        if url.path == "/local/check":
            code, output = robot_ctl("check", timeout=90)
            return self.send(200, {"code": code, "output": output})
        return self.send(404, {"error": "Introuvable"})

    def do_POST(self):
        url = urlparse(self.path)
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
        return self.send(404, {"error": "Introuvable"})


def main():
    server = ThreadingHTTPServer(("127.0.0.1", ARGS.port), Handler)
    server.daemon_threads = True
    print(f"Interface : http://127.0.0.1:{ARGS.port}  (bridge {ARGS.bridge})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
