"""Optional per-session records for the ops dashboard.

Off by default. With JOURNEY_SESSION_LOG=1 each visit is stored in
.journey-state/sessions.sqlite3 for JOURNEY_SESSION_RETENTION_DAYS days:
transcript (unless JOURNEY_SESSION_TRANSCRIPT=0), note, reply, keywords,
timings and print state. With JOURNEY_SESSION_AUDIO=1 the uploaded reference
sample and the generated reply WAV are kept under .journey-state/audio for
JOURNEY_SESSION_AUDIO_MAX recent visits. Storage failures never break a note.
"""
import json
import os
import re
import sqlite3
import time
import wave
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSION_ID = re.compile(r'[0-9a-zA-Z-]{8,64}\Z')
MAX_AUDIO_BYTES = 8 * 1024 * 1024


def enabled():
    return os.environ.get('JOURNEY_SESSION_LOG', '0').strip().lower() in {'1', 'true', 'yes'}


def keep_transcript():
    return os.environ.get('JOURNEY_SESSION_TRANSCRIPT', '1').strip().lower() not in {'0', 'false', 'no'}


def audio_enabled():
    return os.environ.get('JOURNEY_SESSION_AUDIO', '1').strip().lower() not in {'0', 'false', 'no'}


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


def max_audio():
    try:
        return max(10, min(500, int(os.environ.get('JOURNEY_SESSION_AUDIO_MAX', '120'))))
    except ValueError:
        return 120


def db_path():
    return Path(os.environ.get('JOURNEY_SESSION_DB', str(ROOT / '.journey-state' / 'sessions.sqlite3')))


def audio_dir():
    return Path(os.environ.get('JOURNEY_SESSION_AUDIO_DIR', str(ROOT / '.journey-state' / 'audio')))


COLUMNS = {
    'visitor_no': 'INTEGER',
    'status': "TEXT NOT NULL DEFAULT 'draft'",
    'error_code': "TEXT NOT NULL DEFAULT ''",
    'printed_at': 'TEXT',
    'sample_audio': 'TEXT',
    'reply_audio': 'TEXT',
    'reply_seconds': 'REAL',
    'visit_audio': 'TEXT',
    'visit_seconds': 'REAL',
}


def _migrate(connection):
    existing = {row[1] for row in connection.execute('PRAGMA table_info(sessions)')}
    for name, ddl in COLUMNS.items():
        if name not in existing:
            connection.execute(f'ALTER TABLE sessions ADD COLUMN {name} {ddl}')


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
    _migrate(connection)
    _backfill_visitors(connection)
    connection.execute('CREATE INDEX IF NOT EXISTS sessions_created ON sessions(created_at DESC)')
    return connection


@contextmanager
def _connection():
    connection = _connect()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _backfill_visitors(connection):
    """Rows created before visitor numbers existed get chronological labels once."""
    missing = connection.execute('SELECT COUNT(*) FROM sessions WHERE visitor_no IS NULL').fetchone()[0]
    if not missing:
        return
    rows = connection.execute('SELECT id FROM sessions ORDER BY created_at, rowid').fetchall()
    for index, row in enumerate(rows, 1):
        connection.execute('UPDATE sessions SET visitor_no = ? WHERE id = ?', (index, row['id']))


def _visitor(connection, session_id):
    row = connection.execute('SELECT visitor_no, created_at FROM sessions WHERE id = ?', (session_id,)).fetchone()
    if row and row['visitor_no']:
        return row['visitor_no'], row['created_at']
    number = connection.execute('SELECT COALESCE(MAX(visitor_no), 0) + 1 FROM sessions').fetchone()[0]
    return number, time.strftime('%Y-%m-%d %H:%M:%S')


def _prune(connection):
    connection.execute(
        "DELETE FROM sessions WHERE created_at < datetime('now', 'localtime', ?)",
        ('-' + str(retention_days()) + ' days',),
    )
    connection.execute(
        'DELETE FROM sessions WHERE id NOT IN (SELECT id FROM sessions ORDER BY created_at DESC LIMIT ?)',
        (max_rows(),),
    )
    _orphan_audio(connection)


def _orphan_audio(connection):
    if not audio_dir().exists():
        return
    known = {row[0] for row in connection.execute('SELECT id FROM sessions')}
    for file in audio_dir().glob('*.wav'):
        if file.name.split('.')[0] not in known:
            try:
                file.unlink()
            except OSError:
                pass


def _delete_audio_files(session_id):
    for kind in ('sample', 'reply', 'visit'):
        try:
            (audio_dir() / f'{session_id}.{kind}.wav').unlink()
        except OSError:
            pass


