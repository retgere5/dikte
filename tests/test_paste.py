"""The clipboard and the key press, which is where a dictation actually lands.

Everything here is faked: the programs the two Linux desktops shell out to, and
the frameworks macOS goes through. What the tests hold onto is what was asked
for. A paste that presses the wrong keys, or in the wrong order, types nothing
and looks like a hang.

Every system owes the same promises about the clipboard, so those are written
once and run against each of them: the ones that hold regardless of mechanism
in ClipboardContract, and the extra ones a program shelled out to also owes in
SubprocessClipboardContract. Windows, which goes through user32 instead of a
program, inherits the first list and keeps its own tests for the rest, rather
than needing its own copy of either. Each class says which system it is
standing on, which is why none of this is skipped anywhere: the Linux half is
checked on a Mac and the macOS half on Linux, and a change to the chooser
cannot quietly break the platform nobody is sitting at.
"""

import ctypes
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from typing import ClassVar
from unittest import mock

from dikte import i18n
from dikte import paste
from tests.support import DikteTest, FakeCompleted, only_these_tools


class Chooser(DikteTest):
    """Which pair of programs this session's clipboard goes through."""

    def under(self, platform="linux", **env):
        with mock.patch.object(sys, "platform", platform), \
                mock.patch.dict(os.environ, env, clear=True):
            return paste.desktop()

    def test_a_wayland_session(self):
        self.assertIs(self.under(XDG_SESSION_TYPE="wayland",
                                 WAYLAND_DISPLAY="wayland-0"), paste.WAYLAND)

    def test_an_x11_session(self):
        self.assertIs(self.under(XDG_SESSION_TYPE="x11", DISPLAY=":0"), paste.X11)

    def test_a_display_with_no_wayland_beside_it(self):
        self.assertIs(self.under(DISPLAY=":0"), paste.X11)

    def test_an_x11_display_under_wayland_is_still_wayland(self):
        """XWayland sets DISPLAY too; the session type is the one to believe."""
        self.assertIs(self.under(XDG_SESSION_TYPE="wayland",
                                 DISPLAY=":0", WAYLAND_DISPLAY="wayland-0"),
                      paste.WAYLAND)

    def test_nothing_set_at_all(self):
        self.assertIs(self.under(), paste.WAYLAND)

    def test_a_mac(self):
        self.assertIs(self.under("darwin"), paste.MACOS)

    def test_a_mac_running_an_x_server_is_still_a_mac(self):
        """XQuartz sets DISPLAY, and none of X's programs are what pastes here."""
        self.assertIs(self.under("darwin", DISPLAY=":0"), paste.MACOS)

    def test_windows(self):
        self.assertIs(self.under("win32"), paste.WINDOWS)

    def test_windows_with_a_display_variable_is_still_windows(self):
        self.assertIs(self.under("win32", DISPLAY=":0"), paste.WINDOWS)


class Standing:
    """A test that runs as if it were sitting at one particular system."""

    env: ClassVar[dict] = {}
    platform = "linux"
    here = None

    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.object(sys, "platform", self.platform))
        self.enterContext(mock.patch.dict(os.environ, self.env, clear=True))


class ClipboardContract(Standing):
    """What every system owes the text on its way to the clipboard, whichever
    mechanism it goes through: every offered shortcut has to be one press()
    can actually send. A family that shells out to a program owes the rest
    of it too, checked in SubprocessClipboardContract below; Windows, which
    calls straight into user32, inherits this half on its own and adds its
    own tests for the rest.
    """

    def test_the_paste_key_it_offers_is_one_it_can_press(self):
        """Whatever Settings lists, pressing it must not come back unknown."""
        for shortcut in self.here.shortcuts:
            with self.subTest(shortcut=shortcut):
                self.assertTrue(self.pressing(shortcut))


