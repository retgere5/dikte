"""Starting an external process the same way on every system.

Windows opens a console window for every child of a windowless process unless
CREATE_NO_WINDOW says otherwise: with the tray icon under pythonw.exe, every
dictation would flash one for ffmpeg and another for the model server.
CreateProcess also does not run the .cmd shims npm installs from a bare name,
which is how Claude Code and Codex arrive, so the program name is resolved
through PATH the way the shell would. Both answers are read per call rather
than settled at import, so a test can stand on another platform.
"""

import shutil
import subprocess
import sys


def flags():
    """creationflags for a child no console window should flash for."""
    if sys.platform == "win32":
        # CREATE_NO_WINDOW only exists on the subprocess module built on a real
        # Windows interpreter (CPython gates the _winapi import on _mswindows,
        # decided once at interpreter startup, not on this mocked sys.platform),
        # so a test standing here on another platform needs the same fallback
        # value it asserts against.
        return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return 0


def resolve(cmd):
    """cmd with its program resolved to a full path on Windows.

    shutil.which honours PATHEXT, so a bare "claude" finds claude.exe and
    claude.cmd alike; a name which cannot resolve is left for Popen to
    report, which keeps the error message the caller already handles.
    """
    if sys.platform != "win32" or not cmd:
        return cmd
    found = shutil.which(cmd[0])
    return [found, *cmd[1:]] if found else cmd
