"""Runs the real server on a spare port against a throwaway contacts.json.

Run:  python -m unittest discover tests
"""
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class ServerTest(unittest.TestCase):
    seed = [{"id": "ada-park", "name": "Ada Park", "status": "queued"}]

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = os.path.join(self.tmp, "contacts.json")
        if self.seed is not None:
            with open(self.data, "w", encoding="utf-8") as f:
                json.dump(self.seed, f)
        self.port = free_port()
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "serve.py"), "--port", str(self.port),
             "--data", self.data, "--no-browser"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.05)
        self.fail("server did not start")

    def tearDown(self):
        self.proc.kill()
        self.proc.wait()
        self.proc.stdout.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        conn.request(method, path, json.dumps(body) if body is not None else None, h)
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        try:
            return r.status, json.loads(raw.decode("utf-8"))
        except ValueError:
            return r.status, raw

    def on_disk(self):
        with open(self.data, encoding="utf-8") as f:
            return json.load(f)

    def test_list(self):
        code, rows = self.call("GET", "/api/contacts")
        self.assertEqual(code, 200)
        self.assertEqual(rows[0]["id"], "ada-park")

    def test_add_update_delete(self):
        code, _ = self.call("POST", "/api/contacts", {"id": "ben-ruiz", "name": "Ben Ruiz"})
        self.assertEqual(code, 201)
        self.assertEqual(len(self.on_disk()), 2)

        code, row = self.call("PUT", "/api/contacts/ben-ruiz", {"status": "sent"})
        self.assertEqual(code, 200)
        self.assertEqual(row["name"], "Ben Ruiz")
        self.assertEqual(self.on_disk()[1]["status"], "sent")

        code, _ = self.call("DELETE", "/api/contacts/ben-ruiz")
        self.assertEqual(code, 200)
        self.assertEqual([r["id"] for r in self.on_disk()], ["ada-park"])

    def test_rejects_bad_writes(self):
        self.assertEqual(self.call("POST", "/api/contacts", {"name": "No Id"})[0], 400)
        self.assertEqual(self.call("POST", "/api/contacts", {"id": "ada-park"})[0], 409)
        self.assertEqual(self.call("PUT", "/api/contacts/nobody", {"x": 1})[0], 404)
        self.assertEqual(self.call("DELETE", "/api/contacts/nobody")[0], 404)
        self.assertEqual(self.on_disk(), self.seed)

    def test_unknown_path(self):
        self.assertEqual(self.call("GET", "/api/nope")[0], 404)


if __name__ == "__main__":
    unittest.main()
