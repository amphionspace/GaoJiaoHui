"""Private Qwen3-TTS worker for the journey; no persistent voice database."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
import hashlib
import io
import logging
import os
import re
import time
import wave

import httpx
import numpy as np
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

MODEL = "Qwen3-TTS-12Hz-1.7B-Base"
VOICE_NAME = re.compile(r"journey_[a-f0-9]{32}\Z")
MAX_UPLOAD = 2 * 1024 * 1024
TTL = 1800
logger = logging.getLogger("journey_tts")


def read_sample(raw):
    try:
        with wave.open(io.BytesIO(raw)) as wav:
            rate, frames = wav.getframerate(), wav.getnframes()
            if (wav.getnchannels() != 1 or wav.getsampwidth() != 2 or
                    rate not in (16000, 24000, 48000) or not 5 <= frames / rate <= 15):
                raise ValueError()
            pcm = wav.readframes(frames)
            if len(pcm) != frames * 2:
                raise ValueError()
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        chunks = audio[:len(audio) // (rate // 50) * (rate // 50)].reshape(-1, rate // 50)
        if np.count_nonzero(np.sqrt(np.mean(chunks ** 2, axis=1)) > .004) < 150:
            raise ValueError()
        return audio, rate
    except (wave.Error, EOFError, ValueError):
        raise HTTPException(400, "请提供 5 至 15 秒清晰的单声道 WAV 本人录音。") from None


class QwenEngine:
    def __init__(self):
        import torch
        from qwen_tts import Qwen3TTSModel
        torch.set_num_threads(4)
        # Bound this new worker's allocations on the shared GPU.
        torch.cuda.set_per_process_memory_fraction(.14, 0)
        self.model = Qwen3TTSModel.from_pretrained(
            os.environ.get("JOURNEY_TTS_MODEL", "/data/models/" + MODEL),
            device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa",
            local_files_only=True,
        )

    def prepare(self, audio, rate, transcript):
        return self.model.create_voice_clone_prompt(
            ref_audio=(audio, rate), ref_text=transcript, x_vector_only_mode=False,
        )

    def synthesize(self, prompt, text):
        import soundfile as sf
        waves, rate = self.model.generate_voice_clone(
            text=text, language="Chinese", voice_clone_prompt=prompt,
            non_streaming_mode=True, max_new_tokens=min(1200, max(300, len(text) * 8)),
        )
        samples = waves[0]
        if not len(samples) or not np.isfinite(samples).all() or np.max(np.abs(samples)) < .001:
            raise RuntimeError("empty synthesis")
        result = io.BytesIO()
        sf.write(result, samples, rate, format="WAV", subtype="PCM_16")
        return result.getvalue()


@dataclass
class Voice:
    owner: str
    expires: float
    prompt: object = None


class Speech(BaseModel):
    voice: str = Field(min_length=1, max_length=64)
    input: str = Field(min_length=1, max_length=200)
    response_format: str = "wav"
    sample_rate: int = 24000


def create_app(engine_factory=QwenEngine, upstream_transport=None, ttl=TTL):
    voices = {}
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="journey-gpu")
    pending = 0
    engine = None
    client = None

    def expire():
        now = time.monotonic()
        for name, voice in list(voices.items()):
            if voice.expires <= now:
                del voices[name]

    async def sweep():
        while True:
            await asyncio.sleep(30)
            expire()

    @asynccontextmanager
    async def lifespan(app):
        nonlocal engine, client
        engine = await asyncio.get_running_loop().run_in_executor(executor, engine_factory)
        client = httpx.AsyncClient(transport=upstream_transport, timeout=45, trust_env=False)
        sweeper = asyncio.create_task(sweep())
        logger.warning("Journey TTS ready: %s", MODEL)
        try:
            yield
        finally:
            sweeper.cancel()
            with suppress(asyncio.CancelledError):
                await sweeper
            voices.clear()
            await client.aclose()
            executor.shutdown(wait=True, cancel_futures=True)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    async def owner(x_api_key: str = Header(default="")):
        if not x_api_key or len(x_api_key) > 512:
            raise HTTPException(401, "需要有效的语音网关密钥。")
        try:
            result = await client.get(
                "http://127.0.0.1:18910/tts/v1/audio/voices",
                headers={"X-API-Key": x_api_key}, timeout=8,
            )
        except httpx.HTTPError:
            raise HTTPException(503, "网关鉴权服务暂时不可用。") from None
        if result.status_code in (401, 403):
            raise HTTPException(result.status_code, "语音网关密钥无效或权限不足。")
        if result.status_code != 200:
            raise HTTPException(503, "网关鉴权服务暂时不可用。")
        return hashlib.sha256(x_api_key.encode()).hexdigest()

    async def run_model(method, *args):
        nonlocal pending
        if pending >= 3:
            raise HTTPException(429, "声音服务正在处理其他录音，请稍后重试。")
        pending += 1
        future = asyncio.get_running_loop().run_in_executor(executor, method, *args)

        def finished(result):
            nonlocal pending
            pending -= 1
            # Retrieve errors even when the requesting client has disconnected.
            if not result.cancelled():
                result.exception()
        future.add_done_callback(finished)
        try:
            return await asyncio.shield(future)
        except Exception as error:
            logger.error("Model operation failed: %s", type(error).__name__)
            raise HTTPException(503, "本人声音模型暂时无法处理请求，请稍后重试。") from None

    @app.get("/health")
    async def health():
        return {"ready": engine is not None, "model": MODEL, "pending": pending}

    @app.get("/v1/audio/voices")
    async def list_voices(identity=Depends(owner)):
        expire()
        return {"ready": engine is not None, "model": MODEL, "ttl_seconds": ttl,
                "voice_limit": 4, "voices": [
                    {"voice_name": name, "status": "ready" if voice.prompt else "preparing"}
                    for name, voice in voices.items() if voice.owner == identity
                ]}

    @app.post("/v1/audio/voices")
    async def register(voice_name: str = Form(), audio_file: UploadFile = File(), identity=Depends(owner)):
        if not VOICE_NAME.fullmatch(voice_name):
            raise HTTPException(400, "无效的手记会话编号。")
        raw = await audio_file.read(MAX_UPLOAD + 1)
        await audio_file.close()
        if len(raw) > MAX_UPLOAD:
            raise HTTPException(413, "录音文件过大。")
        audio, rate = read_sample(raw)
        expire()
        if voice_name in voices:
            raise HTTPException(409, "该会话编号已被使用。")
        if len(voices) >= 32 or sum(v.owner == identity for v in voices.values()) >= 4:
            raise HTTPException(429, "临时音色名额已满，请结束其他手记会话后重试。")
        voice = voices[voice_name] = Voice(identity, time.monotonic() + ttl)
        try:
            try:
                result = await client.post(
                    "http://172.16.0.4:8010/v1/audio/transcriptions",
                    files={"file": ("sample.wav", raw, "audio/wav")},
                    data={"model": "/data/models/Qwen3-ASR-1.7B", "response_format": "json"},
                )
                result.raise_for_status()
                transcript = result.json().get("text", "").strip()
            except (httpx.HTTPError, ValueError, AttributeError):
                raise HTTPException(503, "参考录音识别服务暂时不可用，请重试。") from None
            if not transcript or len(transcript) > 1000:
                raise HTTPException(400, "未能听清参考录音，请继续补充几句话。")
            prompt = await run_model(engine.prepare, audio, rate, transcript)
            if voices.get(voice_name) is not voice:
                raise HTTPException(410, "本次录音会话已结束。")
            voice.prompt = prompt
            voice.expires = time.monotonic() + ttl
            return {"status": "ready", "model": MODEL, "voice": {"voice_name": voice_name}}
        finally:
            if voice.prompt is None and voices.get(voice_name) is voice:
                del voices[voice_name]

    @app.delete("/v1/audio/voices/{name}")
    async def remove(name: str, identity=Depends(owner)):
        voice = voices.get(name)
        if voice is None or voice.owner != identity:
            raise HTTPException(404, "临时音色不存在或已过期。")
        del voices[name]
        return {"status": "deleted"}

    @app.post("/v1/audio/speech")
    async def speech(body: Speech, identity=Depends(owner)):
        if body.response_format != "wav" or body.sample_rate != 24000 or not body.input.strip():
            raise HTTPException(400, "请提供有效文字，输出格式为 24kHz WAV。")
        expire()
        voice = voices.get(body.voice)
        if voice is None or voice.owner != identity:
            raise HTTPException(404, "临时音色已过期，请用本次录音重新生成。")
        if voice.prompt is None:
            raise HTTPException(409, "本人音色仍在准备中。")
        voice.expires = time.monotonic() + ttl
        result = await run_model(engine.synthesize, voice.prompt, body.input.strip())
        return Response(result, media_type="audio/wav", headers={"Cache-Control": "no-store", "X-TTS-Model": MODEL})

    return app


app = create_app()
