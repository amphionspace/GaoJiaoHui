import base64
import json
import io
import os
import tempfile
import wave
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from starlette.requests import Request
from fastapi import HTTPException

from server import bailian_tts


CONFIG = {
    "api_key": "bailian-test-key",
    "base_url": "https://bailian.example.test",
    "compatible_base_url": "https://bailian.example.test/compatible-mode/v1",
    "target_model": "qwen3.5-omni-plus",
}


def request_for(app, body=b"", headers=None):
    header_items = [(b"x-api-key", b"client-key")]
    header_items.extend((key.lower().encode(), value.encode()) for key, value in (headers or {}).items())
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http", "method": "POST", "path": "/api/journey/tts/v1/audio/speech",
        "headers": header_items, "query_string": b"", "scheme": "http",
        "server": ("test", 80), "client": ("test", 1), "root_path": "",
        "http_version": "1.1", "app": app,
    }
    return Request(scope, receive)


class BailianTtsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.state_patch = patch.object(bailian_tts, 'STATE_FILE', Path(self.directory.name) / 'voices.sqlite3')
        self.state_patch.start()
        self.addCleanup(patch.stopall)
        patch.object(bailian_tts.security, 'access', bailian_tts.security.AccessControl()).start()
        patch.dict(os.environ, {'JOURNEY_ACCESS_KEY': ''}).start()
        self.authenticate = AsyncMock()

    def app_for(self, client):
        return SimpleNamespace(state=SimpleNamespace(bailian_client=client, authenticate_key=self.authenticate))

    def tearDown(self):
        self.state_patch.stop()
        self.directory.cleanup()

    async def test_synthesize_collects_streamed_audio_and_wraps_pcm_as_wav(self):
        encoded = base64.b64encode(b"\x00\x00\x01\x00").decode()

        def handler(request):
            payload = json.loads(request.content)
            self.assertEqual(request.url.path, "/compatible-mode/v1/chat/completions")
            self.assertEqual(payload["model"], CONFIG["target_model"])
            self.assertEqual(payload["audio"]["voice"], "journey_" + "a" * 32)
            self.assertEqual(request.headers["authorization"], "Bearer " + CONFIG["api_key"])
            event = {"choices": [{"delta": {"audio": {"data": encoded}}}]}
            events = ["data: " + json.dumps(event, ensure_ascii=False), "data: [DONE]"]
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text="\n\n".join(events))

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        app = self.app_for(client)
        body = json.dumps({"voice": "journey_" + "a" * 32, "input": "你好，未来的我。"}).encode()
        with patch.object(bailian_tts, "configuration", return_value=CONFIG), patch.object(bailian_tts, '_registered', return_value={'remote': 'journey_' + 'a' * 32, 'model': CONFIG['target_model']}):
            result = await bailian_tts.synthesize(request_for(app, body))
        await client.aclose()
        self.assertTrue(result.startswith(b"RIFF"))
        self.assertIn(b"WAVE", result[:16])

    async def test_list_voices_only_returns_owned_local_aliases(self):
        name = 'journey_' + 'b' * 32
        with bailian_tts._database() as db:
            db.execute('INSERT INTO voices VALUES (?, ?, ?, ?)', (bailian_tts._owner('client-key'), name, 'provider-generated-id', CONFIG['target_model']))
            db.execute('INSERT INTO voices VALUES (?, ?, ?, ?)', ('another-owner', 'journey_' + 'c' * 32, 'unrelated-voice', CONFIG['target_model']))
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: self.fail('No provider-wide listing needed')))
        app = self.app_for(client)
        with patch.object(bailian_tts, "configuration", return_value=CONFIG):
            result = await bailian_tts.list_voices(request_for(app))
        await client.aclose()
        self.assertEqual(result["voices"][0]["voice_name"], "journey_" + "b" * 32)
        self.assertEqual(result["voice_limit"], 1000)
        self.assertEqual(len(result['voices']), 1)

    async def test_invalid_gateway_key_rejected_before_provider_call(self):
        self.authenticate.side_effect = HTTPException(401, 'invalid key')
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: self.fail('Invalid keys must never reach the provider'))) as client:
            with self.assertRaises(HTTPException) as error:
                await bailian_tts.synthesize(request_for(self.app_for(client), b'{}'))
        self.assertEqual(error.exception.status_code, 401)
        self.authenticate.assert_awaited_once_with('client-key')

    async def test_real_multipart_route_maps_provider_voice_for_synthesis_and_cleanup(self):
        from server.main import app
        model = CONFIG['target_model']
        config = {**CONFIG, 'target_model': model}
        name = 'journey_' + 'd' * 32
        remote = 'qwen-tts-vc-journey_generated_by_provider'
        calls = []
        sample = io.BytesIO()
        with wave.open(sample, 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
            wav.writeframes(b'\x01\x00' * 16000 * 6)
        def upstream(request):
            body = json.loads(request.content)
            calls.append(body)
            operation = body.get('input', {}).get('action')
            if operation == 'create':
                self.assertLessEqual(len(body['input']['preferred_name']), 16)
                data = base64.b64decode(body['input']['audio']['data'].split(',')[1])
                with wave.open(io.BytesIO(data)) as wav:
                    self.assertEqual(wav.getframerate(), 24000)
                return httpx.Response(200, json={'output': {'voice': remote}})
            if operation == 'delete':
                self.assertEqual(body['input']['voice'], remote)
                return httpx.Response(200, json={'output': {}})
            self.assertEqual(body['audio']['voice'], remote)
            self.assertEqual(body['messages'][1]['content'], '今天这一步，已经很好。')
            self.assertEqual(body['model'], model)
            self.assertIn('/chat/completions', str(request.url))
            event = {'choices': [{'delta': {'audio': {'data': base64.b64encode(b'\x01\x00' * 2400).decode()}}}]}
            return httpx.Response(200, text='data: ' + json.dumps(event) + '\n\ndata: [DONE]\n\n')
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as provider, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            with patch.object(bailian_tts, 'enabled', return_value=True), patch.object(bailian_tts, 'configuration', return_value=config), patch.object(app.state, 'bailian_client', provider), patch.object(app.state, 'authenticate_key', self.authenticate):
                headers = {'X-API-Key': 'client-key'}
                url = '/api/journey/tts/v1/audio/'
                result = await client.post(url + 'voices', headers=headers, data={'voice_name': name}, files={'audio_file': ('sample.wav', sample.getvalue(), 'audio/wav')})
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()['voice']['voice_name'], name)
                hidden = await client.post(url + 'speech', headers={'X-API-Key': 'another-key'}, json={'voice': name, 'input': '不能使用他人音色'})
                self.assertEqual(hidden.status_code, 404)
                result = await client.post(url + 'speech', headers=headers, json={'voice': name, 'input': '今天这一步，已经很好。'})
                self.assertEqual(result.status_code, 200, result.text[:100])
                self.assertTrue(result.content.startswith(b'RIFF'))
                result = await client.delete(url + 'voices/' + name, headers=headers)
                self.assertEqual(result.status_code, 200)
                self.assertIsNone(bailian_tts._registered('client-key', name))
                result = await client.post(url + 'voices', headers=headers, data={'voice_name': name}, files={'audio_file': ('bad.wav', b'invalid', 'audio/wav')})
                self.assertEqual(result.status_code, 400)
        self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
