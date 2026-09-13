"""Pigeon, a local cold outreach CRM.

Serves app.html and a small JSON API over contacts.json, which sits next to
this file. Standard library only, binds to localhost only.

Run:  python serve.py
"""
import argparse
import errno
import io
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "app.html")
DEFAULT_PORT = 8642

DATA = os.path.join(HERE, "contacts.json")
_lock = threading.Lock()


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

    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def do_GET(self):
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
        self._send(404, b'{"error":"not found"}')

    def do_POST(self):
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
    global DATA
    ap = argparse.ArgumentParser(description="Run Pigeon on localhost.")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--data", default=DATA, help="path to contacts.json")
    ap.add_argument("--no-browser", action="store_true",
                    help="do not open the page on start")
    args = ap.parse_args()
    DATA = os.path.abspath(args.data)

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
    print("  %d contacts loaded from %s" % (len(load()), DATA))
    print("  serving %s" % url)
    print("  press Ctrl+C to stop")
    sys.stdout.flush()

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
