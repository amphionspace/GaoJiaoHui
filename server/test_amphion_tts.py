import unittest
from unittest.mock import patch

import httpx

from server import amphion_tts


class AmphionTtsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import os
        self.env = {'JOURNEY_TTS_ORDER': 'amphion,bailian', 'AMPHION_TTS_URL': 'https://tts.example.test'}
        patcher = patch.dict('os.environ', self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        amphion_tts._cooldown_until = 0.0
        amphion_tts._ready.update(at=0.0, ok=False, model='', latency_ms=0)

    def client(self, handler):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def test_synthesis_sends_the_reference_sample_and_language(self):
        seen = {}

        def handler(request):
            seen['path'] = request.url.path
            seen['payload'] = __import__('json').loads(request.content)
            return httpx.Response(200, content=b'RIFF' + b'\x00' * 40)

        with patch.object(amphion_tts.httpx, 'AsyncClient', return_value=self.client(handler)):
            audio = await amphion_tts.synthesize('你好', b'sample-bytes', 'English')

        self.assertTrue(audio.startswith(b'RIFF'))
        self.assertEqual(seen['path'], '/tts-api/v1/audio/speech')
        self.assertTrue(seen['payload']['ref_audio'].startswith('data:audio/wav;base64,'))
        self.assertTrue(seen['payload']['x_vector_only_mode'])
        self.assertEqual(seen['payload']['language'], 'English')
        self.assertEqual(seen['payload']['response_format'], 'wav')
        self.assertFalse(amphion_tts.cooling_down())

    async def test_a_failed_synthesis_starts_a_cooldown(self):
        with patch.object(amphion_tts.httpx, 'AsyncClient',
                          return_value=self.client(lambda request: httpx.Response(503, text='busy'))):
            with self.assertRaises(amphion_tts.AmphionError):
                await amphion_tts.synthesize('你好', b'sample')
        self.assertTrue(amphion_tts.cooling_down())
        amphion_tts.note_success()

    async def test_readiness_is_cached_and_never_raises(self):
        calls = []

        def handler(request):
            calls.append(request.url.path)
            return httpx.Response(200, json={'status': 'ok', 'model': 'emilia2'})

        with patch.object(amphion_tts.httpx, 'AsyncClient', return_value=self.client(handler)):
            first = await amphion_tts.ready(force=True)
            second = await amphion_tts.ready()
        self.assertTrue(first['ok'])
        self.assertEqual(first['model'], 'emilia2')
        self.assertTrue(second['cached'])
        self.assertEqual(len(calls), 1)

    async def test_readiness_failure_is_reported(self):
        def handler(request):
            raise httpx.ConnectError('down')

        with patch.object(amphion_tts.httpx, 'AsyncClient', return_value=self.client(handler)):
            result = await amphion_tts.ready(force=True)
        self.assertFalse(result['ok'])
        self.assertFalse(result['cached'])


if __name__ == '__main__':
    unittest.main()
