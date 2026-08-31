"""Handing a dictation to an agent.

Three providers behind one setting, so most of this is about the command line
each of them is given and about the conversation carried between dictations. The
CLIs are faked at subprocess.Popen: what the tests read is the argument list and
what the stream of JSON events is turned into.
"""

import io
import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

from dikte import assistant
from dikte import spawn
from tests.support import DikteTest, fake_urlopen, only_these_tools


class FakeCli:
    """A CLI that prints the given events and exits."""

    def __init__(self, events=(), code=0, stderr="", noise=()):
        lines = list(noise) + [json.dumps(event) for event in events]
        self.stdout = io.StringIO("\n".join(lines) + "\n")
        self.stderr = io.StringIO(stderr)
        self.stdin = mock.Mock()
        self.returncode = code
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.killed = True

    def kill(self):
        self.killed = True


class Stream(DikteTest):
    """_stream is what actually starts the CLI; every provider runs through it."""

    def popen_mock(self, popen):
        # A real stdout/wait rather than a bare try/except around the call:
        # _stream reads proc.stdout to the end and _finish both waits on the
        # process and closes proc.stdout/proc.stderr, so both need to be
        # actual file-like objects rather than a bare iterator, for the run
        # to complete the way the assertions below expect.
        popen.return_value.stdout = io.StringIO("")
        popen.return_value.stderr.read.return_value = ""
        popen.return_value.wait.return_value = 0
        popen.return_value.poll.return_value = 0

    def test_it_runs_without_a_console_window_on_windows(self):
        # spawn.resolve must be stubbed: with sys.platform faked to win32 on a
        # real Linux runner, shutil.which reaches _winapi (absent there) and
        # raises. In production the fake is never on, so which stays on its own
        # platform's path.
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.object(assistant.spawn, "resolve", lambda cmd: cmd), \
                mock.patch.object(assistant.subprocess, "Popen") as popen:
            self.popen_mock(popen)
            assistant._stream(["claude", "-p"], self.config(),
                              lambda event: None, lambda: False)
            self.assertEqual(popen.call_args.kwargs.get("creationflags"),
                             spawn.flags())
            self.assertNotEqual(popen.call_args.kwargs.get("creationflags"), 0)

    def test_no_console_flag_off_windows(self):
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.object(assistant.subprocess, "Popen") as popen:
            self.popen_mock(popen)
            assistant._stream(["claude", "-p"], self.config(),
                              lambda event: None, lambda: False)
        self.assertEqual(popen.call_args.kwargs.get("creationflags"), 0)

    def test_input_text_is_written_to_stdin_and_closed(self):
        with mock.patch.object(assistant.subprocess, "Popen") as popen:
            self.popen_mock(popen)
            assistant._stream(["claude", "-p"], self.config(),
                              lambda event: None, lambda: False,
                              input_text="hello")
        self.assertEqual(popen.call_args.kwargs.get("stdin"), subprocess.PIPE)
        popen.return_value.stdin.write.assert_called_once_with("hello")
        popen.return_value.stdin.close.assert_called_once_with()

    def test_with_no_input_text_stdin_is_closed_from_the_start(self):
        with mock.patch.object(assistant.subprocess, "Popen") as popen:
            self.popen_mock(popen)
            assistant._stream(["claude", "-p"], self.config(),
                              lambda event: None, lambda: False)
        self.assertEqual(popen.call_args.kwargs.get("stdin"), subprocess.DEVNULL)
        popen.return_value.stdin.write.assert_not_called()

    def test_a_child_that_closed_its_own_stdin_first_is_not_a_failure_here(self):
        with mock.patch.object(assistant.subprocess, "Popen") as popen:
            self.popen_mock(popen)
            popen.return_value.stdin.write.side_effect = OSError("broken pipe")
            # Must not raise: whatever is wrong with the child shows up as a
            # normal exit-code/stderr failure once the stream is read.
            assistant._stream(["claude", "-p"], self.config(),
                              lambda event: None, lambda: False,
                              input_text="hello")


