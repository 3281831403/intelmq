# SPDX-FileCopyrightText: 2015 Sebastian Wagner
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
"""
Tests the Bot class itself.
"""
import base64
import json
import os
import tempfile
import unittest

import intelmq.lib.test as test
from intelmq.lib import message
from intelmq.tests.lib import test_parser_bot


class TestDummyParserBot(test.BotTestCase, unittest.TestCase):
    """ Testing generic functionalities of Bot base class. """

    @classmethod
    def set_bot(cls):
        cls.bot_reference = test_parser_bot.DummyParserBot

    def test_pipeline_raising(self):
        self.default_input_message = None
        self.run_bot(parameters={"raise_on_connect": True},
                     error_on_pipeline=True,
                     allowed_error_count=1)
        self.assertLogMatches(levelname='ERROR', pattern='Pipeline failed')

    def test_pipeline_empty(self):
        self.default_input_message = None
        self.run_bot(allowed_error_count=1)
        self.assertLogMatches(levelname='ERROR', pattern='.*pipeline failed.*')

    def test_logging_level_other(self):
        self.input_message = test_parser_bot.EXAMPLE_SHORT
        self.run_bot(parameters={"logging_level": "DEBUG"})
        self.assertLogMatches(levelname='DEBUG', pattern='test!')

    def test_logging_catch_warnings(self):
        """
        Test if the logger catches warnings issued by the warnings module.
        """
        self.input_message = test_parser_bot.EXAMPLE_SHORT
        self.run_bot(parameters={'raise_warning': True},
                     allowed_warning_count=1)
        self.assertLogMatches(levelname='WARNING', pattern=r'.*intelmq/tests/lib/test_parser_bot\.py\:[0-9]+\: UserWarning: This is a warning test.')

    def test_bot_group(self):
        """
        Test if the bot's group is Parser.
        """
        self.input_message = []
        self.prepare_bot()
        self.assertEqual(self.bot.group, 'Parser')

    def test_encoding_error_on_input_message(self):
        """
        Test if the bot is dumping / not retrying a message which is impossible to parse.
        https://github.com/certtools/intelmq/issues/1494
        """
        self.input_message = b'foo\xc9bar'
        self.run_bot(iterations=1, allowed_error_count=1)
        self.assertLogMatches(r'.*intelmq\.lib\.exceptions\.DecodingError:.*')
        self.assertEqual(self.pipe.state['test-bot-input-internal'], [])
        self.assertEqual(self.pipe.state['test-bot-input'], [])
        self.assertEqual(self.pipe.state['test-bot-output'], [])

    def test_invalid_value_on_input_message(self):
        """
        Test if the bot is dumping / not retrying a message which is impossible to parse.
        https://github.com/certtools/intelmq/issues/1765
        """
        self.input_message = b'{"source.asn": 0, "__type": "Event"}'
        self.run_bot(iterations=1, allowed_error_count=1)
        self.assertLogMatches(r'.*intelmq\.lib\.exceptions\.InvalidValue:.*')
        self.assertEqual(self.pipe.state['test-bot-input-internal'], [])
        self.assertEqual(self.pipe.state['test-bot-input'], [])
        self.assertEqual(self.pipe.state['test-bot-output'], [])

    def _dump_and_read_entry(self, message_to_dump):
        """
        Call Bot._dump_message with the given message and return the written
        dump file's only entry.
        """
        self.prepare_bot(prepare_source_queue=False)
        self.bot.testing = False
        with tempfile.TemporaryDirectory() as tmpdir:
            self.bot.logging_path = tmpdir
            self.bot._dump_message(['Traceback (most recent call last):',
                                    'Exception: test'],
                                   message=message_to_dump)
            with open(os.path.join(tmpdir, 'test-bot.dump')) as handle:
                dump = json.load(handle)
        self.assertEqual(len(dump), 1)
        entry = next(iter(dump.values()))
        self.assertEqual(entry['bot_id'], 'test-bot')
        self.assertEqual(entry['source_queue'], self.bot.source_queue)
        return entry

    def test_dump_message_invalid_value(self):
        """
        A message dumped because of an invalid value is valid JSON and saved
        as normal message (including the type), not base64-encoded.
        """
        entry = self._dump_and_read_entry(b'{"__type": "Event", "source.asn": 0, "raw": "dGVzdA=="}')
        self.assertNotIn('message_type', entry)
        self.assertEqual(entry['message'],
                         {'__type': 'Event', 'source.asn': 0, 'raw': 'dGVzdA=='})

    def test_dump_message_decoding_error(self):
        """
        Raw data which could not be decoded is dumped base64-encoded.
        """
        entry = self._dump_and_read_entry(b'foo\xc9bar')
        self.assertEqual(entry['message_type'], 'base64')
        self.assertEqual(base64.b64decode(entry['message']), b'foo\xc9bar')

    def test_dump_message_other_exception(self):
        """
        A message dumped because of any other exception is saved serialized,
        including the type.
        """
        event = message.MessageFactory.from_dict({'__type': 'Event',
                                                  'raw': 'dGVzdA==',
                                                  'feed.name': 'test-feed'})
        entry = self._dump_and_read_entry(event)
        self.assertNotIn('message_type', entry)
        dumped = json.loads(entry['message'])
        self.assertEqual(dumped['__type'], 'Event')
        self.assertEqual(dumped['raw'], 'dGVzdA==')
        self.assertEqual(dumped['feed.name'], 'test-feed')


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
