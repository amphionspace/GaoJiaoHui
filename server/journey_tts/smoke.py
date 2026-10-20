"""Manual end-to-end check using Qwen's public reference sample, not user audio."""
import argparse
import getpass
import io
import json
from pathlib import Path
import time
import uuid

import httpx
import librosa
import soundfile as sf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:18970')
    args = parser.parse_args()
    key = getpass.getpass('Gateway API key: ')
    name = 'journey_' + uuid.uuid4().hex
    output = Path(__file__).parent / 'smoke-output'
    output.mkdir(exist_ok=True)
    with httpx.Client(timeout=240, trust_env=False) as client:
        reference = client.get('https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen3-TTS-Repo/clone.wav')
        reference.raise_for_status()
        audio, rate = sf.read(io.BytesIO(reference.content), dtype='float32')
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        audio = librosa.resample(audio, orig_sr=rate, target_sr=16000)[:15 * 16000]
        raw = io.BytesIO()
        sf.write(raw, audio, 16000, format='WAV', subtype='PCM_16')
        headers = {'X-API-Key': key}
        start = time.monotonic()
        registered = client.post(args.base + '/v1/audio/voices', headers=headers,
                                 data={'voice_name': name}, files={'audio_file': ('public-reference.wav', raw.getvalue(), 'audio/wav')})
        print('registration', registered.status_code, round(time.monotonic() - start, 2), registered.text, flush=True)
        registered.raise_for_status()
        try:
            for index, text in enumerate([
                '我是未来的你。今天这个小小的想法，值得被认真听见。',
                '你说想陪爸爸整理旧照片，却担心工作一忙又会拖下去。我听见了这份惦记。先不用给自己安排一个很大的计划，这周挑一张照片，问问他那天发生了什么，就已经开始了。即使只聊十分钟，也是真正留给彼此的时间。慢慢来，你愿意靠近的这一步，本身就很珍贵。',
            ]):
                start = time.monotonic()
                result = client.post(args.base + '/v1/audio/speech', headers=headers, json={'voice': name, 'input': text})
                elapsed = time.monotonic() - start
                if result.status_code != 200:
                    print('synthesis error', result.status_code, result.text, flush=True)
                result.raise_for_status()
                samples, rate = sf.read(io.BytesIO(result.content))
                (output / f'generated-{index}.wav').write_bytes(result.content)
                print(json.dumps({'case': index, 'seconds_to_generate': round(elapsed, 2),
                                  'audio_seconds': round(len(samples) / rate, 2), 'sample_rate': rate,
                                  'bytes': len(result.content)}, ensure_ascii=False), flush=True)
                check = client.post('http://172.16.0.4:8010/v1/audio/transcriptions',
                                    data={'model': '/data/models/Qwen3-ASR-1.7B', 'response_format': 'json'},
                                    files={'file': ('generated.wav', result.content, 'audio/wav')})
                print('generated_audio_asr', check.status_code, check.text, flush=True)
        finally:
            deleted = client.delete(args.base + '/v1/audio/voices/' + name, headers=headers)
            print('cleanup', deleted.status_code, flush=True)


if __name__ == '__main__':
    main()