class Provider(DikteTest):
    def test_the_default(self):
        self.assertEqual(assistant.provider(self.config()), "claude")

    def test_a_provider_this_version_does_not_have(self):
        self.assertEqual(
            assistant.provider(self.config(assistant_provider="ollama")), "claude")

    def test_each_one_is_recognised(self):
        for name in assistant.PROVIDERS:
            with self.subTest(name=name):
                self.assertEqual(
                    assistant.provider(self.config(assistant_provider=name)), name)

    def test_what_each_one_runs(self):
        self.assertEqual(assistant.executable("claude"), "claude")
        self.assertEqual(assistant.executable("codex"), "codex")
        self.assertEqual(assistant.executable("openrouter"), "")

    def test_what_each_one_is_called(self):
        self.assertEqual(assistant.display_name(self.config()), "Claude")
        self.assertEqual(
            assistant.display_name(self.config(assistant_provider="codex")), "Codex")
        self.assertEqual(
            assistant.display_name(self.config(assistant_provider="openrouter")),
            "OpenRouter")


class Effort(unittest.TestCase):
    """One scale, offered once; a rung a provider lacks lands on its nearest."""

    def test_the_scales_cover_the_same_settings(self):
        self.assertEqual(set(assistant.CLAUDE_EFFORT), set(assistant.CODEX_EFFORT))

    def test_codex_has_no_rung_above_high(self):
        self.assertEqual(assistant.CODEX_EFFORT["xhigh"], "high")
        self.assertEqual(assistant.CODEX_EFFORT["max"], "high")

    def test_neither_one_asks_for_a_rung_below_low(self):
        # Claude has none; Codex has one, but calls it "minimal" on the older
        # models and "none" on the newer ones, and refuses the wrong word.
        for scale in (assistant.CLAUDE_EFFORT, assistant.CODEX_EFFORT):
            self.assertEqual(scale["none"], "low")
            self.assertEqual(scale["minimal"], "low")

    def test_an_empty_setting_asks_for_nothing(self):
        self.assertEqual(assistant.CLAUDE_EFFORT.get("", ""), "")
        self.assertEqual(assistant.CODEX_EFFORT.get("", ""), "")


class Session(DikteTest):
    def test_nothing_stored_yet(self):
        self.assertEqual(assistant.read_session("claude", 1800), "")
        self.assertEqual(assistant.read_messages("openrouter", 1800), [])
        self.assertEqual(assistant.stored_provider(), "")
        self.assertIsNone(assistant.session_age())

    def test_an_id_is_written_and_read_back(self):
        assistant.write_session("claude", "abc-123")
        self.assertEqual(assistant.read_session("claude", 1800), "abc-123")
        self.assertEqual(assistant.stored_provider(), "claude")

    def test_nobody_picks_up_another_provider_s_thread(self):
        assistant.write_session("claude", "abc-123")
        self.assertEqual(assistant.read_session("codex", 1800), "")

    def test_a_conversation_that_has_sat_unused_is_dropped(self):
        assistant.write_session("claude", "abc-123")
        with mock.patch.object(time, "time", return_value=time.time() + 3600):
            self.assertEqual(assistant.read_session("claude", 1800), "")

    def test_a_session_that_never_expires(self):
        assistant.write_session("claude", "abc-123")
        with mock.patch.object(time, "time", return_value=time.time() + 10 ** 6):
            self.assertEqual(assistant.read_session("claude", 0), "abc-123")

    def test_the_messages_of_the_provider_that_keeps_none(self):
        messages = [{"role": "user", "content": "hi"}]
        assistant.write_session("openrouter", messages=messages)
        self.assertEqual(assistant.read_messages("openrouter", 1800), messages)

    def test_the_history_window_ends_somewhere(self):
        messages = [{"role": "user", "content": str(index)} for index in range(50)]
        assistant.write_session("openrouter", messages=messages)
        stored = assistant.read_messages("openrouter", 1800)
        self.assertEqual(len(stored), assistant.MAX_HISTORY)
        self.assertEqual(stored[-1]["content"], "49")

    def test_the_age_of_the_conversation(self):
        assistant.write_session("claude", "abc-123")
        self.assertLess(assistant.session_age(), 5)

    def test_a_row_with_neither_an_id_nor_messages_has_no_age(self):
        assistant.write_session("claude", "")
        self.assertIsNone(assistant.session_age())

    def test_clearing(self):
        assistant.write_session("claude", "abc-123")
        assistant.clear_session()
        self.assertEqual(assistant.read_session("claude", 1800), "")

    def test_clearing_one_that_is_not_there(self):
        assistant.clear_session()   # must not raise

    def test_a_session_file_that_is_not_json(self):
        assistant.SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        assistant.SESSION_FILE.write_text("{oh dear", encoding="utf-8")
        self.assertEqual(assistant.read_session("claude", 1800), "")
        self.assertEqual(assistant.stored_provider(), "")
        self.assertIsNone(assistant.session_age())


