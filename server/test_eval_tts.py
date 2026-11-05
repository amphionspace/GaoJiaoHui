import os
import unittest
from unittest.mock import patch

import httpx

from server import eval_tts


def wav_bytes():
    frames = 1600
    return (b'RIFF' + (36 + frames * 2).to_bytes(4, 'little') + b'WAVEfmt ' +
            (16).to_bytes(4, 'little') + b'\x01\x00\x01\x00' +
            (24000).to_bytes(4, 'little') + (48000).to_bytes(4, 'little') +
            b'\x02\x00\x10\x00data' + (frames * 2).to_bytes(4, 'little') + b'\x00' * (frames * 2))


class EvalTtsTests(unittest.IsolatedAsyncioTestCase):
    async def test_clone_multipart_and_model_name(self):
        calls = []

        def handler(request: httpx.Request):
            calls.append(request)
            return httpx.Response(200, content=wav_bytes(), request=request)

        transport = httpx.MockTransport(handler)
        real = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs['transport'] = transport
            return real(*args, **kwargs)

        with patch.dict(os.environ, {'EVAL_TTS_API_KEY': 'eval-key', 'EVAL_TTS_BASE_URL': 'https://eval.test', 'EVAL_TTS_RETRIES': '0'}), \
             patch.object(eval_tts.httpx, 'AsyncClient', factory):
            audio = await eval_tts.synthesize('voxcpm2', '你好', wav_bytes(), '参考原文', 'Chinese')
        self.assertTrue(audio.startswith(b'RIFF'))
        self.assertEqual(calls[0].url.path, '/tts-eval/speech/voxcpm2')
        self.assertEqual(calls[0].headers['authorization'], 'Bearer eval-key')
        body = calls[0].content
        self.assertIn(b'name="mode"', body)
        self.assertIn(b'clone', body)
        self.assertIn(b'name="reference_text"', body)
        self.assertIn('参考原文'.encode(), body)
        self.assertIn(b'filename="reference.wav"', body)

    async def test_firered_language_and_busy_retry(self):
        calls = []

        def handler(request: httpx.Request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(429, headers={'retry-after': '0.01'}, json={'detail': 'busy'}, request=request)
            return httpx.Response(200, content=wav_bytes(), request=request)

        transport = httpx.MockTransport(handler)
        real = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs['transport'] = transport
            return real(*args, **kwargs)

        with patch.dict(os.environ, {'EVAL_TTS_API_KEY': 'eval-key', 'EVAL_TTS_BASE_URL': 'https://eval.test', 'EVAL_TTS_RETRIES': '1'}), \
             patch.object(eval_tts.httpx, 'AsyncClient', factory):
            audio = await eval_tts.synthesize('fireredtts3', '你好', wav_bytes(), '参考原文', 'Chinese')
        self.assertTrue(audio.startswith(b'RIFF'))
        self.assertEqual(len(calls), 2)
        self.assertIn(b'name="language"', calls[-1].content)
        self.assertIn(b'Chinese', calls[-1].content)

    def test_missing_configuration(self):
        with patch.dict(os.environ, {'EVAL_TTS_API_KEY': ''}):
            self.assertFalse(eval_tts.enabled())
            with self.assertRaises(eval_tts.EvalTTSError):
                eval_tts.configuration()
