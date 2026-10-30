"""Optional per-session records for the ops dashboard.

Off by default. With JOURNEY_SESSION_LOG=1 the reviewed note is stored in
.journey-state/sessions.sqlite3 for JOURNEY_SESSION_RETENTION_DAYS days; the
raw transcript is stored only when JOURNEY_SESSION_TRANSCRIPT is not '0'.
Audio is never stored. Storage failures must never break a visitor's note.
"""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def enabled():
    return os.environ.get('JOURNEY_SESSION_LOG', '0').strip().lower() in {'1', 'true', 'yes'}


def keep_transcript():
    return os.environ.get('JOURNEY_SESSION_TRANSCRIPT', '1').strip().lower() not in {'0', 'false', 'no'}


def retention_days():
    try:
        return max(1, min(90, int(os.environ.get('JOURNEY_SESSION_RETENTION_DAYS', '7'))))
    except ValueError:
        return 7


def max_rows():
    try:
        return max(20, min(5000, int(os.environ.get('JOURNEY_SESSION_MAX', '500'))))
    except ValueError:
        return 500


def db_path():
    return Path(os.environ.get('JOURNEY_SESSION_DB', str(ROOT / '.journey-state' / 'sessions.sqlite3')))


def _connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            topic TEXT NOT NULL DEFAULT '',
            language TEXT NOT NULL DEFAULT 'zh',
            transcript TEXT,
            transcript_chars INTEGER NOT NULL DEFAULT 0,
            note_text TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL DEFAULT '',
            keywords TEXT NOT NULL DEFAULT '[]',
            model TEXT NOT NULL DEFAULT '',
            reviewed INTEGER NOT NULL DEFAULT 0,
            draft_ms INTEGER,
            final_ms INTEGER
        )
    """)
    connection.execute('CREATE INDEX IF NOT EXISTS sessions_created ON sessions(created_at DESC)')
    return connection


def _prune(connection):
    connection.execute(
        "DELETE FROM sessions WHERE created_at < datetime('now', 'localtime', ?)",
        ('-' + str(retention_days()) + ' days',),
    )
    connection.execute(
        'DELETE FROM sessions WHERE id NOT IN (SELECT id FROM sessions ORDER BY created_at DESC LIMIT ?)',
        (max_rows(),),
    )


@contextmanager
def _connection():
    connection = _connect()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def record_draft(session_id, request, note, draft_ms, model):
    if not enabled():
        return
    transcript = request.transcript if keep_transcript() else None
    try:
        with _connection() as connection:
            connection.execute(
                'INSERT OR REPLACE INTO sessions (id, created_at, topic, language, transcript, transcript_chars, '
                'note_text, message, keywords, model, reviewed, draft_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)',
                (session_id, time.strftime('%Y-%m-%d %H:%M:%S'), request.topic, request.language, transcript,
                 len(request.transcript or ''), note.note_text, note.message,
                 json.dumps(note.keywords, ensure_ascii=False), model, int(draft_ms)),
            )
            _prune(connection)
    except Exception as error:  # noqa: BLE001 - storage must not break the note
        print('session draft not stored:', type(error).__name__)


def record_final(session_id, note, final_ms):
    if not enabled():
        return
    try:
        with _connection() as connection:
            connection.execute(
                'UPDATE sessions SET note_text = ?, message = ?, keywords = ?, reviewed = 1, final_ms = ? WHERE id = ?',
                (note.note_text, note.message, json.dumps(note.keywords, ensure_ascii=False), int(final_ms), session_id),
            )
    except Exception as error:  # noqa: BLE001 - storage must not break the note
        print('session final not stored:', type(error).__name__)


def _row(row):
    item = {
        'id': row['id'], 'created_at': row['created_at'], 'topic': row['topic'], 'language': row['language'],
        'transcript': row['transcript'], 'transcript_chars': row['transcript_chars'],
        'note_text': row['note_text'], 'message': row['message'],
        'keywords': json.loads(row['keywords'] or '[]'), 'model': row['model'],
        'reviewed': bool(row['reviewed']), 'draft_ms': row['draft_ms'], 'final_ms': row['final_ms'],
    }
    return item


def recent(limit=30, offset=0):
    if not enabled():
        return []
    with _connection() as connection:
        rows = connection.execute(
            'SELECT * FROM sessions ORDER BY created_at DESC LIMIT ? OFFSET ?', (limit, offset)
        ).fetchall()
    return [_row(row) for row in rows]


def count():
    if not enabled():
        return 0
    with _connection() as connection:
        return connection.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]


def clear():
    with _connection() as connection:
        connection.execute('DELETE FROM sessions')