class WorkingDir(DikteTest):
    def test_the_home_directory_by_default(self):
        self.assertEqual(assistant.working_dir(self.config()),
                         os.path.expanduser("~"))

    def test_a_directory_of_your_own(self):
        conf = self.config(assistant_dir=self.root)
        self.assertEqual(assistant.working_dir(conf), self.root)

    def test_a_tilde_is_expanded(self):
        conf = self.config(assistant_dir="~")
        self.assertEqual(assistant.working_dir(conf), os.path.expanduser("~"))

    def test_a_directory_that_is_not_there_falls_back(self):
        conf = self.config(assistant_dir="/no/such/place")
        self.assertEqual(assistant.working_dir(conf), os.path.expanduser("~"))


class Labels(DikteTest):
    def test_a_tool_the_table_knows(self):
        self.assertEqual(assistant._claude_label({"name": "Bash"}),
                         "Running a command…")

    def test_a_tool_arriving_from_an_mcp_server_is_named_by_its_server(self):
        self.assertIn("gmail", assistant._claude_label({"name": "mcp__gmail__send"}))

    def test_a_skill_is_named_by_the_skill(self):
        label = assistant._claude_label(
            {"name": "Skill", "input": {"skill": "calendar"}})
        self.assertIn("calendar", label)

    def test_a_tool_nobody_wrote_a_line_for(self):
        self.assertIn("SomeNewTool",
                      assistant._claude_label({"name": "SomeNewTool"}))

    def test_a_tool_with_no_name_at_all(self):
        self.assertTrue(assistant._claude_label({}))

    def test_the_codex_table(self):
        self.assertEqual(assistant._codex_label({"type": "command_execution"}),
                         "Running a command…")

    def test_a_codex_mcp_call(self):
        self.assertIn("gmail", assistant._codex_label(
            {"type": "mcp_tool_call", "server": "gmail"}))

    def test_a_codex_item_nobody_listed(self):
        self.assertIn("something_new",
                      assistant._codex_label({"type": "something_new"}))


class Denials(DikteTest):
    def test_nothing_was_denied(self):
        self.assertEqual(assistant._denial_warning({}), "")
        self.assertEqual(assistant._denial_warning({"permission_denials": []}), "")

    def test_a_denied_tool_is_named(self):
        warning = assistant._denial_warning(
            {"permission_denials": [{"tool_name": "Bash"}]})
        self.assertIn("Bash", warning)

    def test_the_same_tool_denied_twice_is_named_once(self):
        warning = assistant._denial_warning({"permission_denials": [
            {"tool_name": "Bash"}, {"tool_name": "Bash"}, {"tool_name": "Write"}]})
        self.assertEqual(warning.count("Bash"), 1)
        self.assertIn("Write", warning)


class SessionMissing(unittest.TestCase):
    def test_a_session_that_is_gone(self):
        for text in ("Error: session abc not found",
                     "No conversation with that id",
                     "unknown thread: abc"):
            with self.subTest(text=text):
                self.assertTrue(assistant._session_missing(text))

    def test_an_unrelated_failure(self):
        for text in ("", "network unreachable", "session limit exceeded"):
            with self.subTest(text=text):
                self.assertFalse(assistant._session_missing(text))

    def test_the_last_line_is_the_one_worth_showing(self):
        self.assertEqual(assistant.last_line("warning\n\nreal error\n"),
                         "real error")
        self.assertEqual(assistant.last_line(""), "")
        self.assertEqual(assistant.last_line(None), "")


