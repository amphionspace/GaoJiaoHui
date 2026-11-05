"""Client for the Amphion test TTS (Emilia2 / Qwen3-TTS) used as the primary voice.

The service is anonymous for /tts-api: a reference WAV plus the text is enough,
so the visitor's sample can be reused without a saved voice. A short cooldown
after a failure keeps a flapping primary from delaying every request.
"""
import base64
import os
import time

import httpx

try:
    from . import tts_settings
except ImportError:
    import tts_settings

DEFAULT_URL = 'https://test-playground.amphion.top'
READY_CACHE_SECONDS = 20
_ready = {'at': 0.0, 'ok': False, 'model': '', 'latency_ms': 0}
_cooldown_until = 0.0


class AmphionError(Exception):
    pass


def base_url():
    return (os.environ.get('AMPHION_TTS_URL', '').strip() or DEFAULT_URL).rstrip('/')


def order():
    return tts_settings.order()


def enabled():
    return 'amphion' in order()


def timeout_seconds():
    try:
        return max(5.0, min(120.0, float(os.environ.get('AMPHION_TTS_TIMEOUT', '45'))))
    except ValueError:
        return 45.0


def cooldown_seconds():
    try:
        return max(0.0, min(300.0, float(os.environ.get('AMPHION_TTS_COOLDOWN', '30'))))
    except ValueError:
        return 30.0


def cooling_down():
    return time.monotonic() < _cooldown_until


def cooldown_remaining():
    return max(0.0, round(_cooldown_until - time.monotonic(), 1))


def note_failure():
    global _cooldown_until
    _cooldown_until = time.monotonic() + cooldown_seconds()


def note_success():
    global _cooldown_until
    _cooldown_until = 0.0


def language_name(value):
    return 'English' if str(value or '').lower().startswith('en') else 'Chinese'


async def ready(force=False, timeout=2.5):
    """Readiness with a short cache; never raises."""
    now = time.monotonic()
    if not enabled():
        return {'ok': False, 'model': '', 'latency_ms': 0, 'at': now, 'cached': True, 'enabled': False}
    if not force and now - _ready['at'] < READY_CACHE_SECONDS:
        return {**_ready, 'cached': True, 'enabled': True}
    started = time.monotonic()
    ok, model = False, ''
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.get(base_url() + '/tts-api/ready')
        if response.status_code == 200:
            payload = response.json()
            ok = payload.get('status') == 'ok'
            model = str(payload.get('model', ''))
    except Exception:  # noqa: BLE001 - readiness must never break a health probe
        ok = False
    _ready.update(at=now, ok=ok, model=model, latency_ms=round((time.monotonic() - started) * 1000))
    return {**_ready, 'cached': False, 'enabled': True}


async def synthesize(text, sample, language='Chinese'):
    """Return a complete WAV (24 kHz mono) using the reference sample."""
    payload = {
        'input': str(text)[:2000],
        'ref_audio': 'data:audio/wav;base64,' + base64.b64encode(sample).decode('ascii'),
        'x_vector_only_mode': True,
        'language': language_name(language),
        'response_format': 'wav',
        'max_new_tokens': 512,
    }
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds(), trust_env=False) as client:
            response = await client.post(base_url() + '/tts-api/v1/audio/speech', json=payload)
    except httpx.HTTPError as error:
        note_failure()
        raise AmphionError(type(error).__name__) from None
    if response.status_code >= 400:
        note_failure()
        raise AmphionError('http ' + str(response.status_code))
    if not response.content.startswith(b'RIFF'):
        note_failure()
        raise AmphionError('not wav')
    note_success()
    return response.content


def last_latency_ms(started):
    return round((time.monotonic() - started) * 1000)
