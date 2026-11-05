"""Runtime TTS provider selection for the future-notes booth.

The environment order remains the fallback for a fresh deployment. Once an
operator switches from the admin dashboard, the choice is stored in
``.journey-state/tts-settings.json`` (0600) and survives restarts and releases
that keep the state symlink.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MODES = {
    'amphion': {'label': '自研 TTS + 百炼', 'order': ['amphion', 'bailian']},
    'bailian': {'label': '百炼 Qwen', 'order': ['bailian']},
    'voxcpm2': {'label': 'VoxCPM2 + 百炼', 'order': ['voxcpm2', 'bailian']},
    'fireredtts3': {'label': 'FireRedTTS3 + 百炼', 'order': ['fireredtts3', 'bailian']},
}
DEFAULT_MODE = 'bailian'


def state_path() -> Path:
    configured = os.environ.get('JOURNEY_TTS_SETTINGS_FILE', '').strip()
    return Path(configured) if configured else ROOT / '.journey-state' / 'tts-settings.json'


def fallback_mode() -> str:
    raw = os.environ.get('JOURNEY_TTS_ORDER', '').strip().lower()
    items = [item.strip() for item in raw.split(',') if item.strip()]
    if items and items[0] in MODES:
        return items[0]
    return DEFAULT_MODE


def mode() -> str:
    path = state_path()
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        value = str(payload.get('mode', '')).strip().lower()
        if value in MODES:
            return value
    except (OSError, ValueError, TypeError):
        pass
    return fallback_mode()


def order() -> list[str]:
    return list(MODES[mode()]['order'])


def label(value: str | None = None) -> str:
    return MODES.get(value or mode(), MODES[DEFAULT_MODE])['label']


def set_mode(value: str) -> str:
    value = str(value or '').strip().lower()
    if value not in MODES:
        raise ValueError('未知的 TTS 模式')
    path = state_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = json.dumps({'mode': value}, ensure_ascii=False) + '\n'
    fd, temporary = tempfile.mkstemp(prefix='.tts-settings-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass
    return value


def status() -> dict:
    current = mode()
    return {
        'mode': current,
        'label': label(current),
        'order': order(),
        'modes': [{'value': key, 'label': value['label']} for key, value in MODES.items()],
    }