class Conclude(DikteTest):
    def found(self, **changes):
        row = {"answer": "", "warning": "", "session": "", "failure": ""}
        row.update(changes)
        return row

    def test_an_answer_and_its_session(self):
        answer, warning = assistant._conclude(
            self.found(answer="done", session="abc"), 0, "", "", "Claude")
        self.assertEqual(answer, "done")
        self.assertEqual(warning, "")
        self.assertEqual(assistant.read_session("claude", 1800), "abc")

    def test_codex_stores_under_its_own_name(self):
        assistant._conclude(self.found(answer="done", session="t-1"), 0, "",
                            "", "Codex")
        self.assertEqual(assistant.read_session("codex", 1800), "t-1")

    def test_a_non_zero_exit_with_nothing_to_show_for_it(self):
        with self.assertRaises(assistant.AssistantError) as caught:
            assistant._conclude(self.found(), 1, "it all went wrong\n", "", "Claude")
        self.assertIn("it all went wrong", str(caught.exception))

    def test_a_plain_stdout_line_shows_when_stderr_is_silent(self):
        # claude prints an expired login to stdout with an empty stderr; the
        # last such line is the reason to show, not a bare exit code.
        with self.assertRaises(assistant.AssistantError) as caught:
            assistant._conclude(self.found(), 1, "", "", "Claude",
                                tail="Failed to authenticate")
        self.assertIn("Failed to authenticate", str(caught.exception))

    def test_a_session_that_is_gone_is_raised_apart(self):
        with self.assertRaises(assistant._SessionGone):
            assistant._conclude(self.found(), 1, "session abc not found",
                                "abc", "Claude")

    def test_a_session_that_is_gone_only_matters_when_one_was_resumed(self):
        with self.assertRaises(assistant.AssistantError):
            assistant._conclude(self.found(), 1, "session abc not found",
                                "", "Claude")

    def test_an_answer_survives_a_non_zero_exit(self):
        answer, _ = assistant._conclude(self.found(answer="done"), 1, "noise",
                                        "", "Claude")
        self.assertEqual(answer, "done")

    def test_a_reported_failure_with_no_answer(self):
        with self.assertRaises(assistant.AssistantError) as caught:
            assistant._conclude(self.found(failure="the model refused"), 0, "",
                                "", "Claude")
        self.assertIn("refused", str(caught.exception))

    def test_a_run_that_said_nothing_at_all(self):
        with self.assertRaises(assistant.AssistantError) as caught:
            assistant._conclude(self.found(), 0, "", "", "Codex")
        self.assertIn("Codex", str(caught.exception))


