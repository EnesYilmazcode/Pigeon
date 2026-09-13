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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fakeclaude  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Server(unittest.TestCase):
    """Starts serve.py for each test. Holds no tests itself."""
    seed = [{"id": "ada-park", "name": "Ada Park", "status": "queued"}]

    def env(self):
        return None

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
            env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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


class ServerTest(Server):
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

    def test_logos(self):
        os.mkdir(os.path.join(self.tmp, "logos"))
        with open(os.path.join(self.tmp, "logos", "globex.png"), "wb") as fh:
            fh.write(b"\x89PNG fake")
        with open(os.path.join(self.tmp, "secret.png"), "wb") as fh:
            fh.write(b"not a logo")
        self.assertEqual(self.call("GET", "/logos/globex.png"), (200, b"\x89PNG fake"))
        self.assertEqual(self.call("GET", "/logos/missing.png")[0], 404)
        self.assertEqual(self.call("GET", "/logos/globex.txt")[0], 404)
        self.assertEqual(self.call("GET", "/logos/..%2Fsecret.png")[0], 404)
        self.assertEqual(self.call("GET", "/logos/../secret.png")[0], 404)

    def test_refuses_other_sites(self):
        row = {"id": "mallory", "name": "Mallory"}
        evil = {"Origin": "http://evil.example"}
        self.assertEqual(self.call("POST", "/api/contacts", row, evil)[0], 403)
        self.assertEqual(self.call("DELETE", "/api/contacts/ada-park", None, evil)[0], 403)
        # DNS rebinding: the request arrives with someone else's hostname.
        rebind = {"Host": "evil.example:%d" % self.port}
        self.assertEqual(self.call("GET", "/api/contacts", None, rebind)[0], 403)
        self.assertEqual(self.on_disk(), self.seed)

        same = {"Origin": "http://localhost:%d" % self.port}
        self.assertEqual(self.call("POST", "/api/contacts", row, same)[0], 201)


class ClaudeEndpointTest(Server):
    def env(self):
        bin_dir = os.path.join(self.tmp, "bin")
        os.mkdir(bin_dir)
        fakeclaude.install(bin_dir)
        self.log = os.path.join(self.tmp, "calls.jsonl")
        return dict(os.environ, PATH=bin_dir + os.pathsep + os.environ["PATH"],
                    FAKE_CLAUDE_LOG=self.log)

    def test_status(self):
        code, s = self.call("GET", "/api/claude")
        self.assertEqual(code, 200)
        self.assertTrue(s["available"])
        self.assertFalse(s["started"])

    def test_chat_streams_lines(self):
        code, raw = self.call("POST", "/api/claude/chat", {"message": "hi"})
        self.assertEqual(code, 200)
        events = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
        self.assertEqual(events[0]["subtype"], "turn_start")
        self.assertEqual(events[-1], {"type": "desk", "subtype": "turn_end", "code": 0})
        self.assertIn({"type": "result", "subtype": "success", "result": "echo hi"}, events)
        self.assertTrue(self.call("GET", "/api/claude")[1]["started"])
        # The session id lives beside the data, not in the checkout.
        self.assertTrue(os.path.exists(os.path.join(self.tmp, ".pigeon-session.json")))

        code, s = self.call("POST", "/api/claude/reset")
        self.assertEqual(code, 200)
        self.assertFalse(self.call("GET", "/api/claude")[1]["started"])

    def test_chat_needs_a_message(self):
        self.assertEqual(self.call("POST", "/api/claude/chat", {"message": " "})[0], 400)
        self.assertEqual(self.call("POST", "/api/claude/stop")[1], {"stopped": False})

    def test_other_sites_cannot_drive_claude(self):
        evil = {"Origin": "http://evil.example"}
        code, _ = self.call("POST", "/api/claude/chat", {"message": "rm -rf"}, evil)
        self.assertEqual(code, 403)
        self.assertFalse(os.path.exists(self.log))


class FirstRunTest(Server):
    seed = None  # no contacts.json yet

    def test_copies_examples(self):
        with open(os.path.join(ROOT, "contacts.example.json"), encoding="utf-8") as f:
            example = json.load(f)
        code, rows = self.call("GET", "/api/contacts")
        self.assertEqual(code, 200)
        self.assertEqual(rows, example)
        self.assertEqual(self.on_disk(), example)


if __name__ == "__main__":
    unittest.main()