class SubprocessClipboardContract(ClipboardContract):
    """The half of it that shells out to a program: xclip, wl-copy, pbcopy."""

    def test_no_reader_installed(self):
        with only_these_tools():
            self.assertIsNone(paste.read_clipboard())

    def test_what_is_on_the_clipboard_comes_back_as_bytes(self):
        with only_these_tools(self.here.read_command[0]), \
                mock.patch.object(subprocess, "run",
                                  return_value=FakeCompleted(stdout=b"hello")) as run:
            self.assertEqual(paste.read_clipboard(), b"hello")
        self.assertEqual(run.call_args.args[0], self.here.read_command)

    def test_an_empty_clipboard_is_not_an_error(self):
        with only_these_tools(self.here.read_command[0]), \
                mock.patch.object(subprocess, "run",
                                  return_value=FakeCompleted(returncode=1)):
            self.assertIsNone(paste.read_clipboard())

    def test_a_reader_that_will_not_run(self):
        with only_these_tools(self.here.read_command[0]), \
                mock.patch.object(subprocess, "run", side_effect=OSError("nope")):
            self.assertIsNone(paste.read_clipboard())

    def test_no_clipboard_tool_installed_names_it(self):
        with only_these_tools(), self.assertRaises(paste.PasteError) as caught:
            paste.copy("hello")
        self.assertIn(self.here.clipboard, str(caught.exception))

    def test_the_text_goes_in_as_utf8(self):
        with only_these_tools(self.here.clipboard), \
                mock.patch.object(subprocess, "run",
                                  return_value=FakeCompleted()) as run:
            paste.copy("günaydın")
        self.assertEqual(run.call_args.args[0], self.here.copy_command)
        self.assertEqual(run.call_args.kwargs["input"], "günaydın".encode())

    def test_the_pipes_are_closed_so_the_call_can_return(self):
        """The clipboard owner forks; a pipe nobody drains hangs the caller."""
        with only_these_tools(self.here.clipboard), \
                mock.patch.object(subprocess, "run",
                                  return_value=FakeCompleted()) as run:
            paste.copy("hello")
        self.assertEqual(run.call_args.kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_a_non_zero_exit_is_reported(self):
        with only_these_tools(self.here.clipboard), \
                mock.patch.object(subprocess, "run",
                                  return_value=FakeCompleted(returncode=1)), \
                self.assertRaises(paste.PasteError):
            paste.copy("hello")

    def test_a_clipboard_tool_that_will_not_run(self):
        with only_these_tools(self.here.clipboard), \
                mock.patch.object(subprocess, "run", side_effect=OSError("nope")), \
                self.assertRaises(paste.PasteError):
            paste.copy("hello")

    def test_there_is_nothing_to_restore(self):
        with only_these_tools(self.here.clipboard), \
                mock.patch.object(subprocess, "run") as run:
            paste.copy_bytes(None)
        run.assert_not_called()

    def test_restoring_never_raises(self):
        """It runs after the paste went in; failing here must not undo that."""
        with only_these_tools(self.here.clipboard), \
                mock.patch.object(subprocess, "run", side_effect=OSError("nope")):
            paste.copy_bytes(b"whatever was there before")

    def test_the_bytes_go_back_untouched(self):
        with only_these_tools(self.here.clipboard), \
                mock.patch.object(subprocess, "run",
                                  return_value=FakeCompleted()) as run:
            paste.copy_bytes(b"\x89PNG\r\n")
        self.assertEqual(run.call_args.kwargs["input"], b"\x89PNG\r\n")


class KeyProgramContract(Standing):
    """The half of it that is another program: ydotool, xdotool."""

    def press(self, shortcut, result=None):
        with only_these_tools(self.here.keyboard), \
                mock.patch.object(paste.time, "sleep", lambda seconds: None), \
                mock.patch.object(subprocess, "run",
                                  return_value=result or FakeCompleted()) as run:
            paste.press(shortcut)
        return run.call_args.args[0]

    def pressing(self, shortcut):
        """The command a shortcut would run, for the contract above."""
        return self.press(shortcut)

    def test_no_keyboard_tool_installed(self):
        with only_these_tools():
            self.assertFalse(paste.paste_ready())
            with self.assertRaises(paste.PasteError) as caught:
                paste.press()
        self.assertIn(self.here.keyboard, str(caught.exception))

    def test_case_and_spacing_do_not_matter(self):
        self.assertEqual(self.press(" Ctrl + V "), self.press("ctrl+v"))

    def test_a_key_nobody_mapped_is_refused_before_the_tool_runs(self):
        """Whichever desktop it is, the shortcut is held to one table."""
        with only_these_tools(self.here.keyboard), \
                mock.patch.object(subprocess, "run") as run, \
                self.assertRaises(paste.PasteError) as caught:
            paste.press("ctrl+f13")
        self.assertIn("f13", str(caught.exception))
        run.assert_not_called()

    def test_a_tool_that_will_not_run(self):
        with only_these_tools(self.here.keyboard), \
                mock.patch.object(paste.time, "sleep", lambda seconds: None), \
                mock.patch.object(subprocess, "run", side_effect=OSError("nope")), \
                self.assertRaises(paste.PasteError):
            paste.press("ctrl+v")

    def test_a_failed_key_press_names_the_tool_and_what_it_said(self):
        with self.assertRaises(paste.PasteError) as caught:
            self.press("ctrl+v", FakeCompleted(returncode=1, stderr="no socket"))
        self.assertIn(self.here.keyboard, str(caught.exception))
        self.assertIn("no socket", str(caught.exception))

    def test_nothing_named_presses_the_one_this_desktop_pastes_with(self):
        self.assertEqual(self.press(""), self.press(self.here.shortcuts[0]))


class Wayland(SubprocessClipboardContract, KeyProgramContract, DikteTest):
    env: ClassVar[dict] = {"XDG_SESSION_TYPE": "wayland",
                           "WAYLAND_DISPLAY": "wayland-0"}
    here = paste.WAYLAND

    def test_ydotool_presses_down_then_lets_go_in_reverse(self):
        self.assertEqual(self.press("ctrl+v"),
                         ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"])

    def test_three_keys(self):
        self.assertEqual(self.press("ctrl+shift+v"),
                         ["ydotool", "key", "29:1", "42:1", "47:1",
                          "47:0", "42:0", "29:0"])

    def test_the_synonyms_land_on_the_same_codes(self):
        self.assertEqual(self.press("control+insert"),
                         ["ydotool", "key", "29:1", "110:1", "110:0", "29:0"])
        self.assertEqual(self.press("super+enter"), self.press("meta+return"))

    def test_a_failure_asks_after_the_daemon(self):
        """ydotool needs ydotoold, and says nothing useful when it is not up."""
        with self.assertRaises(paste.PasteError) as caught:
            self.press("ctrl+v", FakeCompleted(returncode=1, stderr="no socket"))
        self.assertIn("ydotoold", str(caught.exception))


class X11(SubprocessClipboardContract, KeyProgramContract, DikteTest):
    env: ClassVar[dict] = {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}
    here = paste.X11

    def test_xdotool_takes_the_combination_as_one_argument(self):
        self.assertEqual(self.press("ctrl+v"),
                         ["xdotool", "key", "--clearmodifiers", "ctrl+v"])

    def test_three_keys(self):
        self.assertEqual(self.press("ctrl+shift+v"),
                         ["xdotool", "key", "--clearmodifiers", "ctrl+shift+v"])

    def test_the_keys_x_spells_differently(self):
        """xdotool wants keysyms, not the names the code table is keyed by."""
        self.assertEqual(self.press("control+insert")[-1], "ctrl+Insert")
        self.assertEqual(self.press("meta+enter")[-1], "super+Return")

    def test_no_daemon_to_ask_after(self):
        with self.assertRaises(paste.PasteError) as caught:
            self.press("ctrl+v", FakeCompleted(returncode=1, stderr="bad keysym"))
        self.assertNotIn("ydotoold", str(caught.exception))


class FakeCoreGraphics:
    """Enough of the two frameworks to watch what a paste does to them.

    The events are numbers standing in for pointers, which is all the code
    treats them as: it makes them, sets flags on them, posts them, and hands
    them back.
    """

    def __init__(self, trusted=True, makes=None):
        self.trusted = trusted
        self.makes = makes   # how many it will hand out; None for as many as asked
        self.made = []       # (keycode, is_down)
        self.flags = []      # (event, flags)
        self.posted = []     # (tap, event)
        self.released = []

    # --- ApplicationServices
    def AXIsProcessTrusted(self):
        return self.trusted

    def CGEventCreateKeyboardEvent(self, source, keycode, down):
        self.made.append((keycode, down))
        if self.makes is not None and len(self.made) > self.makes:
            return None
        return 1000 + len(self.made)

    def CGEventSetFlags(self, event, flags):
        self.flags.append((event, flags))

    def CGEventPost(self, tap, event):
        self.posted.append((tap, event))

    # --- CoreFoundation
    def CFRelease(self, event):
        self.released.append(event)


class MacOS(SubprocessClipboardContract, DikteTest):
    platform = "darwin"
    here = paste.MACOS

    def setUp(self):
        super().setUp()
        self.api = FakeCoreGraphics()
        self.patch_attr(paste, "_macos_api", lambda: (self.api, self.api))
        self.patch_attr(paste.time, "sleep", lambda seconds: None)
        # It opens the settings pane once per run; each test gets its own run.
        self.patch_attr(paste, "_asked_for_permission", False)
        self.opened = self.patch_attr(paste.subprocess, "Popen", mock.Mock())

    def pressing(self, shortcut):
        paste.press(shortcut)
        return self.api.posted

    def test_the_key_goes_in_by_position_with_the_modifiers_on_it(self):
        paste.press("cmd+v")
        self.assertEqual(self.api.made, [(9, True), (9, False)])
        self.assertEqual([flags for _, flags in self.api.flags],
                         [paste.MAC_FLAGS["command"]] * 2)
        self.assertEqual([tap for tap, _ in self.api.posted],
                         [paste.HID_EVENT_TAP] * 2)

    def test_the_down_is_posted_before_the_up(self):
        paste.press("cmd+v")
        self.assertEqual([event for _, event in self.api.posted], [1001, 1002])

    def test_both_events_are_handed_back(self):
        """CoreGraphics gives out memory that nothing else will free."""
        paste.press("cmd+v")
        self.assertEqual(sorted(self.api.released), [1001, 1002])

    def test_several_modifiers_are_one_number(self):
        paste.press("cmd+shift+v")
        self.assertEqual(self.api.flags[0][1],
                         paste.MAC_FLAGS["command"] | paste.MAC_FLAGS["shift"])

    def test_the_names_a_mac_keyboard_uses(self):
        for name in ("cmd", "command", "meta", "super"):
            with self.subTest(name=name):
                self.assertEqual(paste._macos_keys(f"{name}+v"),
                                 (9, paste.MAC_FLAGS["command"]))
        self.assertEqual(paste._macos_keys("option+v"), paste._macos_keys("alt+v"))
        self.assertEqual(paste._macos_keys("control+v"), paste._macos_keys("ctrl+v"))

    def test_case_and_spacing_do_not_matter(self):
        self.assertEqual(paste._macos_keys(" Cmd + V "), paste._macos_keys("cmd+v"))

    def test_a_key_nobody_mapped_is_refused_before_anything_is_posted(self):
        with self.assertRaises(paste.PasteError) as caught:
            paste.press("cmd+f13")
        self.assertIn("f13", str(caught.exception))
        self.assertEqual(self.api.posted, [])

    def test_a_modifier_nobody_mapped(self):
        with self.assertRaises(paste.PasteError) as caught:
            paste.press("hyper+v")
        self.assertIn("hyper", str(caught.exception))

    def test_nothing_at_all(self):
        with self.assertRaises(paste.PasteError):
            paste.press("+")

    def test_nothing_is_typed_until_macos_says_so(self):
        self.api.trusted = False
        with self.assertRaises(paste.PasteError) as caught:
            paste.press("cmd+v")
        self.assertIn("Accessibility", str(caught.exception))
        self.assertEqual(self.api.posted, [])

    def test_the_permission_pane_is_opened_once_and_not_again(self):
        """It is a window in the user's face, and one paste is every dictation."""
        self.api.trusted = False
        for _ in range(3):
            with self.assertRaises(paste.PasteError):
                paste.press("cmd+v")
        self.opened.assert_called_once()
        self.assertIn("Privacy_Accessibility", self.opened.call_args.args[0][1])

    def test_a_system_that_will_not_open_the_pane_still_says_what_is_wrong(self):
        self.api.trusted = False
        self.opened.side_effect = OSError("no open(1) here")
        with self.assertRaises(paste.PasteError) as caught:
            paste.press("cmd+v")
        self.assertIn("Accessibility", str(caught.exception))

    def test_readiness_is_the_permission_rather_than_a_program(self):
        self.assertTrue(paste.paste_ready())
        self.api.trusted = False
        self.assertFalse(paste.paste_ready())

    def test_an_event_that_could_not_be_made_takes_its_pair_with_it(self):
        self.api.makes = 1            # the second one comes back null
        with self.assertRaises(paste.PasteError):
            paste.press("cmd+v")
        self.assertEqual(self.api.released, [1001])
        self.assertEqual(self.api.posted, [])

    def test_the_frameworks_not_being_there_is_not_a_crash(self):
        """Every other system imports this module too, and must survive it."""
        self.patch_attr(paste, "_macos_api",
                        mock.Mock(side_effect=paste.PasteError("no such library")))
        self.assertFalse(paste.paste_ready())


class MacClipboardSnapshot(DikteTest):
    def test_every_native_type_is_restored_and_the_files_are_removed(self):
        directory = tempfile.mkdtemp(prefix="dikte-test-clipboard-")
        manifest = '[[{"type":"public.tiff","file":"0-0.bin"}]]'
        pathlib.Path(directory, "0-0.bin").write_bytes(b"a TIFF")
        snapshot = paste._MAC_SNAPSHOT(directory, manifest)

        with mock.patch.object(subprocess, "run",
                               return_value=FakeCompleted()) as run:
            paste.copy_bytes(snapshot)

        self.assertEqual(run.call_args.kwargs["input"], manifest)
        self.assertEqual(run.call_args.kwargs["env"]["DIKTE_PASTEBOARD_DIR"],
                         directory)
        self.assertFalse(os.path.exists(directory))

    def test_a_failed_snapshot_leaves_no_temporary_directory(self):
        directory = tempfile.mkdtemp(prefix="dikte-test-clipboard-")
        with mock.patch.object(paste.tempfile, "mkdtemp", return_value=directory), \
                mock.patch.object(subprocess, "run",
                                  return_value=FakeCompleted(stdout=b"not json")):
            self.assertIsNone(paste._macos_snapshot())
        self.assertFalse(os.path.exists(directory))


class FakeWin32:
    """user32+kernel32 with a real clipboard buffer behind them.

    GlobalAlloc hands out real ctypes buffers so that the memmove and
    string_at inside paste.py operate on actual memory; what the fake keeps
    is the call order, which is the contract Windows holds us to.
    """

    CF_UNICODETEXT = 13

    def __init__(self, open_answers=(1,), clipboard_text=None,
                 unterminated_text=None):
        self.calls = []
        self.buffers = {}
        self.sizes = {}                # handle -> what GlobalSize should answer
        self.stored = None            # handle put in by SetClipboardData
        self.open_answers = list(open_answers)
        self.get_handle = 0
        if clipboard_text is not None:
            data = clipboard_text.encode("utf-16-le") + b"\x00\x00"
            buf = ctypes.create_string_buffer(data, len(data))
            self.buffers[999] = buf
            self.get_handle = 999
        if unterminated_text is not None:
            # A block another process filled exactly to GlobalSize's edge,
            # with real (non-NUL) memory sitting right after it and no
            # CF_UNICODETEXT terminator anywhere inside the block itself.
            # wstring_at with no length bound would read straight through
            # into that memory; only trusting GlobalSize tells the two
            # apart deterministically, without relying on the allocator
            # happening to hand back zeroed pages beyond the block.
            data = unterminated_text.encode("utf-16-le")
            beyond = "-not part of the clipboard-".encode("utf-16-le")
            buf = ctypes.create_string_buffer(data + beyond + b"\x00\x00",
                                              len(data) + len(beyond) + 2)
            self.buffers[999] = buf
            self.sizes[999] = len(data)
            self.get_handle = 999

    # user32 half
    def OpenClipboard(self, owner):
        self.calls.append("open")
        return self.open_answers.pop(0) if self.open_answers else 1

    def CloseClipboard(self):
        self.calls.append("close")
        return 1

    def EmptyClipboard(self):
        self.calls.append("empty")
        return 1

    def SetClipboardData(self, fmt, handle):
        self.calls.append(("set", fmt))
        self.stored = handle
        return handle

    def GetClipboardData(self, fmt):
        self.calls.append(("get", fmt))
        return self.get_handle

    # kernel32 half
    def GlobalAlloc(self, flags, size):
        handle = len(self.buffers) + 1
        self.buffers[handle] = ctypes.create_string_buffer(size)
        return handle

    def GlobalLock(self, handle):
        return ctypes.addressof(self.buffers[handle])

    def GlobalUnlock(self, handle):
        return 1

    def GlobalFree(self, handle):
        self.buffers.pop(handle, None)
        return None

    def GlobalSize(self, handle):
        return self.sizes.get(handle, len(self.buffers[handle]))

    def SendInput(self, count, array, size):
        self.calls.append("send")
        return count

    def stored_text(self):
        # The buffer is exactly as long as the payload _windows_copy sized it
        # for, so decoding the whole thing and dropping the CF_UNICODETEXT
        # terminator is the only split that survives a string ending in a
        # character whose UTF-16 low byte is itself zero.
        raw = bytes(self.buffers[self.stored].raw)
        return raw.decode("utf-16-le").rstrip("\x00")


class WindowsClipboard(ClipboardContract, DikteTest):
    """The promises every system owes, kept through calls instead of programs."""

    platform = "win32"
    here = paste.WINDOWS

    def fake(self, **kwargs):
        api = FakeWin32(**kwargs)
        self.patch_attr(paste, "_windows_api", lambda: (api, api))
        return api

    def pressing(self, shortcut):
        """The contract's own check that a shortcut is one press() can send."""
        self.fake()
        with mock.patch.object(paste.time, "sleep", lambda seconds: None):
            paste.press(shortcut)
        return True

    def test_there_is_nothing_to_restore(self):
        api = self.fake()
        paste.copy_bytes(None)
        self.assertEqual(api.calls, [])

    def test_restoring_never_raises(self):
        """It runs after the paste went in; failing here must not undo that."""
        self.fake(open_answers=[0, 0, 0, 0, 0])
        with mock.patch.object(paste.time, "sleep"):
            paste.copy_bytes(b"whatever was there before")

    def test_the_text_goes_in_as_utf16_with_turkish_intact(self):
        api = self.fake()
        paste.copy("şöğüİı çÇ")
        self.assertEqual(api.stored_text(), "şöğüİı çÇ")
        self.assertEqual(api.calls[:2], ["open", "empty"])
        self.assertIn(("set", FakeWin32.CF_UNICODETEXT), api.calls)
        self.assertEqual(api.calls[-1], "close")

    def test_what_is_on_the_clipboard_comes_back_as_bytes(self):
        self.fake(clipboard_text="hello")
        self.assertEqual(paste.read_clipboard(), b"hello")

    def test_an_unterminated_block_is_cut_at_globalsize_not_a_crash(self):
        """A block another process filled to the edge with no CF_UNICODETEXT
        NUL is where wstring_at would run off the end of it; GlobalSize is
        the only bound that can be trusted."""
        self.fake(unterminated_text="hello")
        self.assertEqual(paste.read_clipboard(), b"hello")

    def test_an_empty_clipboard_is_not_an_error(self):
        self.fake()                      # no text: GetClipboardData answers 0
        self.assertIsNone(paste.read_clipboard())

    def test_a_clipboard_someone_else_holds_is_retried_then_reported(self):
        api = self.fake(open_answers=[0, 0, 0, 0, 0])
        with mock.patch.object(paste.time, "sleep"), \
                self.assertRaises(paste.PasteError):
            paste.copy("hello")
        self.assertEqual(api.calls.count("open"), 5)

    def test_the_held_clipboard_message_is_readable_in_turkish(self):
        """The fragment named who is holding it is author-chosen text, not an
        OS exception, so it needs its own TR entry or a Turkish user reads
        half of the sentence in English."""
        i18n.set_language("tr")
        self.fake(open_answers=[0, 0, 0, 0, 0])
        with mock.patch.object(paste.time, "sleep"), \
                self.assertRaises(paste.PasteError) as caught:
            paste.copy("hello")
        message = str(caught.exception)
        self.assertNotIn("holding it", message)
        self.assertIn("tutuyor", message)

    def test_a_held_clipboard_reads_as_empty_rather_than_crashing(self):
        self.fake(open_answers=[0, 0, 0, 0, 0])
        with mock.patch.object(paste.time, "sleep"):
            self.assertIsNone(paste.read_clipboard())

    def test_copy_bytes_restores_a_snapshot(self):
        api = self.fake()
        paste.copy_bytes("önce".encode("utf-8"))
        self.assertEqual(api.stored_text(), "önce")

    def test_a_failure_to_empty_it_is_reported(self):
        api = self.fake()
        api.EmptyClipboard = lambda: 0
        with self.assertRaises(paste.PasteError):
            paste.copy("hello")

    def test_a_missing_api_names_the_failure(self):
        self.patch_attr(paste, "_windows_api",
                        mock.Mock(side_effect=paste.PasteError("no user32")))
        with self.assertRaises(paste.PasteError) as caught:
            paste.copy("hello")
        self.assertIn("no user32", str(caught.exception))
        self.assertIsNone(paste.read_clipboard())

    def test_the_missing_api_itself_names_what_would_not_load(self):
        """_windows_api is lru_cached, so a run through its own try/except
        needs the cache cleared first or an earlier test's memoized result
        would answer instead of this one's WinDLL."""
        paste._windows_api.cache_clear()
        self.addCleanup(paste._windows_api.cache_clear)
        with mock.patch.object(paste.ctypes, "WinDLL", create=True,
                               side_effect=OSError("no such DLL")), \
                self.assertRaises(paste.PasteError) as caught:
            paste._windows_api()
        self.assertIn("no such DLL", str(caught.exception))


class WindowsPress(DikteTest):
    platform = "win32"

    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.object(sys, "platform", self.platform))
        self.sent = []

        fake = mock.Mock()

        def send_input(count, array, size):
            for i in range(count):
                self.sent.append((array[i].ki.wVk,
                                  bool(array[i].ki.dwFlags & 0x0002)))
            return count

        fake.SendInput = send_input
        self.patch_attr(paste, "_windows_api", lambda: (fake, fake))

    def test_ctrl_v_is_pressed_down_and_released_in_reverse(self):
        with mock.patch.object(paste.time, "sleep"):
            paste._windows_press("ctrl+v", 0)
        self.assertEqual(self.sent, [(0x11, False), (0x56, False),
                                     (0x56, True), (0x11, True)])

    def test_shift_insert_uses_the_insert_key(self):
        with mock.patch.object(paste.time, "sleep"):
            paste._windows_press("shift+insert", 0)
        self.assertEqual(self.sent, [(0x10, False), (0x2D, False),
                                     (0x2D, True), (0x10, True)])

    def test_an_unknown_key_is_refused_before_anything_is_typed(self):
        with self.assertRaises(paste.PasteError):
            paste._windows_press("ctrl+ş", 0)
        self.assertEqual(self.sent, [])

    def test_a_refused_send_is_reported(self):
        api = paste._windows_api()[0]
        api.SendInput = lambda count, array, size: 0
        with mock.patch.object(paste.time, "sleep"), \
                self.assertRaises(paste.PasteError):
            paste._windows_press("ctrl+v", 0)

    def test_a_refused_send_is_readable_in_turkish_too(self):
        """How many of how many events got through is author-chosen text
        built with an f-string, not an OS exception; it needs its own TR
        entry the same as the other fragments here do."""
        i18n.set_language("tr")
        api = paste._windows_api()[0]
        api.SendInput = lambda count, array, size: 0
        with mock.patch.object(paste.time, "sleep"), \
                self.assertRaises(paste.PasteError) as caught:
            paste._windows_press("ctrl+v", 0)
        message = str(caught.exception)
        self.assertNotIn("events", message)
        self.assertIn("gönderildi", message)

    def test_the_delay_lets_focus_come_back_first(self):
        with mock.patch.object(paste.time, "sleep") as sleep:
            paste._windows_press("ctrl+v", 0.12)
        sleep.assert_called_once_with(0.12)


if __name__ == "__main__":
    unittest.main()