def _trim_audio(connection):
    rows = connection.execute(
        'SELECT id FROM sessions WHERE sample_audio IS NOT NULL OR reply_audio IS NOT NULL '
        'OR visit_audio IS NOT NULL ORDER BY created_at DESC LIMIT -1 OFFSET ?', (max_audio(),)
    ).fetchall()
    for row in rows:
        _delete_audio_files(row['id'])
        connection.execute(
            'UPDATE sessions SET sample_audio = NULL, reply_audio = NULL, reply_seconds = NULL, '
            'visit_audio = NULL, visit_seconds = NULL WHERE id = ?', (row['id'],)
        )


def record_draft(session_id, request, note, draft_ms, model):
    if not enabled():
        return
    transcript = request.transcript if keep_transcript() else None
    try:
        with _connection() as connection:
            visitor_no, created = _visitor(connection, session_id)
            connection.execute("""
                INSERT INTO sessions (id, created_at, visitor_no, status, topic, language, transcript,
                    transcript_chars, note_text, message, keywords, model, reviewed, draft_ms)
                VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = 'draft', error_code = '', topic = excluded.topic, language = excluded.language,
                    transcript = COALESCE(excluded.transcript, sessions.transcript),
                    transcript_chars = excluded.transcript_chars,
                    note_text = excluded.note_text, message = excluded.message, keywords = excluded.keywords,
                    model = excluded.model, reviewed = 0, draft_ms = excluded.draft_ms
            """, (session_id, created, visitor_no, request.topic, request.language, transcript,
                  len(request.transcript or ''), note.note_text, note.message,
                  json.dumps(note.keywords, ensure_ascii=False), model, int(draft_ms)))
            _prune(connection)
    except Exception as error:  # noqa: BLE001 - storage must not break the note
        print('session draft not stored:', type(error).__name__)


def record_final(session_id, note, final_ms):
    if not enabled():
        return
    try:
        with _connection() as connection:
            connection.execute(
                "UPDATE sessions SET status = 'final', note_text = ?, message = ?, keywords = ?, "
                "reviewed = 1, final_ms = ? WHERE id = ?",
                (note.note_text, note.message, json.dumps(note.keywords, ensure_ascii=False), int(final_ms), session_id),
            )
    except Exception as error:  # noqa: BLE001
        print('session final not stored:', type(error).__name__)


def record_failure(session_id, request, code, elapsed_ms):
    if not enabled():
        return
    transcript = request.transcript if keep_transcript() else None
    try:
        with _connection() as connection:
            visitor_no, created = _visitor(connection, session_id)
            connection.execute("""
                INSERT INTO sessions (id, created_at, visitor_no, status, error_code, topic, language,
                    transcript, transcript_chars, draft_ms)
                VALUES (?, ?, ?, 'failed', ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = 'failed', error_code = excluded.error_code,
                    transcript = COALESCE(excluded.transcript, sessions.transcript),
                    transcript_chars = excluded.transcript_chars
            """, (session_id, created, visitor_no, str(code)[:60], request.topic, request.language,
                  transcript, len(request.transcript or ''), int(elapsed_ms)))
            _prune(connection)
    except Exception as error:  # noqa: BLE001
        print('session failure not stored:', type(error).__name__)


def mark_printed(session_id):
    if not enabled() or not SESSION_ID.fullmatch(session_id or ''):
        return False
    try:
        with _connection() as connection:
            cursor = connection.execute(
                'UPDATE sessions SET printed_at = COALESCE(printed_at, ?) WHERE id = ?',
                (time.strftime('%Y-%m-%d %H:%M:%S'), session_id),
            )
            return cursor.rowcount > 0
    except Exception as error:  # noqa: BLE001
        print('print state not stored:', type(error).__name__)
        return False


def _wav_seconds(raw):
    try:
        with wave.open(BytesIO(raw), 'rb') as sample:
            rate = sample.getframerate()
            return round(sample.getnframes() / rate, 2) if rate else 0.0
    except (wave.Error, EOFError, ValueError):
        return 0.0


