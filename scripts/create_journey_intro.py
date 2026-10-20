"""Render the fixed welcome audio once; never expose the provider key to visitors."""
import asyncio
import audioop
import base64
import io
import json
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from server.bailian_tts import configuration, _headers, _safe_upstream_error, _wav_from_pcm

TEXT = "像打电话一样，把想说的内容告诉我。今天，哪一项新科技让你印象最深？你希望它为你，或你在意的人，带来什么改变？"
OUTPUT = ROOT / 'frontend/public/journey/call-intro.wav'


async def main():
    config = configuration()
    async with httpx.AsyncClient(timeout=90) as client:
        encoded = ''
        async with client.stream('POST', config['compatible_base_url'] + '/chat/completions',
                                 headers=_headers(config), json={
            'model': 'qwen3.5-omni-plus', 'stream': True, 'modalities': ['text', 'audio'],
            'audio': {'voice': 'Serena', 'format': 'wav'},
            'messages': [
                {'role': 'system', 'content': '请用自然、温柔而坚定的女声，像一位耐心的朋友接起电话。语速舒缓，句子间有自然停顿。不要播音腔，不要甜腻，不要夸张。仅逐字朗读用户提供的文字，不回答、不改写、不添加开场白。'},
                {'role': 'user', 'content': TEXT},
            ],
        }) as response:
            if response.status_code >= 400:
                await response.aread()
                raise RuntimeError(_safe_upstream_error(response, config, '引导语合成').detail)
            async for line in response.aiter_lines():
                if not line.startswith('data:') or line[5:].strip() == '[DONE]':
                    continue
                event = json.loads(line[5:])
                if event.get('error') or event.get('code'):
                    raise RuntimeError('引导语流式合成失败')
                for choice in event.get('choices', []):
                    encoded += (choice.get('delta', {}).get('audio') or {}).get('data', '')
    raw = base64.b64decode(encoded)
    if not raw:
        raise RuntimeError('引导语未返回音频')
    with wave.open(io.BytesIO(raw if raw.startswith(b'RIFF') else _wav_from_pcm(raw)), 'rb') as source:
        rate, channels, width = source.getframerate(), source.getnchannels(), source.getsampwidth()
        speech = source.readframes(source.getnframes())
    if channels != 1 or width != 2:
        raise RuntimeError('引导语格式应为单声道 16 位 PCM')
    with wave.open(str(ROOT / 'frontend/public/journey/welcome-music.wav'), 'rb') as music:
        bed = music.readframes(music.getnframes())
        if music.getnchannels() == 2:
            bed = audioop.tomono(bed, music.getsampwidth(), .5, .5)
        bed = audioop.lin2lin(bed, music.getsampwidth(), 2)
        bed, _ = audioop.ratecv(bed, 2, 1, music.getframerate(), rate, None)
    # A single mixed asset guarantees the music ends before the microphone opens.
    speech = bytes(rate) + speech + bytes(rate)
    bed = (bed * (len(speech) // len(bed) + 1))[:len(speech)]
    chunks = []
    block = rate // 10 * 2
    duration = len(speech) / (rate * 2)
    for start in range(0, len(speech), block):
        t = start / (rate * 2)
        fade = min(1, t / .5, max(0, (duration - t) / .7))
        chunks.append(audioop.add(speech[start:start + block], audioop.mul(bed[start:start + block], 2, .12 * fade), 2))
    with wave.open(str(OUTPUT), 'wb') as destination:
        destination.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        destination.writeframes(b''.join(chunks))
    print(f'Created {OUTPUT.name}: {duration:.1f}s, Serena / qwen3.5-omni-plus; music mixed at 12%.')


if __name__ == '__main__':
    asyncio.run(main())
