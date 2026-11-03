import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from reader import Reader


class FakeClient:
    def __init__(self, *requests):
        self.lines = [(json.dumps(r) + '\n').encode() for r in requests]
        self.written = []
        self.disconnectFromServer = Mock()

    def canReadLine(self):
        return bool(self.lines)

    def readLine(self):
        return self.lines.pop(0)

    def write(self, data):
        self.written.append(json.loads(data))

    def flush(self):
        pass


class WatchTests(unittest.TestCase):
    """The bar icon watches the reading state over one kept-open connection."""

    def subject(self):
        subject = SimpleNamespace(enabled=True, paused=False, status='Reading', set_enabled=Mock())
        subject.answer = lambda client: Reader.answer(subject, client)
        return subject

    def test_watch_is_light_and_keeps_connection(self):
        subject, client = self.subject(), FakeClient({'command': 'watch', 'keep': True}, {'command': 'watch', 'keep': True})
        Reader.command(subject, client)
        self.assertEqual(client.written, [dict(enabled=True, paused=False, status='Reading')] * 2)
        client.disconnectFromServer.assert_not_called()

    def test_plain_request_still_closes(self):
        subject, client = self.subject(), FakeClient({'command': 'watch'})
        Reader.command(subject, client)
        client.disconnectFromServer.assert_called_once()

    def test_unknown_command_reports_error_and_closes(self):
        subject, client = self.subject(), FakeClient({'command': 'dance', 'keep': True})
        Reader.command(subject, client)
        self.assertIn('error', client.written[0])


if __name__ == '__main__':
    unittest.main()
