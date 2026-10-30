import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from server import sessions

REQUEST = SimpleNamespace(transcript='我想让爸爸搬东西省些力。', topic='future', language='zh')
NOTE = SimpleNamespace(note_text='我想让爸爸搬东西省些力。', message='你想让爸爸少弯一点腰。', keywords=['爸爸', '搬东西'])


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = str(Path(self.directory.name) / 'sessions.sqlite3')
        self.env = {
            'JOURNEY_SESSION_LOG': '1', 'JOURNEY_SESSION_DB': self.db,
            'JOURNEY_SESSION_TRANSCRIPT': '1', 'JOURNEY_SESSION_RETENTION_DAYS': '7',
        }

    def test_records_are_off_by_default(self):
        with patch.dict('os.environ', {'JOURNEY_SESSION_LOG': '0', 'JOURNEY_SESSION_DB': self.db}):
            sessions.record_draft('one', REQUEST, NOTE, 1200, 'deepseek-chat')
            self.assertEqual(sessions.count(), 0)
            self.assertEqual(sessions.recent(), [])
            self.assertFalse(Path(self.db).exists())

    def test_draft_is_updated_by_the_reviewed_final(self):
        with patch.dict('os.environ', self.env):
            sessions.record_draft('one', REQUEST, NOTE, 1200, 'deepseek-chat')
            row = sessions.recent()[0]
            self.assertFalse(row['reviewed'])
            self.assertEqual(row['transcript'], REQUEST.transcript)
            self.assertEqual(row['transcript_chars'], len(REQUEST.transcript))
            self.assertEqual(row['draft_ms'], 1200)
            self.assertIsNone(row['final_ms'])
            sessions.record_final('one', NOTE, 2400)
            row = sessions.recent()[0]
            self.assertTrue(row['reviewed'])
            self.assertEqual(row['final_ms'], 2400)
            self.assertEqual(row['keywords'], ['爸爸', '搬东西'])
            self.assertEqual(sessions.count(), 1)

    def test_transcript_storage_can_be_disabled(self):
        with patch.dict('os.environ', {**self.env, 'JOURNEY_SESSION_TRANSCRIPT': '0'}):
            sessions.record_draft('one', REQUEST, NOTE, 900, 'deepseek-chat')
            row = sessions.recent()[0]
            self.assertIsNone(row['transcript'])
            self.assertEqual(row['transcript_chars'], len(REQUEST.transcript))

    def test_old_rows_are_pruned(self):
        with patch.dict('os.environ', self.env):
            sessions.record_draft('old', REQUEST, NOTE, 900, 'deepseek-chat')
            with sqlite3.connect(self.db) as connection:
                connection.execute("UPDATE sessions SET created_at = datetime('now', 'localtime', '-10 days')")
            sessions.record_draft('new', REQUEST, NOTE, 900, 'deepseek-chat')
            rows = sessions.recent()
            self.assertEqual([row['id'] for row in rows], ['new'])

    def test_clear_removes_every_row(self):
        with patch.dict('os.environ', self.env):
            sessions.record_draft('one', REQUEST, NOTE, 900, 'deepseek-chat')
            sessions.record_draft('two', REQUEST, NOTE, 900, 'deepseek-chat')
            self.assertEqual(sessions.count(), 2)
            sessions.clear()
            self.assertEqual(sessions.count(), 0)


if __name__ == '__main__':
    unittest.main()
