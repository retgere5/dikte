"""Starting an external process the same way on every system.

Windows opens a console window for every child of a windowless process unless
CREATE_NO_WINDOW says otherwise: with the tray icon under pythonw.exe, every
dictation would flash one for ffmpeg and another for the model server.
CreateProcess also does not run the .cmd shims npm installs from a bare name,
which is how Claude Code and Codex arrive, so the program name is resolved
through PATH the way the shell would. Both answers are read per call rather
than settled at import, so a test can stand on another platform.
"""

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile


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

    This is only about finding the .cmd/.bat shim npm installs; it says
    nothing about where PATH itself is searched. shutil.which and
    CreateProcess both look in the current working directory before PATH on
    Windows, which is a separate hazard (binary planting) fixed once, at
    startup, by setting NoDefaultCurrentDirectoryInExePath rather than here.
    And once a name resolves to a .cmd/.bat, CreateProcess runs it by handing
    the whole command line to cmd.exe, which re-parses every argument; a
    caller that puts untrusted or multi-line text in cmd's argv must not rely
    on resolve() to make that safe; it does not.
    """
    if sys.platform != "win32" or not cmd:
        return cmd
    found = shutil.which(cmd[0])
    return [found, *cmd[1:]] if found else cmd


@contextlib.contextmanager
def temp_text_file(text, prefix="dikte-"):
    """A temp file holding text, for an argv value a caller cannot put on the
    command line as-is.

    Some CLI options (Claude Code's --system-prompt et al.) are themselves
    often multi-line, which is exactly what a resolved .cmd shim truncates at
    the first CR/LF once it reaches cmd.exe. The path handed back has no
    newlines or quotes of its own, so it is always a safe argv element; the
    file is removed again once the caller is done with it.
    """
    handle, path = tempfile.mkstemp(prefix=prefix, suffix=".txt")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(text)
        yield path
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
