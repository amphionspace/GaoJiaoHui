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
MAX_TEXT = 500


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


def save(voice, raw, reference_text=''):
    if not NAME.fullmatch(voice or '') or not raw or len(raw) > MAX_BYTES:
        return False
    folder = directory()
    path = folder / f'{voice}.wav'
    text_path = folder / f'{voice}.txt'
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o600)
        text = str(reference_text or '').strip()[:MAX_TEXT]
        if text:
            text_path.write_text(text + '\n', encoding='utf-8')
            text_path.chmod(0o600)
        else:
            try:
                text_path.unlink()
            except OSError:
                pass
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


def load_text(voice):
    if not NAME.fullmatch(voice or ''):
        return None
    folder = directory()
    path = folder / f'{voice}.wav'
    text_path = folder / f'{voice}.txt'
    try:
        if not path.is_file() or time.time() - path.stat().st_mtime > ttl_seconds():
            return None
        if text_path.is_file():
            return text_path.read_text(encoding='utf-8').strip()[:MAX_TEXT] or None
    except OSError:
        return None
    return None


def delete(voice):
    if not NAME.fullmatch(voice or ''):
        return
    folder = directory()
    for suffix in ('.wav', '.txt'):
        try:
            (folder / f'{voice}{suffix}').unlink()
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
                try:
                    path.with_suffix('.txt').unlink()
                except OSError:
                    pass
        except OSError:
            continue
    for text_path in folder.glob('*.txt'):
        if not text_path.with_suffix('.wav').exists():
            try:
                text_path.unlink()
            except OSError:
                pass
