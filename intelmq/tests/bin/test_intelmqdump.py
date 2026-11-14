# SPDX-FileCopyrightText: 2016 Sebastian Wagner
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import termstyle

from intelmq.bin import intelmqdump
from intelmq.lib.test import skip_installation
from intelmq.lib.utils import base64_encode


class TestCompleter(unittest.TestCase):
    """
    A TestCase for Completer.
    """

    def test_simple(self):
        comp = intelmqdump.Completer(['foo', 'foobar', 'else'])
        self.assertEqual(comp.complete('', 0), 'else')
        self.assertEqual(comp.complete('', 2), 'foobar')
        self.assertEqual(comp.complete('f', 0), 'foo')
        self.assertEqual(comp.complete('f', 1), 'foobar')
        self.assertEqual(comp.complete('a', 0), None)

    def test_queues(self):
        comp = intelmqdump.Completer(['r ', 'a '],
                                     queues={'some-parser-queue', 'some-expert-queue'})
        self.assertEqual(comp.complete('r ', 0), 'r ')
        self.assertEqual(comp.complete('r 1 ', 0), 'r 1 some-expert-queue')
        self.assertEqual(comp.complete('r 1 ', 1), 'r 1 some-parser-queue')
        self.assertEqual(comp.complete('r 1 ', 2), None)
        self.assertEqual(comp.complete('r 2', 0), None)
        self.assertEqual(comp.complete('a  ', 0), 'a  some-expert-queue')
        self.assertEqual(comp.complete('a  ', 2), None)
        self.assertEqual(comp.complete('r  34 some-p', 0), 'r  34 some-parser-queue')
        self.assertEqual(comp.complete('a some-e', 0), 'a some-expert-queue')