class AskClaude(DikteTest):
    def run_ask(self, conf=None, events=None, code=0, stderr="", noise=(),
                session=""):
        conf = conf or self.config()
        proc = FakeCli(events or [
            {"type": "system", "subtype": "init", "session_id": "abc"},
            {"type": "result", "session_id": "abc", "result": "  done  "},
        ], code=code, stderr=stderr, noise=noise)
        stages = []
        # Command construction is under test here, not PATH resolution, which
        # tests/test_spawn.py covers on its own; resolving for real would rename
        # cmd[0] on this machine and break the assertions below.
        with only_these_tools("claude", "codex"), \
                mock.patch.object(assistant.spawn, "resolve", side_effect=lambda cmd: cmd), \
                mock.patch.object(subprocess, "Popen", return_value=proc) as popen:
            result = assistant._ask_claude(
                "book it", conf, session, stages.append, None)
        return result, popen.call_args.args[0], stages, proc

    def test_the_answer_comes_back_stripped(self):
        (answer, warning), _, _, _ = self.run_ask()
        self.assertEqual(answer, "done")
        self.assertEqual(warning, "")

    def test_the_prompt_goes_in_over_stdin_not_argv(self):
        _, cmd, _, proc = self.run_ask()
        self.assertEqual(cmd[:2], ["claude", "-p"])
        self.assertNotIn("book it", cmd)
        proc.stdin.write.assert_called_once_with("book it")
        proc.stdin.close.assert_called_once_with()

    def test_a_multiline_untrusted_prompt_never_rides_in_argv(self):
        # The command being spoken is untrusted, and a resolved .cmd shim runs
        # by handing the whole command line to cmd.exe: putting it in argv is
        # what truncates it at the first CR/LF and lets a quote plus "&" run a
        # second command.
        conf = self.config()
        proc = FakeCli([{"type": "result", "result": "done"}])
        with only_these_tools("claude"), \
                mock.patch.object(assistant.spawn, "resolve", side_effect=lambda cmd: cmd), \
                mock.patch.object(subprocess, "Popen", return_value=proc) as popen:
            assistant._ask_claude('line one\nline two "q" & echo PWNED', conf,
                                  "", None, None)
        cmd = popen.call_args.args[0]
        self.assertFalse(any("PWNED" in part or "\n" in part for part in cmd))
        proc.stdin.write.assert_called_once_with(
            'line one\nline two "q" & echo PWNED')

    def test_the_stream_is_asked_for_so_progress_can_be_shown(self):
        _, cmd, _, _ = self.run_ask()
        self.assertIn("--output-format", cmd)
        self.assertIn("stream-json", cmd)
        self.assertIn("--verbose", cmd)

    def test_the_model_and_the_permission_mode_are_passed_on(self):
        conf = self.config(assistant_model="opus",
                           assistant_permission_mode="plan")
        _, cmd, _, _ = self.run_ask(conf)
        self.assertEqual(cmd[cmd.index("--model") + 1], "opus")
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "plan")

    def test_the_instruction_rides_along_as_a_system_prompt_file(self):
        # Not a plain --append-system-prompt <value>: config.ASSISTANT_PROMPT_EN
        # is itself multi-line, and a resolved .cmd shim truncates the whole
        # command line at the first CR/LF, so a multi-line value there would
        # silently drop --model and --permission-mode along with itself. The
        # file is read here while the Popen call is still live, since
        # _ask_claude deletes it again once the call returns.
        conf = self.config()
        proc = FakeCli([{"type": "result", "result": "done"}])
        seen = {}

        def fake_popen(cmd, **kwargs):
            with open(cmd[cmd.index("--append-system-prompt-file") + 1],
                     encoding="utf-8") as fh:
                seen["prompt_file_content"] = fh.read()
            seen["cmd"] = cmd
            return proc

        with only_these_tools("claude"), \
                mock.patch.object(assistant.spawn, "resolve", side_effect=lambda cmd: cmd), \
                mock.patch.object(subprocess, "Popen", side_effect=fake_popen):
            assistant._ask_claude("book it", conf, "", None, None)
        self.assertEqual(seen["prompt_file_content"], conf.assistant_prompt())
        self.assertFalse(os.path.exists(
            seen["cmd"][seen["cmd"].index("--append-system-prompt-file") + 1]))

    def test_no_effort_asked_for_means_no_flag(self):
        _, cmd, _, _ = self.run_ask()
        self.assertNotIn("--effort", cmd)

    def test_an_effort_is_translated_to_the_provider_s_vocabulary(self):
        _, cmd, _, _ = self.run_ask(self.config(assistant_reasoning="minimal"))
        self.assertEqual(cmd[cmd.index("--effort") + 1], "low")

    def test_a_conversation_is_resumed(self):
        _, cmd, _, _ = self.run_ask(session="abc-123")
        self.assertEqual(cmd[cmd.index("--resume") + 1], "abc-123")

    def test_a_fresh_conversation_resumes_nothing(self):
        _, cmd, _, _ = self.run_ask()
        self.assertNotIn("--resume", cmd)

    def test_every_tool_it_picks_up_is_named_in_the_corner(self):
        _, _, stages, _ = self.run_ask(events=[
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "WebSearch"}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash"}]}},
            {"type": "result", "result": "done"},
        ])
        self.assertEqual(stages, ["Searching the web…", "Running a command…"])

    def test_a_denied_tool_comes_back_as_a_warning_beside_the_answer(self):
        (answer, warning), _, _, _ = self.run_ask(events=[
            {"type": "result", "result": "I could not do that.",
             "permission_denials": [{"tool_name": "Bash"}]},
        ])
        self.assertEqual(answer, "I could not do that.")
        self.assertIn("Bash", warning)

    def test_a_run_that_ended_in_an_error(self):
        with self.assertRaises(assistant.AssistantError):
            self.run_ask(events=[{"type": "result", "is_error": True,
                                  "result": "rate limited"}])

    def test_the_odd_unstructured_line_among_the_json(self):
        (answer, _), _, _, _ = self.run_ask(noise=["Loading…", "not json at all"])
        self.assertEqual(answer, "done")

    def test_a_json_line_that_is_not_an_object(self):
        proc = FakeCli(code=0)
        proc.stdout = io.StringIO('{"type": "result", "result": "done"}\n[1,2]\n')
        with only_these_tools("claude"), \
                mock.patch.object(assistant.spawn, "resolve", side_effect=lambda cmd: cmd), \
                mock.patch.object(subprocess, "Popen", return_value=proc):
            answer, _ = assistant._ask_claude("hi", self.config(), "", None, None)
        self.assertEqual(answer, "done")


