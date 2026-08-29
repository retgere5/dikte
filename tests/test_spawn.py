"""The two Windows answers every external process needs.

A windowless parent on Windows flashes a console for every child unless
CREATE_NO_WINDOW is passed, and CreateProcess does not find the .cmd shims
npm installs, which shutil.which does. Both are asked per call so a test can
stand on another platform.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import spawn


class Flags(unittest.TestCase):

    def test_windows_hides_the_console(self):
        with mock.patch.object(sys, "platform", "win32"):
            self.assertEqual(spawn.flags(),
                             getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))

    def test_everywhere_else_passes_nothing(self):
        with mock.patch.object(sys, "platform", "linux"):
            self.assertEqual(spawn.flags(), 0)


class Resolve(unittest.TestCase):

    def test_windows_resolves_the_program_through_which(self):
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch("shutil.which", return_value=r"C:\bin\claude.cmd"):
            self.assertEqual(spawn.resolve(["claude", "-p"]),
                             [r"C:\bin\claude.cmd", "-p"])

    def test_a_program_which_cannot_find_is_left_alone(self):
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch("shutil.which", return_value=None):
            self.assertEqual(spawn.resolve(["claude", "-p"]), ["claude", "-p"])

    def test_other_platforms_do_not_touch_the_command(self):
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch("shutil.which") as which:
            self.assertEqual(spawn.resolve(["claude", "-p"]), ["claude", "-p"])
        which.assert_not_called()

    def test_an_empty_command_is_left_alone(self):
        with mock.patch.object(sys, "platform", "win32"):
            self.assertEqual(spawn.resolve([]), [])


@unittest.skipUnless(sys.platform == "win32",
                     "cmd.exe shims only exist to reproduce this on Windows")
class RealCmdShim(unittest.TestCase):
    """C1's proof, run for real rather than mocked: npm installs claude/codex
    as a .cmd shim, and CreateProcess runs a .cmd by handing the whole command
    line to cmd.exe, which re-parses every argument. Untrusted, multi-line
    dictation text placed in argv would (a) get silently truncated at the
    first CR/LF and (b) let a quote-and-"&" payload run a second command.
    Handing the same text over stdin instead sidesteps cmd.exe's parser
    entirely: it never looks at pipe data, only at the command line.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dikte-cmdshim-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def make_shim(self, name):
        """A .cmd in the shape npm writes one: it hands its own argv off to
        another program, the way claude.cmd hands off to node. This one hands
        off to a small Python script that writes the whole of its stdin to
        the file named by its one argument."""
        script = os.path.join(self.tmp, "sink.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(
                "import sys\n"
                "with open(sys.argv[1], 'wb') as fh:\n"
                "    fh.write(sys.stdin.buffer.read())\n"
            )
        cmd_path = os.path.join(self.tmp, name)
        with open(cmd_path, "w", encoding="ascii") as fh:
            fh.write("@echo off\r\n")
            fh.write(f'"{sys.executable}" "{script}" %*\r\n')
        return cmd_path

    def test_a_multiline_transcript_with_a_quote_and_an_ampersand_survives_stdin(self):
        marker = os.path.join(self.tmp, "pwned.txt")
        out = os.path.join(self.tmp, "out.bin")
        payload = ('first line\n'
                   'a "quoted" phrase & echo PWNED > ' + marker + '\n'
                   'third line')

        cmd = spawn.resolve([self.make_shim("claude.cmd"), out])
        result = subprocess.run(cmd, input=payload.encode("utf-8"),
                                capture_output=True, timeout=10)

        self.assertEqual(result.returncode, 0, result.stderr)
        with open(out, "rb") as fh:
            self.assertEqual(fh.read().decode("utf-8"), payload)
        self.assertFalse(
            os.path.exists(marker),
            "the ampersand in the transcript must not run a second command "
            "when it travels over stdin rather than as an argv element",
        )


if __name__ == "__main__":
    unittest.main()
