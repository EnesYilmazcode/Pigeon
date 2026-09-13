"""Pigeon, a local cold outreach CRM.

Serves app.html and a small JSON API over contacts.json, which sits next to
this file, plus any logos fetch_logos.py cached beside it. Standard library
only, binds to localhost only.

The Claude Code pane in the page talks to /api/claude/*, which runs the claude
CLI in this folder and streams its output straight back. See claude_bridge.py.

Run:  python serve.py
"""
import argparse
import errno
import io
import json
import os
import shutil
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import claude_bridge

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "app.html")
EXAMPLE = os.path.join(HERE, "contacts.example.json")
DEFAULT_PORT = 8642

DATA = os.path.join(HERE, "contacts.json")
_lock = threading.Lock()
bridge = None  # made in main(), once DATA is known


def load():
    if not os.path.exists(DATA):
        return []
    with io.open(DATA, encoding="utf-8") as f:
        return json.load(f)


def save(rows):
    """Temp file then replace, so a crash mid-write cannot truncate the data."""
    tmp = DATA + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(rows, ensure_ascii=False, indent=1))
    os.replace(tmp, DATA)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # quiet

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _guard(self):
        """Refuse requests that a page on some other site could have sent.

        Any tab in the browser can reach this port. Checking Host stops DNS
        rebinding, and checking Origin stops a page elsewhere from posting here.
        """
        port = self.server.server_address[1]
        hosts = ("localhost:%d" % port, "127.0.0.1:%d" % port)
        host = (self.headers.get("Host") or "").lower()
        origin = self.headers.get("Origin")
        if host in hosts and (origin is None or origin.lower() in
                              ["http://" + h for h in hosts]):
            return True
        self._json(403, {"error": "cross-site request refused"})
        return False

    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def do_GET(self):
        if not self._guard():
            return
        if self.path in ("/", "/index.html", "/app.html"):
            if not os.path.exists(PAGE):
                self._send(500, b"app.html is missing", "text/plain; charset=utf-8")
                return
            with io.open(PAGE, "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
            return
        if self.path == "/api/contacts":
            with _lock:
                self._json(200, load())
            return
        if self.path == "/api/claude":
            self._json(200, bridge.status())
            return
        if self.path.startswith("/logos/"):
            self._logo(self.path[len("/logos/"):])
            return
        self._send(404, b'{"error":"not found"}')

    TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml",
             ".ico": "image/x-icon"}

    def _logo(self, name):
        name = name.split("?")[0]
        # Only ever serve a bare filename out of the logos folder.
        if not name or "/" in name or "\\" in name or name.startswith("."):
            self._send(404, b"", "text/plain")
            return
        ext = os.path.splitext(name)[1].lower()
        if ext not in self.TYPES:
            self._send(404, b"", "text/plain")
            return
        path = os.path.join(os.path.dirname(DATA), "logos", name)
        if not os.path.isfile(path):
            self._send(404, b"", "text/plain")
            return
        with io.open(path, "rb") as f:
            blob = f.read()
        self.send_response(200)
        self.send_header("Content-Type", self.TYPES[ext])
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(blob)

    def _stream(self, events):
        """NDJSON, one object per line, flushed as it arrives.

        No Content-Length: the response is HTTP/1.0 and ends when the socket
        closes, which is what lets the pane render a turn while it runs.
        """
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        for obj in events:
            blob = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
            try:
                self.wfile.write(blob)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                # Tab closed or navigated away mid-turn. Nothing is listening,
                # so do not leave a claude process running behind it.
                bridge.stop()
                return

    def do_POST(self):
        if not self._guard():
            return
        if self.path == "/api/claude/chat":
            try:
                req = self._read_body()
            except Exception as e:
                self._json(400, {"error": str(e)})
                return
            msg = (req.get("message") or "").strip()
            if not msg:
                self._json(400, {"error": "message is required"})
                return
            self._stream(bridge.run(msg, req.get("context") or ""))
            return
        if self.path == "/api/claude/stop":
            self._json(200, {"stopped": bridge.stop()})
            return
        if self.path == "/api/claude/reset":
            if bridge.turn.locked():
                self._json(409, {"error": "a turn is still running"})
                return
            self._json(200, {"sessionId": bridge.reset()})
            return
        if self.path != "/api/contacts":
            self._send(404, b'{"error":"not found"}')
            return
        try:
            row = self._read_body()
        except Exception as e:
            self._json(400, {"error": str(e)})
            return
        with _lock:
            rows = load()
            if not row.get("id"):
                self._json(400, {"error": "id is required"})
                return
            if any(r.get("id") == row["id"] for r in rows):
                self._json(409, {"error": "id already exists"})
                return
            rows.append(row)
            save(rows)
        self._json(201, row)

    def do_PUT(self):
        if not self._guard():
            return
        if not self.path.startswith("/api/contacts/"):
            self._send(404, b'{"error":"not found"}')
            return
        cid = self.path[len("/api/contacts/"):]
        try:
            fields = self._read_body()
        except Exception as e:
            self._json(400, {"error": str(e)})
            return
        with _lock:
            rows = load()
            for r in rows:
                if r.get("id") == cid:
                    r.update(fields)
                    save(rows)
                    self._json(200, r)
                    return
        self._json(404, {"error": "no contact with that id"})

    def do_DELETE(self):
        if not self._guard():
            return
        if not self.path.startswith("/api/contacts/"):
            self._send(404, b'{"error":"not found"}')
            return
        cid = self.path[len("/api/contacts/"):]
        with _lock:
            rows = load()
            keep = [r for r in rows if r.get("id") != cid]
            if len(keep) == len(rows):
                self._json(404, {"error": "no contact with that id"})
                return
            save(keep)
        self._json(200, {"deleted": cid})


def main():
    global DATA, bridge
    ap = argparse.ArgumentParser(description="Run Pigeon on localhost.")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--data", default=DATA, help="path to contacts.json")
    ap.add_argument("--no-browser", action="store_true",
                    help="do not open the page on start")
    args = ap.parse_args()
    DATA = os.path.abspath(args.data)
    bridge = claude_bridge.Bridge(
        HERE, state=os.path.join(os.path.dirname(DATA), ".pigeon-session.json"))

    # First run. Give the page something to show; delete them whenever.
    seeded = not os.path.exists(DATA) and os.path.exists(EXAMPLE)
    if seeded:
        shutil.copyfile(EXAMPLE, DATA)

    url = "http://localhost:%d/" % args.port
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as e:
        if e.errno not in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", 10048)):
            raise
        # Started twice. Show the one that is already up rather than a traceback.
        print("Pigeon is already running at %s" % url)
        if not args.no_browser:
            webbrowser.open(url)
        sys.exit(0)

    print("Pigeon")
    if seeded:
        print("  first run, copied the example contacts to %s" % DATA)
    print("  %d contacts loaded from %s" % (len(load()), DATA))
    print("  serving %s" % url)
    print("  claude bridge: %s"
          % ("ready" if bridge.status()["available"]
             else "off, the claude command is not on PATH"))
    print("  press Ctrl+C to stop")
    sys.stdout.flush()

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        bridge.stop()


if __name__ == "__main__":
    main()