class AskCodex(DikteTest):
    def run_ask(self, conf=None, events=None, session=""):
        conf = conf or self.config(assistant_provider="codex")
        proc = FakeCli(events or [
            {"type": "thread.started", "thread_id": "t-1"},
            {"type": "item.completed",
             "item": {"type": "agent_message", "text": "done"}},
        ])
        stages = []
        # Same as AskClaude.run_ask: keep PATH resolution out of a test that is
        # about the argument list, not about where the binary lives.
        with only_these_tools("codex"), \
                mock.patch.object(assistant.spawn, "resolve", side_effect=lambda cmd: cmd), \
                mock.patch.object(subprocess, "Popen", return_value=proc) as popen:
            result = assistant._ask_codex("book it", conf, session,
                                          stages.append, None)
        return result, popen.call_args.args[0], stages, proc

    def test_the_answer(self):
        (answer, _), _, _, _ = self.run_ask()
        self.assertEqual(answer, "done")

    def test_the_instruction_is_kept_apart_from_the_command_over_stdin(self):
        """Codex takes no system prompt, so the two must not read as one, and
        the combined body is untrusted enough that it must not ride in argv."""
        conf = self.config(assistant_provider="codex")
        _, cmd, _, proc = self.run_ask(conf)
        self.assertFalse(any("book it" in part for part in cmd))
        body = proc.stdin.write.call_args.args[0]
        self.assertTrue(body.startswith(conf.assistant_prompt()))
        self.assertIn("\n\n---\n\n", body)
        self.assertTrue(body.endswith("book it"))
        proc.stdin.close.assert_called_once_with()

    def test_a_multiline_untrusted_body_never_rides_in_argv(self):
        conf = self.config(assistant_provider="codex")
        proc = FakeCli([{"type": "item.completed",
                        "item": {"type": "agent_message", "text": "done"}}])
        with only_these_tools("codex"), \
                mock.patch.object(assistant.spawn, "resolve", side_effect=lambda cmd: cmd), \
                mock.patch.object(subprocess, "Popen", return_value=proc) as popen:
            assistant._ask_codex('line one\nline two "q" & echo PWNED', conf,
                                 "", None, None)
        cmd = popen.call_args.args[0]
        self.assertFalse(any("PWNED" in part or "\n" in part for part in cmd))

    def test_there_is_nobody_here_to_approve_anything(self):
        _, cmd, _, _ = self.run_ask()
        self.assertIn('approval_policy="never"', cmd)
        self.assertIn("--skip-git-repo-check", cmd)
        self.assertIn("--json", cmd)

    def test_the_sandbox_setting_is_passed_on(self):
        _, cmd, _, _ = self.run_ask(
            self.config(assistant_provider="codex",
                        assistant_codex_sandbox="read-only"))
        self.assertIn('sandbox_mode="read-only"', cmd)

    def test_no_model_named_means_whatever_codex_is_set_to(self):
        _, cmd, _, _ = self.run_ask()
        self.assertNotIn("-m", cmd)

    def test_a_model_of_your_own(self):
        _, cmd, _, _ = self.run_ask(
            self.config(assistant_provider="codex", assistant_codex_model=" gpt-5 "))
        self.assertEqual(cmd[cmd.index("-m") + 1], "gpt-5")

    def test_the_effort_lands_on_the_nearest_rung_codex_has(self):
        _, cmd, _, _ = self.run_ask(
            self.config(assistant_provider="codex", assistant_reasoning="max"))
        self.assertIn('model_reasoning_effort="high"', cmd)

    def test_a_conversation_is_resumed(self):
        _, cmd, _, _ = self.run_ask(session="t-1")
        self.assertEqual(cmd[:4], ["codex", "exec", "resume", "t-1"])

    def test_a_fresh_conversation(self):
        _, cmd, _, _ = self.run_ask()
        self.assertEqual(cmd[:2], ["codex", "exec"])

    def test_the_closing_message_is_the_answer(self):
        (answer, _), _, _, _ = self.run_ask(events=[
            {"type": "item.completed",
             "item": {"type": "agent_message", "text": "let me look"}},
            {"type": "item.completed",
             "item": {"type": "agent_message", "text": "it is on Thursday"}},
        ])
        self.assertEqual(answer, "it is on Thursday")

    def test_the_work_is_narrated_as_it_goes(self):
        _, _, stages, _ = self.run_ask(events=[
            {"type": "item.started", "item": {"type": "command_execution"}},
            {"type": "item.completed",
             "item": {"type": "agent_message", "text": "done"}},
        ])
        self.assertEqual(stages, ["Running a command…"])

    def test_a_turn_that_failed(self):
        with self.assertRaises(assistant.AssistantError) as caught:
            self.run_ask(events=[{"type": "turn.failed",
                                  "error": {"message": "quota exhausted"}}])
        self.assertIn("quota", str(caught.exception))