class TestIntelMQDump(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.tmp_log_dir = tempfile.TemporaryDirectory()
        self.global_config = {}
        self.runtime_config = {}
        self.bot_configs = {}

        self.config_patcher = mock.patch.multiple(
            intelmqdump.utils,
            get_global_settings=mock.Mock(side_effect=self._mocked_global_config),
            get_runtime=mock.Mock(side_effect=self._mocked_runtime_config),
            get_bots_settings=mock.Mock(side_effect=self._mocked_bots_config))
        self.config_patcher.start()

        self._real_load_configuration = intelmqdump.intelmqctl.utils.load_configuration
        self.ctl_config_patcher = mock.patch.multiple(
            intelmqdump.intelmqctl.utils,
            load_configuration=mock.Mock(side_effect=self._mocked_load_configuration))
        self.ctl_config_patcher.start()

        # Coloring output makes asserts unnecessary complicated
        termstyle.disable()

    def _mocked_load_configuration(self, filepath, *args, **kwargs):
        # intelmqdump.intelmqctl.utils is the shared intelmq.lib.utils module,
        # so only intercept the runtime configuration and delegate everything
        # else (e.g. the harmonization file loaded by the message classes)
        if 'runtime' in str(filepath):
            return self._mocked_runtime_config()
        return self._real_load_configuration(filepath, *args, **kwargs)

    def _mocked_global_config(self):
        return self.global_config

    def _mocked_runtime_config(self, *args):
        return {"global": self.global_config, **self.runtime_config}

    def _mocked_bots_config(self, bot_id):
        return self.bot_configs[bot_id]

    def _prepare_empty_dump(self, filename: str):
        path = Path(f"{self.tmp_log_dir.name}/{filename}.dump")
        path.parent.mkdir(parents=True, exist_ok=True)
        Path(path).touch()

    def tearDown(self) -> None:
        self.ctl_config_patcher.stop()
        self.config_patcher.stop()
        self.tmp_log_dir.cleanup()
        termstyle.auto()
        return super().tearDown()

    def _run_main(self, argv: list) -> str:
        """Helper for running intelmqdump.main and capturing output"""
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with contextlib.suppress(SystemExit):
                intelmqdump.main(argv)
        return output.getvalue().split("\n")

    @skip_installation()
    @mock.patch.object(intelmqdump, "input", return_value='q')
    def test_list_dumps_for_all_bots_from_default_log_path(self, _):
        self._prepare_empty_dump('test-1')
        self._prepare_empty_dump('test-2')

        with mock.patch.object(intelmqdump, "DEFAULT_LOGGING_PATH", self.tmp_log_dir.name):
            output = self._run_main([])

        self.assertIn("0: test-1 empty file", output[1])
        self.assertIn("1: test-2 empty file", output[2])

    @skip_installation()
    @mock.patch.object(intelmqdump, "input", return_value='q')
    def test_list_dumps_for_all_bots_from_custom_locations(self, _):
        self.global_config = {"logging_path": self.tmp_log_dir.name}
        self._prepare_empty_dump('bot-1/test-1')
        self._prepare_empty_dump('bot-2/test-2')

        self.runtime_config = {
            "bot-1": {
                "parameters": {
                    "logging_path": f"{self.tmp_log_dir.name}/bot-1"
                }
            },
            "bot-2": {
                "parameters": {
                    "logging_path": f"{self.tmp_log_dir.name}/bot-2"
                }
            }
        }

        output = self._run_main([])

        self.assertIn("0: test-1 empty file", output[1])
        self.assertIn("1: test-2 empty file", output[2])

    @skip_installation()
    @mock.patch.object(intelmqdump, "input")
    def test_list_and_select_dump_from_global_location(self, input_mock):
        self._prepare_empty_dump('test-1')

        self.global_config = {"logging_path": self.tmp_log_dir.name}

        for selector in ['0', 'test-1']:
            with self.subTest(selector):
                input_mock.side_effect = [selector, 'q']
                output = self._run_main([])

                self.assertIn("0: test-1 empty file", output[1])
                # Enough to check that the correct file path was used
                self.assertIn("Processing test-1: empty file", output[2])

    @skip_installation()
    @mock.patch.object(intelmqdump, "input")
    def test_list_and_select_dump_from_custom_location(self, input_mock):
        self.global_config = {"logging_path": self.tmp_log_dir.name}
        self._prepare_empty_dump('/bot-1/test-1')

        self.runtime_config = {
            "bot-1": {
                "parameters": {
                    "logging_path": f"{self.tmp_log_dir.name}/bot-1"
                }
            },
        }
        for selector in ['0', 'test-1']:
            with self.subTest(selector):
                input_mock.side_effect = [selector, 'q']
                output = self._run_main([])

                self.assertIn("0: test-1 empty file", output[1])
                # Enough to check that the correct file path was used
                self.assertIn("Processing test-1: empty file", output[2])

    @skip_installation()
    @mock.patch.object(intelmqdump, "input")
    def test_selecting_dump_warns_when_filename_is_ambiguous(self, input_mock):
        """With different locations used, there could be a case of dumps with the same
            filename. Then, if user tried to select using filename, warn and exit.
            Selecting using numbers should be supported"""

        self._prepare_empty_dump('test-1')
        self._prepare_empty_dump('bot-1/test-1')

        self.global_config = {"logging_path": self.tmp_log_dir.name}
        self.runtime_config = {
            "bot-1": {
                "parameters": {
                    "logging_path": f"{self.tmp_log_dir.name}/bot-1"
                }
            },
        }

        with self.subTest("warn on ambiguous filename"):
            input_mock.side_effect = ['test-1']
            output = self._run_main([])

            self.assertIn("0: test-1 empty file", output[1])
            self.assertIn("1: test-1 empty file", output[2])
            self.assertIn("Given filename is not unique, please use number", output[3])

        with self.subTest("allow selecting using number"):
            input_mock.side_effect = ['1', 'q']
            output = self._run_main([])
            self.assertIn("Processing test-1: empty file", output[3])

    @skip_installation()
    @mock.patch.object(intelmqdump, "input", return_value='q')
    def test_get_dump_for_one_bot(self, _):
        self._prepare_empty_dump("bot/bot-1")
        self.global_config = {"logging_path": self.tmp_log_dir.name}
        self.bot_configs = {"bot-1": {"parameters": {"logging_path": f"{self.tmp_log_dir.name}/bot"}}}

        output = self._run_main(["bot-1"])
        self.assertIn("Processing bot-1: empty file", output[0])

    def _prepare_dump(self, bot_id: str, entries: dict) -> Path:
        """Write a dump file with the given entries and configure the bot."""
        path = Path(f"{self.tmp_log_dir.name}/{bot_id}.dump")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries, indent=4))
        self.global_config = {"logging_path": self.tmp_log_dir.name}
        self.runtime_config = {
            bot_id: {
                "group": "Parser",
                "module": "intelmq.bots.parsers.generic.parser_csv",
                "source_queue": f"{bot_id}-queue",
                "parameters": {"logging_path": self.tmp_log_dir.name},
            },
        }
        self.bot_configs = {bot_id: {"parameters": {"logging_path": self.tmp_log_dir.name}}}
        return path

    @staticmethod
    def _dump_entry(message, traceback=None, message_type=None):
        entry = {
            "bot_id": "test-bot",
            "source_queue": "test-bot-queue",
            "traceback": traceback if traceback is not None else [
                "Traceback (most recent call last): ...",
                "Exception: some error",
            ],
            "message": message,
        }
        if message_type:
            entry["message_type"] = message_type
        return entry

    @skip_installation()
    @mock.patch.object(intelmqdump, "input")
    def test_recover_all_entries(self, input_mock):
        """All three kinds of dumped failures (invalid value, decoding error,
        other exceptions) are recovered and converted to reports for the
        parser queue."""
        # setUp disables coloring, which makes intelmqdump treat every dump
        # info as error and restricts the available actions
        termstyle.enable()
        entries = {
            # invalid value: message saved as JSON object
            "2026-11-14T00:00:01": self._dump_entry(
                {"__type": "Event", "raw": base64_encode(b"event1"), "feed.name": "test-feed"},
                traceback=["Traceback (most recent call last): ...",
                           "intelmq.lib.exceptions.InvalidValue: invalid value '0' for key 'source.asn'"]),
            # decoding error: raw data saved base64-encoded
            "2026-11-14T00:00:02": self._dump_entry(
                base64_encode(b'foo\xc9bar'),
                traceback=["Traceback (most recent call last): ...",
                           "intelmq.lib.exceptions.DecodingError: ..."],
                message_type="base64"),
            # any other exception: message saved serialized
            "2026-11-14T00:00:03": self._dump_entry(
                json.dumps({"__type": "Event", "raw": base64_encode(b"event3"), "feed.name": "test-feed"})),
        }
        path = self._prepare_dump("test-bot", entries)

        input_mock.side_effect = ['a', 'q']
        pipe = mock.Mock()
        with mock.patch.object(intelmqdump.pipeline.PipelineFactory, "create", return_value=pipe):
            output = self._run_main(["test-bot"])

        self.assertEqual(3, pipe.send.call_count)
        sent_raws = []
        for call in pipe.send.call_args_list:
            sent = json.loads(call.args[0])
            # everything injected into a parser queue is a report
            self.assertEqual(sent["__type"], "Report")
            sent_raws.append(sent["raw"])
        self.assertEqual(sorted(sent_raws),
                         sorted([base64_encode(b"event1"),
                                 base64_encode(b'foo\xc9bar'),
                                 base64_encode(b"event3")]))
        # all entries recovered, the dump file is gone
        self.assertFalse(path.exists())
        self.assertTrue(any("Recovered dump 0." in line for line in output))
        self.assertTrue(any("Recovered dump 1." in line for line in output))
        self.assertTrue(any("Recovered dump 2." in line for line in output))

    @skip_installation()
    @mock.patch.object(intelmqdump, "input")
    def test_recover_skips_broken_entries(self, input_mock):
        """Broken entries are skipped and stay in the dump file, all other
        entries are recovered."""
        # setUp disables coloring, which makes intelmqdump treat every dump
        # info as error and restricts the available actions
        termstyle.enable()
        entries = {
            "2026-11-14T00:00:01": self._dump_entry(
                {"__type": "Event", "raw": base64_encode(b"event1"), "feed.name": "test-feed"}),
            # no message type: cannot be recovered
            "2026-11-14T00:00:02": self._dump_entry({"raw": base64_encode(b"event2")}),
            # old invalid value dumps: base64-encoded JSON without type
            "2026-11-14T00:00:03": self._dump_entry(
                base64_encode(b'{"source.asn": 0}'), message_type="base64"),
            "2026-11-14T00:00:04": self._dump_entry(
                {"__type": "Event", "raw": base64_encode(b"event4"), "feed.name": "test-feed"}),
        }
        path = self._prepare_dump("test-bot", entries)

        input_mock.side_effect = ['a', 'q']
        pipe = mock.Mock()
        with mock.patch.object(intelmqdump.pipeline.PipelineFactory, "create", return_value=pipe):
            output = self._run_main(["test-bot"])

        self.assertEqual(2, pipe.send.call_count)
        for call in pipe.send.call_args_list:
            self.assertEqual(json.loads(call.args[0])["__type"], "Report")
        # the broken entries are still in the file
        remaining = json.loads(path.read_text())
        self.assertEqual(sorted(remaining.keys()),
                         ["2026-11-14T00:00:02", "2026-11-14T00:00:03"])
        self.assertTrue(any("Recovered dump 0." in line for line in output))
        self.assertTrue(any("Recovered dump 3." in line for line in output))

    @skip_installation()
    @mock.patch.object(intelmqdump, "input")
    def test_show_and_delete_old_format_dump(self, input_mock):
        """Dumps written by older versions (traceback as string, message as
        serialized string) can be listed, shown and deleted."""
        # setUp disables coloring, which makes intelmqdump treat every dump
        # info as error and restricts the available actions
        termstyle.enable()
        entries = {
            "2020-01-01T00:00:00": self._dump_entry(
                json.dumps({"__type": "Event", "raw": base64_encode(b"event"), "feed.name": "test-feed"}),
                traceback="Traceback (most recent call last): ...\nValueError: some error"),
        }
        path = self._prepare_dump("test-bot", entries)

        input_mock.side_effect = ['s 0', 'd 0', 'q']
        output = self._run_main(["test-bot"])

        self.assertIn("1 dumps", output[0])
        self.assertTrue(any("Showing id 0" in line for line in output))
        self.assertTrue(any("ValueError: some error" in line for line in output))
        # the entry has been deleted
        self.assertEqual(json.loads(path.read_text()), {})


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
