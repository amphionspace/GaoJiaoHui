"""Server-side Bailian voice cloning adapter for the future-notes journey."""
from __future__ import annotations

import base64
import audioop
import binascii
import hashlib
import io
import json
import os
import re
import sqlite3
import wave
from contextlib import contextmanager
from pathlib import Path

import httpx
from fastapi import HTTPException, Request, UploadFile

try:
    from . import security
except ImportError:
    import security


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / ".env.bailian.json"
VOICE_API_PATH = "/api/v1/services/audio/tts/customization"
VOICE_MODEL = "qwen-voice-enrollment"
JOURNEY_VOICE = re.compile(r"journey_[a-f0-9]{32}\Z")
MAX_UPLOAD = 2 * 1024 * 1024
STATE_FILE = ROOT / '.journey-state' / 'voices.sqlite3'


@contextmanager
def _database():
    STATE_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(STATE_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute('CREATE TABLE IF NOT EXISTS voices (owner TEXT, name TEXT, remote TEXT, model TEXT, PRIMARY KEY (owner, name))')
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _owner(key):
    return hashlib.sha256(key.encode()).hexdigest()


def _registered(key, name):
    with _database() as db:
        row = db.execute('SELECT * FROM voices WHERE owner = ? AND name = ?', (_owner(key), name)).fetchone()
    return dict(row) if row else None


def configuration() -> dict[str, str]:
    values: dict[str, object] = {}
    if CONFIG_FILE.exists():
        try:
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError()
            values = loaded
        except (OSError, ValueError):
            raise HTTPException(503, "百炼 TTS 配置文件无法读取，请检查 .env.bailian.json。") from None
    config = {
        "api_key": str(os.environ.get("BAILIAN_API_KEY", values.get("api_key", ""))).strip(),
        "base_url": str(os.environ.get("BAILIAN_BASE_URL", values.get("base_url", ""))).strip().rstrip("/"),
        "compatible_base_url": str(os.environ.get(
            "BAILIAN_COMPATIBLE_BASE_URL", values.get("compatible_base_url", "")
        )).strip().rstrip("/"),
        "target_model": str(os.environ.get(
            "BAILIAN_TTS_MODEL", values.get("target_model", "qwen3.5-omni-plus")
        )).strip(),
    }
    if not config["api_key"] or not config["base_url"] or not config["compatible_base_url"]:
        raise HTTPException(503, "百炼 TTS 尚未配置完整，请检查服务端敏感配置。")
    return config


def enabled() -> bool:
    return os.environ.get("JOURNEY_TTS_PROVIDER", "legacy").strip().lower() in {"bailian", "aliyun"}


def _headers(config: dict[str, str]) -> dict[str, str]:
    return {"Authorization": "Bearer " + config["api_key"], "Content-Type": "application/json"}


def _safe_upstream_error(response: httpx.Response, config: dict[str, str], operation: str) -> HTTPException:
    message = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            message = str(payload.get("message") or payload.get("error") or payload.get("code") or "")
    except (ValueError, TypeError):
        pass
    message = message.replace(config["api_key"], "[redacted]").replace("\n", " ").strip()[:180]
    suffix = f"：{message}" if message else ""
    status = 502 if response.status_code >= 500 else response.status_code
    return HTTPException(status, f"百炼{operation}失败（HTTP {response.status_code}）{suffix}")


async def _post_json(client: httpx.AsyncClient, url: str, config: dict[str, str], payload: dict, operation: str):
    try:
        response = await client.post(url, headers=_headers(config), json=payload)
    except httpx.TimeoutException:
        raise HTTPException(504, f"百炼{operation}超时，请稍后重试。") from None
    except httpx.RequestError:
        raise HTTPException(502, f"无法连接百炼{operation}服务，请稍后重试。") from None
    if response.status_code >= 400:
        raise _safe_upstream_error(response, config, operation)
    try:
        return response.json()
    except ValueError:
        raise HTTPException(502, f"百炼{operation}返回了无法识别的结果。") from None


async def require_client_key(request: Request) -> str:
    await security.access.authorize(request)
    return request.headers['x-api-key'].strip()


async def list_voices(request: Request):
    key = await require_client_key(request)
    config = configuration()
    with _database() as db:
        rows = db.execute('SELECT name, model FROM voices WHERE owner = ?', (_owner(key),)).fetchall()
    return {
        "ready": True,
        "model": config["target_model"],
        "voice_limit": 1000,
        "voices": [
            {"voice_name": item["name"], "status": "ready", "target_model": item["model"]}
            for item in rows
        ],
    }


async def create_voice(request: Request, voice_name: str, audio_file: UploadFile):
    key = await require_client_key(request)
    if not JOURNEY_VOICE.fullmatch(voice_name):
        raise HTTPException(400, "无效的手记会话编号。")
    raw = await audio_file.read(MAX_UPLOAD + 1)
    await audio_file.close()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "录音文件过大。")
    if not raw.startswith(b"RIFF") or b"WAVE" not in raw[:16]:
        raise HTTPException(400, "请提供 WAV 格式的本人录音。")
    try:
        with wave.open(io.BytesIO(raw), 'rb') as sample:
            rate = sample.getframerate()
            if sample.getnchannels() != 1 or sample.getsampwidth() != 2 or rate < 16000 or not 5 <= sample.getnframes() / rate <= 30:
                raise ValueError()
            pcm = sample.readframes(sample.getnframes())
            if len(pcm) != sample.getnframes() * 2:
                raise ValueError()
        if rate != 24000:
            pcm, _ = audioop.ratecv(pcm, 2, 1, rate, 24000, None)
        raw = _wav_from_pcm(pcm)
    except (wave.Error, EOFError, ValueError, audioop.error):
        raise HTTPException(400, "需要 5 至 30 秒的清晰单声道录音，请继续讲几句话。") from None
    existing = _registered(key, voice_name)
    if existing:
        return {"status": "ready", "model": existing['model'], "voice": {"voice_name": voice_name}}
    data_uri = "data:audio/wav;base64," + base64.b64encode(raw).decode("ascii")
    config = configuration()
    payload = {
        "model": VOICE_MODEL,
        "input": {
            "action": "create",
            "target_model": config["target_model"],
            "preferred_name": voice_name[:16],
            "audio": {"data": data_uri},
        },
    }
    result = await _post_json(
        request.app.state.bailian_client,
        config["base_url"] + VOICE_API_PATH,
        config,
        payload,
        "声音复刻",
    )
    voice = ((result.get("output") or {}).get("voice") if isinstance(result, dict) else "")
    if not voice:
        raise HTTPException(502, "百炼声音复刻完成但没有返回音色编号。")
    with _database() as db:
        db.execute('INSERT INTO voices (owner, name, remote, model) VALUES (?, ?, ?, ?)',
                   (_owner(key), voice_name, voice, config['target_model']))
    return {"status": "ready", "model": config["target_model"], "voice": {"voice_name": voice_name}}


