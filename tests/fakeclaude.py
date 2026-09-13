"""A stand-in claude command that echoes the prompt as stream-json.

Every call appends its arguments to $FAKE_CLAUDE_LOG. FAKE_CLAUDE_MODE=gone
makes it fail the way a resume of a deleted conversation does.
"""
import os
import stat
import sys

SCRIPT = r'''
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


def install(folder):
    """Write a runnable `claude` into folder and return its path."""
    script = os.path.join(folder, "fake_claude.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(SCRIPT)
    if os.name == "nt":
        exe = os.path.join(folder, "claude.cmd")
        with open(exe, "w") as f:
            f.write('@"%s" "%s" %%*\n' % (sys.executable, script))
    else:
        exe = os.path.join(folder, "claude")
        with open(exe, "w") as f:
            f.write("#!%s\n%s" % (sys.executable, SCRIPT))
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IEXEC)
    return exe
