"""VoxCPM2 / FireRedTTS3 clone TTS for the future-notes booth.

The evaluation endpoint is stateless: every clone request includes the short
reference WAV and its transcript. The booth stores the transcript beside the
reference sample when the visitor's voice is registered.
"""
from __future__ import annotations

import asyncio
import os

import httpx

DEFAULT_BASE = 'https://speeker.amphiondev.com'
MODELS = ('voxcpm2', 'fireredtts3')


class EvalTTSError(Exception):
    def __init__(self, message, *, status=0, detail=''):
        super().__init__(message)
        self.status = status
        self.detail = str(detail or '')[:220]


def configuration() -> dict:
    key = os.environ.get('EVAL_TTS_API_KEY', '').strip()
    if not key:
        raise EvalTTSError('EVAL_TTS_API_KEY 尚未配置', status=503)
    return {
        'api_key': key,
        'base_url': (os.environ.get('EVAL_TTS_BASE_URL', '').strip() or DEFAULT_BASE).rstrip('/'),
        'timeout': max(30.0, min(300.0, float(os.environ.get('EVAL_TTS_TIMEOUT', '180')))),
        'retries': max(0, min(3, int(os.environ.get('EVAL_TTS_RETRIES', '2')))),
        'language': os.environ.get('EVAL_TTS_LANGUAGE', 'Chinese').strip() or 'Chinese',
    }


def enabled() -> bool:
    return bool(os.environ.get('EVAL_TTS_API_KEY', '').strip())


def language_name(value=None) -> str:
    value = str(value or '').lower()
    return 'English' if value.startswith('en') else 'Chinese'


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return str(payload.get('detail') or payload.get('message') or payload)[:220]
    except (ValueError, TypeError):
        pass
    return (response.text or '')[:220]


async def synthesize(model: str, text: str, reference: bytes, reference_text: str,
                     language: str = 'Chinese') -> bytes:
    if model not in MODELS:
        raise EvalTTSError('未知的评测 TTS 模型', status=400)
    if not reference or not reference.startswith(b'RIFF') or not reference_text.strip():
        raise EvalTTSError('缺少参考音频或原文', status=400)
    config = configuration()
    files = {'reference': ('reference.wav', reference, 'audio/wav')}
    data = {
        'mode': 'clone',
        'text': str(text)[:500],
        'reference_text': str(reference_text).strip()[:500],
    }
    if model == 'fireredtts3':
        data['language'] = language_name(language)
    url = config['base_url'] + '/tts-eval/speech/' + model
    headers = {'Authorization': 'Bearer ' + config['api_key']}
    last_error = None
    for attempt in range(config['retries'] + 1):
        try:
            async with httpx.AsyncClient(timeout=config['timeout'], trust_env=False) as client:
                response = await client.post(url, headers=headers, data=data, files=files)
        except httpx.TimeoutException:
            last_error = EvalTTSError('评测 TTS 合成超时', status=504)
            if attempt < config['retries']:
                await asyncio.sleep(1.2 * (attempt + 1)); continue
            raise last_error from None
        except httpx.RequestError as error:
            last_error = EvalTTSError('评测 TTS 连接失败', status=502, detail=type(error).__name__)
            if attempt < config['retries']:
                await asyncio.sleep(1.2 * (attempt + 1)); continue
            raise last_error from None
        if response.status_code == 429 and attempt < config['retries']:
            try:
                delay = max(0.1, min(10.0, float(response.headers.get('retry-after', '1.5'))))
            except ValueError:
                delay = 1.5
            await asyncio.sleep(delay)
            last_error = EvalTTSError('评测 TTS 模型繁忙', status=429)
            continue
        if response.status_code >= 400:
            raise EvalTTSError('评测 TTS 合成失败', status=response.status_code, detail=_error_detail(response))
        body = response.content
        if not body.startswith(b'RIFF'):
            raise EvalTTSError('评测 TTS 返回的不是 WAV', status=502)
        return body
    raise last_error or EvalTTSError('评测 TTS 暂不可用', status=503)


def status() -> dict:
    try:
        configuration()
        return {'ok': True, 'configured': True}
    except EvalTTSError as error:
        return {'ok': False, 'configured': False, 'detail': str(error)}
