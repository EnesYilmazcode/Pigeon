"""Runs the Claude Code CLI against this folder and streams its JSON back.

One turn at a time, one resumable session, so the pane in the browser is the
same conversation from message to message.

The pane has no way to answer a permission prompt, so the rules are fixed at
launch instead: TOOLS is pre-approved, and --permission-prompts none turns
anything outside it into an instant deny rather than a process that sits there
forever waiting on nobody.
"""
import json
import os
import shutil
import subprocess
import threading
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, ".pigeon-session.json")

# File tools so it can edit contacts.json, Bash so "renumber everyone" can be
# one python line, web tools so it can check a posting is still open. No Task:
# a subagent would hide its work from the pane and cost a lot more.
TOOLS = ["Read", "Edit", "Write", "Glob", "Grep", "Bash", "WebSearch", "WebFetch"]

TURN_TIMEOUT = 900  # a turn that has run 15 minutes is stuck, not thinking

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _exe():
    return shutil.which("claude")


class Bridge(object):
    def __init__(self, cwd=HERE, state=STATE):
        self.cwd = cwd
        self.state = state
        self.turn = threading.Lock()
        self._plock = threading.Lock()
        self.proc = None
        self.stopping = False
        self.session_id = str(uuid.uuid4())
        self.started = False
        self._restore()

    # ---- session id, kept across restarts so the pane remembers the thread ---

    def _restore(self):
        try:
            with open(self.state, encoding="utf-8") as f:
                s = json.load(f)
            if s.get("sessionId"):
                self.session_id = s["sessionId"]
                self.started = bool(s.get("started"))
        except Exception:
            pass

    def _persist(self):
        try:
            tmp = self.state + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"sessionId": self.session_id, "started": self.started}, f)
            os.replace(tmp, self.state)
        except Exception:
            pass

    def reset(self):
        self.session_id = str(uuid.uuid4())
        self.started = False
        self._persist()
        return self.session_id

    def status(self):
        return {
            "available": bool(_exe()),
            "busy": self.turn.locked(),
            "sessionId": self.session_id,
            "started": self.started,
            "cwd": self.cwd,
            "tools": TOOLS,
        }

    # --------------------------------------------------------------- stopping

    def stop(self):
        with self._plock:
            p = self.proc
        if p is None or p.poll() is not None:
            return False
        self.stopping = True  # so the nonzero exit reads as stopped, not failed
        try:
            if os.name == "nt":
                # The CLI spawns children; /T takes the whole tree with it.
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)],
                               capture_output=True, creationflags=_NO_WINDOW)
            else:
                p.terminate()
        except Exception:
            return False
        return True

    # ----------------------------------------------------------------- a turn

    def run(self, message, context=""):
        """Yield dicts: every line the CLI prints, plus our own 'desk' events."""
        exe = _exe()
        if not exe:
            yield {"type": "desk", "subtype": "error",
                   "message": "The claude command is not on PATH, so the pane "
                              "has nothing to talk to. Install Claude Code and "
                              "restart the server."}
            return

        if not self.turn.acquire(False):
            yield {"type": "desk", "subtype": "error",
                   "message": "Claude is still working on the last message."}
            return

        try:
            message = (message or "").strip()
            context = (context or "").strip()
            prompt = (context + "\n\n" + message).strip() if context else message

            args = [
                exe, "-p", prompt,
                "--output-format", "stream-json",
                "--verbose",
                "--include-partial-messages",
                "--permission-mode", "acceptEdits",
                "--permission-prompts", "none",
                "--tools", ",".join(TOOLS),
                "--allowedTools", ",".join(TOOLS),
            ]
            args += (["--resume", self.session_id] if self.started
                     else ["--session-id", self.session_id])

            self.stopping = False
            yield {"type": "desk", "subtype": "turn_start",
                   "sessionId": self.session_id, "resumed": self.started}

            try:
                p = subprocess.Popen(
                    args, cwd=self.cwd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    encoding="utf-8", errors="replace", bufsize=1,
                    creationflags=_NO_WINDOW,
                )
            except Exception as e:
                yield {"type": "desk", "subtype": "error",
                       "message": "Could not start claude: %s" % e}
                return

            with self._plock:
                self.proc = p

            errbuf = []
            drain = threading.Thread(target=_drain, args=(p.stderr, errbuf))
            drain.daemon = True
            drain.start()
            killer = threading.Timer(TURN_TIMEOUT, self.stop)
            killer.daemon = True
            killer.start()

            saw_init = False
            try:
                for line in p.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    # The session is real the moment it initialises, so the next
                    # message resumes it even if this turn dies halfway.
                    if obj.get("type") == "system" and obj.get("subtype") == "init":
                        saw_init = True
                        if obj.get("session_id"):
                            self.session_id = obj["session_id"]
                        if not self.started:
                            self.started = True
                            self._persist()
                    yield obj
            finally:
                killer.cancel()
                try:
                    code = p.wait(timeout=10)
                except Exception:
                    code = -1
                with self._plock:
                    self.proc = None
                # Let stderr finish so the error tail below is whole, then close
                # both pipes; otherwise every turn leaks two handles.
                drain.join(2)
                p.stdout.close()
                p.stderr.close()

            if code != 0 and self.stopping:
                yield {"type": "desk", "subtype": "stopped",
                       "message": "Stopped. Anything it had already written is "
                                  "on disk; anything mid-flight is not."}
            elif code != 0:
                tail = "".join(errbuf)[-600:].strip()
                if not saw_init and self.started:
                    # The saved conversation is gone or unreadable. Start clean
                    # so the next message is not stuck retrying a dead session.
                    self.reset()
                    tail = (tail + "\n\nThat conversation could not be resumed, "
                                   "so this is a fresh session. Send the "
                                   "message again.").strip()
                yield {"type": "desk", "subtype": "error",
                       "message": tail or "claude exited with code %s" % code,
                       "code": code}

            yield {"type": "desk", "subtype": "turn_end", "code": code}
        finally:
            self.turn.release()


def _drain(stream, into):
    try:
        for line in stream:
            into.append(line)
    except Exception:
        pass