def save_audio(session_id, kind, raw):
    if kind not in ('sample', 'reply', 'visit') or not enabled() or not audio_enabled():
        return 0.0
    if not SESSION_ID.fullmatch(session_id or '') or not raw or len(raw) > MAX_AUDIO_BYTES:
        return 0.0
    seconds = _wav_seconds(raw)
    directory = audio_dir()
    path = directory / f'{session_id}.{kind}.wav'
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o600)
        with _connection() as connection:
            visitor_no, created = _visitor(connection, session_id)
            if kind == 'sample':
                connection.execute("""
                    INSERT INTO sessions (id, created_at, visitor_no, status, sample_audio)
                    VALUES (?, ?, ?, 'pending', ?)
                    ON CONFLICT(id) DO UPDATE SET sample_audio = excluded.sample_audio
                """, (session_id, created, visitor_no, str(path)))
            elif kind == 'reply':
                connection.execute("""
                    INSERT INTO sessions (id, created_at, visitor_no, status, reply_audio, reply_seconds)
                    VALUES (?, ?, ?, 'pending', ?, ?)
                    ON CONFLICT(id) DO UPDATE SET reply_audio = excluded.reply_audio,
                        reply_seconds = excluded.reply_seconds
                """, (session_id, created, visitor_no, str(path), seconds))
            else:
                connection.execute("""
                    INSERT INTO sessions (id, created_at, visitor_no, status, visit_audio, visit_seconds)
                    VALUES (?, ?, ?, 'pending', ?, ?)
                    ON CONFLICT(id) DO UPDATE SET visit_audio = excluded.visit_audio,
                        visit_seconds = excluded.visit_seconds
                """, (session_id, created, visitor_no, str(path), seconds))
            _trim_audio(connection)
        return seconds
    except Exception as error:  # noqa: BLE001
        print('session audio not stored:', type(error).__name__)
        try:
            path.unlink()
        except OSError:
            pass
        return 0.0


def audio_path(session_id, kind):
    if kind not in ('sample', 'reply', 'visit') or not enabled() or not SESSION_ID.fullmatch(session_id or ''):
        return ''
    column = {'sample': 'sample_audio', 'reply': 'reply_audio', 'visit': 'visit_audio'}[kind]
    with _connection() as connection:
        row = connection.execute(f'SELECT {column} FROM sessions WHERE id = ?', (session_id,)).fetchone()
    if not row or not row[0]:
        return ''
    path = Path(row[0])
    try:
        if path.resolve().parent != audio_dir().resolve() or not path.is_file():
            return ''
    except OSError:
        return ''
    return str(path)


def _row(row):
    keys = row.keys()
    return {
        'id': row['id'], 'visitor_no': row['visitor_no'] if 'visitor_no' in keys else None,
        'created_at': row['created_at'], 'topic': row['topic'], 'language': row['language'],
        'status': row['status'] if 'status' in keys else 'final',
        'error_code': row['error_code'] if 'error_code' in keys else '',
        'transcript': row['transcript'], 'transcript_chars': row['transcript_chars'],
        'note_text': row['note_text'], 'message': row['message'],
        'keywords': json.loads(row['keywords'] or '[]'), 'model': row['model'],
        'reviewed': bool(row['reviewed']), 'draft_ms': row['draft_ms'], 'final_ms': row['final_ms'],
        'printed_at': row['printed_at'] if 'printed_at' in keys else None,
        'has_sample': bool(row['sample_audio']) if 'sample_audio' in keys else False,
        'has_reply': bool(row['reply_audio']) if 'reply_audio' in keys else False,
        'reply_seconds': row['reply_seconds'] if 'reply_seconds' in keys else None,
        'has_visit': bool(row['visit_audio']) if 'visit_audio' in keys else False,
        'visit_seconds': row['visit_seconds'] if 'visit_seconds' in keys else None,
    }


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


def summary():
    base = {'enabled': enabled(), 'today': 0, 'total': 0, 'generated': 0, 'printed': 0, 'failed': 0,
            'audio': 0, 'retention_days': retention_days()}
    if not enabled():
        return base
    with _connection() as connection:
        base.update({
            'today': connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE date(created_at) = date('now', 'localtime')").fetchone()[0],
            'total': connection.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],
            'generated': connection.execute("SELECT COUNT(*) FROM sessions WHERE note_text <> ''").fetchone()[0],
            'printed': connection.execute('SELECT COUNT(*) FROM sessions WHERE printed_at IS NOT NULL').fetchone()[0],
            'failed': connection.execute("SELECT COUNT(*) FROM sessions WHERE status = 'failed'").fetchone()[0],
            'audio': connection.execute(
                'SELECT COUNT(*) FROM sessions WHERE sample_audio IS NOT NULL OR reply_audio IS NOT NULL '
                'OR visit_audio IS NOT NULL').fetchone()[0],
        })
    return base


def clear():
    with _connection() as connection:
        connection.execute('DELETE FROM sessions')
    if audio_dir().exists():
        for file in audio_dir().glob('*.wav'):
            try:
                file.unlink()
            except OSError:
                pass
