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


class SessionFeatureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        base = Path(self.directory.name)
        self.env = {
            'JOURNEY_SESSION_LOG': '1', 'JOURNEY_SESSION_DB': str(base / 'sessions.sqlite3'),
            'JOURNEY_SESSION_AUDIO_DIR': str(base / 'audio'), 'JOURNEY_SESSION_AUDIO': '1',
            'JOURNEY_SESSION_TRANSCRIPT': '1', 'JOURNEY_SESSION_RETENTION_DAYS': '7',
        }

    def test_visitor_numbers_are_sequential_and_stable_across_retries(self):
        with patch.dict('os.environ', self.env):
            sessions.record_draft('a' * 32, REQUEST, NOTE, 100, 'model')
            sessions.record_draft('b' * 32, REQUEST, NOTE, 100, 'model')
            sessions.record_draft('a' * 32, REQUEST, NOTE, 900, 'model')
            rows = {row['id']: row for row in sessions.recent()}
            self.assertEqual(rows['a' * 32]['visitor_no'], 1)
            self.assertEqual(rows['b' * 32]['visitor_no'], 2)
            self.assertEqual(rows['a' * 32]['draft_ms'], 900)

    def test_summary_counts_generated_printed_failed_and_today(self):
        with patch.dict('os.environ', self.env):
            sessions.record_draft('a' * 32, REQUEST, NOTE, 100, 'model')
            sessions.record_final('a' * 32, NOTE, 2000)
            self.assertTrue(sessions.mark_printed('a' * 32))
            sessions.record_failure('b' * 32, REQUEST, 'text_timeout', 500)
            summary = sessions.summary()
            self.assertEqual(summary['total'], 2)
            self.assertEqual(summary['today'], 2)
            self.assertEqual(summary['generated'], 1)
            self.assertEqual(summary['printed'], 1)
            self.assertEqual(summary['failed'], 1)
            self.assertEqual(summary['audio'], 0)

    def test_audio_is_saved_served_and_cleared(self):
        import io
        import wave

        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as sample:
            sample.setnchannels(1)
            sample.setsampwidth(2)
            sample.setframerate(24000)
            sample.writeframes(b'\x00\x00' * 24000)
        raw = buffer.getvalue()
        with patch.dict('os.environ', self.env):
            seconds = sessions.save_audio('c' * 32, 'reply', raw)
            self.assertEqual(seconds, 1.0)
            path = sessions.audio_path('c' * 32, 'reply')
            self.assertTrue(path and Path(path).is_file())
            row = sessions.recent()[0]
            self.assertTrue(row['has_reply'])
            self.assertEqual(row['reply_seconds'], 1.0)
            self.assertEqual(row['visitor_no'], 1)
            self.assertEqual(sessions.summary()['audio'], 1)
            sessions.clear()
            self.assertFalse(Path(path).exists())
            self.assertEqual(sessions.summary()['total'], 0)

    def test_audio_path_rejects_unknown_kind_and_id(self):
        with patch.dict('os.environ', self.env):
            self.assertEqual(sessions.audio_path('c' * 32, 'other'), '')
            self.assertEqual(sessions.audio_path('short', 'reply'), '')


class VisitorBackfillTests(unittest.TestCase):
    def test_rows_without_numbers_are_labelled_in_creation_order(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {'JOURNEY_SESSION_LOG': '1', 'JOURNEY_SESSION_DB': str(Path(directory) / 's.sqlite3'),
                   'JOURNEY_SESSION_AUDIO_DIR': str(Path(directory) / 'audio')}
            with patch.dict('os.environ', env):
                sessions.record_draft('a' * 32, REQUEST, NOTE, 100, 'model')
                sessions.record_draft('b' * 32, REQUEST, NOTE, 100, 'model')
                with sqlite3.connect(Path(directory) / 's.sqlite3') as connection:
                    connection.execute('UPDATE sessions SET visitor_no = NULL')
                rows = {row['id']: row['visitor_no'] for row in sessions.recent()}
                self.assertEqual(rows['a' * 32], 1)
                self.assertEqual(rows['b' * 32], 2)
