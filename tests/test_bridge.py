"""Drives claude_bridge against a fake claude command, so no login or tokens."""
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import claude_bridge  # noqa: E402

FAKE = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CLAUDE_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\n")
if os.environ.get("FAKE_CLAUDE_MODE") == "gone":
    sys.stderr.write("No conversation found\n")
    sys.exit(1)
sid = args[args.index("--resume" if "--resume" in args else "--session-id") + 1]
said = "echo " + args[args.index("-p") + 1]
print(json.dumps({"type": "system", "subtype": "init", "session_id": sid}))
print(json.dumps({"type": "stream_event", "event": {"type": "content_block_delta",
      "index": 0, "delta": {"type": "text_delta", "text": said}}}))
print(json.dumps({"type": "result", "subtype": "success", "result": said}))
'''


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        script = os.path.join(self.tmp, "fake_claude.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(FAKE)
        if os.name == "nt":
            exe = os.path.join(self.tmp, "claude.cmd")
            with open(exe, "w") as f:
                f.write('@"%s" "%s" %%*\n' % (sys.executable, script))
        else:
            exe = os.path.join(self.tmp, "claude")
            with open(exe, "w") as f:
                f.write("#!%s\n%s" % (sys.executable, FAKE))
            os.chmod(exe, os.stat(exe).st_mode | stat.S_IEXEC)
        self.log = os.path.join(self.tmp, "calls.jsonl")
        os.environ["FAKE_CLAUDE_LOG"] = self.log
        os.environ.pop("FAKE_CLAUDE_MODE", None)
        self._exe = claude_bridge._exe
        claude_bridge._exe = lambda: exe
        self.state = os.path.join(self.tmp, "session.json")

    def tearDown(self):
        claude_bridge._exe = self._exe
        shutil.rmtree(self.tmp, ignore_errors=True)

    def bridge(self):
        return claude_bridge.Bridge(self.tmp, state=self.state)

    def calls(self):
        with open(self.log, encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_first_turn_then_resume(self):
        b = self.bridge()
        sid = b.session_id
        events = list(b.run("hello"))
        kinds = [(e["type"], e.get("subtype")) for e in events]
        self.assertEqual(kinds[0], ("desk", "turn_start"))
        self.assertIn(("system", "init"), kinds)
        self.assertIn(("result", "success"), kinds)
        self.assertEqual(events[-1], {"type": "desk", "subtype": "turn_end", "code": 0})

        first = self.calls()[0]
        self.assertEqual(first[first.index("--session-id") + 1], sid)
        self.assertEqual(first[first.index("--permission-prompts") + 1], "none")
        self.assertEqual(first[first.index("-p") + 1], "hello")

        # A restarted server picks the same conversation back up.
        again = self.bridge()
        self.assertTrue(again.started)
        list(again.run("again"))
        second = self.calls()[1]
        self.assertEqual(second[second.index("--resume") + 1], sid)
        self.assertNotIn("--session-id", second)

    def test_lost_session_starts_fresh(self):
        b = self.bridge()
        b.started = True
        old = b.session_id
        os.environ["FAKE_CLAUDE_MODE"] = "gone"
        events = list(b.run("hello"))
        err = [e for e in events if e.get("subtype") == "error"][0]
        self.assertIn("fresh session", err["message"])
        self.assertFalse(b.started)
        self.assertNotEqual(b.session_id, old)

    def test_one_turn_at_a_time(self):
        b = self.bridge()
        b.turn.acquire()
        events = list(b.run("hello"))
        b.turn.release()
        self.assertEqual(events[0]["subtype"], "error")
        self.assertFalse(os.path.exists(self.log))

    def test_no_cli_on_path(self):
        claude_bridge._exe = lambda: None
        events = list(self.bridge().run("hello"))
        self.assertIn("not on PATH", events[0]["message"])
        self.assertFalse(self.bridge().status()["available"])


if __name__ == "__main__":
    unittest.main()