async def delete_voice(request: Request, voice: str):
    key = await require_client_key(request)
    if not JOURNEY_VOICE.fullmatch(voice):
        raise HTTPException(404, "临时音色不存在。")
    registered = _registered(key, voice)
    if not registered:
        raise HTTPException(404, "临时音色不存在。")
    config = configuration()
    try:
        await _post_json(
            request.app.state.bailian_client,
            config["base_url"] + VOICE_API_PATH,
            config,
            {"model": VOICE_MODEL, "input": {"action": "delete", "voice": registered['remote']}},
            "音色删除",
        )
    except HTTPException as error:
        if error.status_code != 404:
            raise
    with _database() as db:
        db.execute('DELETE FROM voices WHERE owner = ? AND name = ?', (_owner(key), voice))
    return {"status": "deleted"}


def _wav_from_pcm(raw: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(raw)
    return output.getvalue()


async def synthesize(request: Request):
    key = await require_client_key(request)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "合成请求不是有效 JSON。") from None
    if not isinstance(body, dict):
        raise HTTPException(400, "合成请求不是有效 JSON 对象。")
    voice = str(body.get("voice", "")).strip()
    text = str(body.get("input", "")).strip()
    if not JOURNEY_VOICE.fullmatch(voice) or not text or len(text) > 600:
        raise HTTPException(400, "请提供有效的本人音色和朗读文字。")
    registered = _registered(key, voice)
    if not registered:
        raise HTTPException(404, "本次音色已失效，请重新生成本人声音。")
    config = configuration()
    payload = {
        "model": registered['model'],
        "messages": [{"role": "system", "content": "请保持所选本人音色，像在给熟悉的人打私人电话一样说话。声音自然、贴近，有轻微语气起伏和句间停顿；安慰时温和，鼓励时坚定。不要播音腔、演讲腔，不要刻意拖长或逐字顿读。仅逐字说出用户提供的文字，不回答、不改写、不添加开场白或结尾。"}, {"role": "user", "content": text}],
        "modalities": ["text", "audio"],
        "audio": {"voice": registered['remote'], "format": "wav"},
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    headers = _headers(config)
    url = config['compatible_base_url'] + '/chat/completions'
    audio_b64 = ""
    try:
        async with request.app.state.bailian_client.stream(
            "POST", url, headers=headers, json=payload,
        ) as response:
            if response.status_code >= 400:
                await response.aread()
                raise _safe_upstream_error(response, config, "声音合成")
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if value == "[DONE]":
                    break
                try:
                    event = json.loads(value)
                except ValueError:
                    continue
                if event.get('code'):
                    raise HTTPException(502, '百炼声音合成未完成，请稍后重试。')
                for choice in event.get("choices", []):
                    audio = ((choice.get("delta") or {}).get("audio") or {})
                    if isinstance(audio, dict):
                        audio_b64 += str(audio.get("data") or "")
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(504, "百炼声音合成超时，请稍后重试。") from None
    except httpx.RequestError:
        raise HTTPException(502, "无法连接百炼声音合成服务，请稍后重试。") from None
    if audio_b64.startswith("data:") and "," in audio_b64:
        audio_b64 = audio_b64.split(",", 1)[1]
    try:
        raw = base64.b64decode(audio_b64, validate=False)
    except (binascii.Error, ValueError):
        raw = b""
    if not raw:
        raise HTTPException(502, "百炼没有返回可播放的声音。")
    if raw.startswith(b"RIFF"):
        wav = raw
    else:
        wav = _wav_from_pcm(raw)
    return wav
