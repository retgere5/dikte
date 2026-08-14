"""The two Windows answers every external process needs.

A windowless parent on Windows flashes a console for every child unless
CREATE_NO_WINDOW is passed, and CreateProcess does not find the .cmd shims
npm installs, which shutil.which does. Both are asked per call so a test can
stand on another platform.
"""

import subprocess
import sys
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


if __name__ == "__main__":
    unittest.main()
