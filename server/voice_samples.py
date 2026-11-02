"""Short-lived reference samples for the primary TTS.

The browser uploads a 5-30 s sample when it registers a cloned voice. The
primary (Amphion) TTS needs that sample for every synthesis, so keep a local
copy keyed by the journey voice name. Files are deleted when the voice is
deleted and pruned by age/count; they are never exposed to the browser.
"""
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r'journey_[a-f0-9]{32}\Z')
MAX_BYTES = 2 * 1024 * 1024


def directory():
    return Path(os.environ.get('JOURNEY_TTS_SAMPLE_DIR', str(ROOT / '.journey-state' / 'tts')))


def ttl_seconds():
    try:
        return max(300, min(86400, int(os.environ.get('JOURNEY_TTS_SAMPLE_TTL', '7200'))))
    except ValueError:
        return 7200


def max_files():
    try:
        return max(5, min(200, int(os.environ.get('JOURNEY_TTS_SAMPLE_MAX', '40'))))
    except ValueError:
        return 40


def save(voice, raw):
    if not NAME.fullmatch(voice or '') or not raw or len(raw) > MAX_BYTES:
        return False
    folder = directory()
    path = folder / f'{voice}.wav'
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o600)
    except OSError:
        return False
    prune()
    return True


def load(voice):
    if not NAME.fullmatch(voice or ''):
        return None
    path = directory() / f'{voice}.wav'
    try:
        if path.is_file() and time.time() - path.stat().st_mtime <= ttl_seconds():
            return path.read_bytes()
    except OSError:
        return None
    return None


def delete(voice):
    if not NAME.fullmatch(voice or ''):
        return
    try:
        (directory() / f'{voice}.wav').unlink()
    except OSError:
        pass


def prune():
    folder = directory()
    if not folder.is_dir():
        return
    try:
        files = sorted(folder.glob('*.wav'), key=lambda item: item.stat().st_mtime, reverse=True)
    except OSError:
        return
    now = time.time()
    for index, path in enumerate(files):
        try:
            if index >= max_files() or now - path.stat().st_mtime > ttl_seconds():
                path.unlink()
        except OSError:
            continue
