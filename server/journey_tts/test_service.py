import asyncio
import io
import unittest
import wave

import httpx
import numpy as np

from service import create_app

NAME = 'journey_' + 'a' * 32


def sample(silent=False):
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        audio = np.zeros(96000) if silent else np.sin(np.arange(96000) / 10) * 4000
        wav.writeframes(audio.astype('<i2').tobytes())
    return output.getvalue()


class Engine:
    def __init__(self):
        self.prepared = []
        self.spoken = []

    def prepare(self, audio, rate, transcript):
        prompt = {'transcript': transcript, 'samples': len(audio), 'rate': rate}
        self.prepared.append(prompt)
        return prompt

    def synthesize(self, prompt, text):
        self.spoken.append((prompt, text))
        return b'RIFF-test-audio'


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = Engine()
        self.asr_count = 0
        self.fail_asr = False

        def upstream(request):
            if request.url.path.endswith('/voices'):
                return httpx.Response(200 if request.headers.get('X-API-Key') in ('first', 'second') else 401, json={})
            self.asr_count += 1
            return httpx.Response(503 if self.fail_asr else 200, json={'text': '这段参考录音的准确转写。'})

        self.app = create_app(lambda: self.engine, httpx.MockTransport(upstream))
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)

    async def register(self, raw=None, key='first'):
        return await self.client.post('/v1/audio/voices', headers={'X-API-Key': key},
                                      data={'voice_name': NAME}, files={'audio_file': ('sample.wav', raw or sample())})

    async def speak(self, key='first'):
        return await self.client.post('/v1/audio/speech', headers={'X-API-Key': key},
                                      json={'voice': NAME, 'input': '把这个小想法记下来，再向前走一步。'})

    async def test_authentication_and_voice_ownership(self):
        self.assertEqual((await self.register(key='invalid')).status_code, 401)
        self.assertEqual(self.asr_count, 0)
        self.assertEqual((await self.register()).status_code, 200)
        self.assertEqual((await self.speak('second')).status_code, 404)
        other_list = await self.client.get('/v1/audio/voices', headers={'X-API-Key': 'second'})
        self.assertEqual(other_list.json()['voices'], [])
        self.assertEqual((await self.client.delete('/v1/audio/voices/' + NAME, headers={'X-API-Key': 'second'})).status_code, 404)
        spoken = await self.speak()
        self.assertEqual(spoken.status_code, 200)
        self.assertEqual(spoken.headers['content-type'], 'audio/wav')
        self.assertEqual(self.engine.prepared[0]['transcript'], '这段参考录音的准确转写。')
        self.assertIs(self.engine.spoken[0][0], self.engine.prepared[0])
        self.assertEqual((await self.client.delete('/v1/audio/voices/' + NAME, headers={'X-API-Key': 'first'})).status_code, 200)
        self.assertEqual((await self.speak()).status_code, 404)

    async def test_bad_and_silent_audio_never_reach_asr_or_model(self):
        for raw in (b'not-wav', sample(silent=True), b'x' * (2 * 1024 * 1024 + 1)):
            self.assertIn((await self.register(raw)).status_code, (400, 413))
        self.assertEqual(self.asr_count, 0)
        self.assertEqual(self.engine.prepared, [])

    async def test_failed_asr_releases_reservation_for_retry(self):
        self.fail_asr = True
        self.assertEqual((await self.register()).status_code, 503)
        self.fail_asr = False
        self.assertEqual((await self.register()).status_code, 200)
        self.assertEqual((await self.register()).status_code, 409)

    async def test_expired_prompt_cannot_be_synthesized(self):
        from unittest.mock import patch
        self.assertEqual((await self.register()).status_code, 200)
        import time
        now = time.monotonic()
        with patch('service.time.monotonic', return_value=now + 1801):
            self.assertEqual((await self.speak()).status_code, 404)
        self.assertEqual(self.engine.spoken, [])


if __name__ == '__main__':
    unittest.main()
