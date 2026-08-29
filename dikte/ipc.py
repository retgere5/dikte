"""The socket the running instance listens on, and one request over it.

A command typed at a terminal is answered rather than only obeyed: the reply
carries the transcript, the agent's answer, or the reason nothing happened,
which is what lets a script wait for a dictation instead of guessing when it is
done. One JSON object goes each way per connection. A bare verb is still
understood, because that is what earlier versions sent and what a stale KDE
shortcut may still send.
"""

import getpass
import json
import os
import sys

from PyQt6.QtNetwork import QLocalSocket


def _server_name(platform=None):
    """One name per user: the uid where there is one, the login name on Windows.

    Windows has no getuid, so the login name stands in for it here, but the
    \\\\.\\pipe namespace QLocalSocket maps this name into is machine-wide, not
    per session: the name only keeps two accounts' pipes from colliding by
    name. What actually keeps one account off another account's pipe is the
    single-SID DACL QLocalServer's UserAccessOption applies, in app.py.
    """
    if (platform or sys.platform) == "win32":
        return "dikte-" + getpass.getuser()
    return "dikte-" + str(os.getuid())


SERVER_NAME = _server_name()

# Long enough for a process that is already running to answer, short enough that
# "nothing is running" is not a noticeable pause in front of a key press.
CONNECT_MS = 800


def package_root():
    """The directory the dikte package sits in, which is the checkout root.

    `python -m dikte` looks for the package on the path, so this is what the
    launchers and cli.launch_gui put on PYTHONPATH before starting one.
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def child_env():
    """A copy of the environment with the package parent on PYTHONPATH, so a
    child started as `python -m dikte` can import the package."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (package_root() + os.pathsep + existing
                         if existing else package_root())
    return env


def command_for(verb):
    """The command line a KDE shortcut runs for one of the verbs.

    Only ever used to register a Linux desktop shortcut, so it names the
    package parent on PYTHONPATH and launches the package with -m.
    """
    return f"env PYTHONPATH={package_root()} {sys.executable} -m dikte {verb}"


def send(cmd, wait=False, timeout=0, **args):
    """Send one request; the reply, or None when no instance is running.

    `wait` asks the instance to hold its reply back until the job the request
    started is over, which is how a terminal gets the transcript rather than
    only the fact that recording began. `timeout` bounds that wait in seconds;
    0 waits for as long as the job takes.
    """
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(CONNECT_MS):
        return None

    request = {"cmd": cmd}
    request.update({key: value for key, value in args.items() if value is not None})
    if wait:
        request["wait"] = True
    # A verb carrying nothing goes as the bare word it used to be, so that an
    # instance still running the older code obeys it: that is the one request
    # that has to work across an update, since it is how you install the update.
    line = cmd if list(request) == ["cmd"] else json.dumps(request)
    sock.write((line + "\n").encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(CONNECT_MS)

    limit = (int(timeout * 1000) if timeout else -1) if wait else CONNECT_MS
    buffer = b""
    while b"\n" not in buffer:
        if not sock.waitForReadyRead(limit):
            break
        buffer += bytes(sock.readAll())
    sock.disconnectFromServer()

    line = buffer.decode("utf-8", "replace").strip()
    if not line:
        # An instance from before replies existed answers by staying silent, and
        # for a fire-and-forget verb that silence means it went through. A wait
        # that ends this way did not: the run never reported back.
        return ({"ok": False, "legacy": True,
                 "error": "the running instance is too old to answer; "
                          "reload it with: dikte restart"}
                if wait else {"ok": True, "legacy": True})
    try:
        reply = json.loads(line)
    except json.JSONDecodeError:
        return {"ok": True, "legacy": True}
    return reply if isinstance(reply, dict) else {"ok": True, "legacy": True}