class ResolvedOnWindows(DikteTest):
    """I14: spawn.resolve() actually runs at _stream's Popen call, and the
    prompt reaches the CLI over stdin rather than as an argv element a
    resolved .cmd shim would hand to cmd.exe. Unlike the classes above, this
    one does not stub spawn.resolve away."""

    def test_claude_is_launched_at_its_resolved_path_with_the_prompt_on_stdin(self):
        proc = FakeCli([{"type": "result", "result": "done"}])
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch("shutil.which", return_value=r"C:\bin\claude.cmd"), \
                mock.patch.object(subprocess, "Popen", return_value=proc) as popen:
            assistant._ask_claude("book it\nsecond line", self.config(), "",
                                  None, None)
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[0], r"C:\bin\claude.cmd")
        self.assertFalse(any("\n" in part for part in cmd))
        proc.stdin.write.assert_called_once_with("book it\nsecond line")

    def test_codex_is_launched_at_its_resolved_path_with_the_body_on_stdin(self):
        proc = FakeCli([{"type": "item.completed",
                        "item": {"type": "agent_message", "text": "done"}}])
        conf = self.config(assistant_provider="codex")
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch("shutil.which", return_value=r"C:\bin\codex.cmd"), \
                mock.patch.object(subprocess, "Popen", return_value=proc) as popen:
            assistant._ask_codex("book it\nsecond line", conf, "", None, None)
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[0], r"C:\bin\codex.cmd")
        self.assertFalse(any("\n" in part for part in cmd))
        self.assertTrue(proc.stdin.write.call_args.args[0].endswith(
            "book it\nsecond line"))


class AskOpenRouter(DikteTest):
    def test_a_question_and_an_answer(self):
        conf = self.config(assistant_provider="openrouter",
                           openrouter_api_key="sk-or-test")
        with fake_urlopen({"choices": [{"message": {"content": "on Thursday"}}]}):
            answer, warning = assistant.ask("when is it", conf)
        self.assertEqual(answer, "on Thursday")
        self.assertEqual(warning, "")

    def test_the_conversation_is_ours_to_keep(self):
        conf = self.config(assistant_provider="openrouter",
                           openrouter_api_key="sk-or-test")
        with fake_urlopen({"choices": [{"message": {"content": "on Thursday"}}]}):
            assistant.ask("when is it", conf)
        stored = assistant.read_messages("openrouter", 1800)
        self.assertEqual([row["content"] for row in stored],
                         ["when is it", "on Thursday"])

    def test_the_next_command_knows_what_that_means(self):
        conf = self.config(assistant_provider="openrouter",
                           openrouter_api_key="sk-or-test")
        assistant.write_session("openrouter", messages=[
            {"role": "user", "content": "when is it"},
            {"role": "assistant", "content": "on Thursday"}])
        with fake_urlopen({"choices": [{"message": {"content": "moved"}}]}) as calls:
            assistant.ask("move it to Friday", conf)
        sent = json.loads(calls[0].data.decode("utf-8"))["messages"]
        self.assertEqual(len(sent), 4)   # system, the two stored, the new one

    def test_an_api_failure_reads_as_an_assistant_failure(self):
        conf = self.config(assistant_provider="openrouter")
        with self.assertRaises(assistant.AssistantError):
            assistant.ask("when is it", conf)


class Ask(DikteTest):
    def test_a_cli_that_is_not_installed_says_where_to_change_it(self):
        with only_these_tools(), \
                self.assertRaises(assistant.AssistantError) as caught:
            assistant.ask("hi", self.config())
        self.assertIn("claude", str(caught.exception))
        self.assertIn("Settings", str(caught.exception))

    def test_a_session_that_is_gone_is_started_over_without_a_word(self):
        conf = self.config()
        assistant.write_session("claude", "stale-id")
        attempts = []

        def run(prompt, conf, session, on_stage, should_stop):
            attempts.append(session)
            if session:
                raise assistant._SessionGone()
            return "done", ""

        with only_these_tools("claude"), \
                mock.patch.object(assistant, "_ask_claude", side_effect=run):
            answer, _ = assistant.ask("hi", conf)
        self.assertEqual(answer, "done")
        self.assertEqual(attempts, ["stale-id", ""])
        self.assertEqual(assistant.stored_provider(), "")


if __name__ == "__main__":
    unittest.main()
