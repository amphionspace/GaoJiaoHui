import json
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from server import journey_text

RAW = "我想让爸爸搬东西省些力。"
NOTE = {
    "note_text": "我想让爸爸搬东西省些力。希望这张桌子能让他轻松一点。",
    "message": "你想让爸爸少弯一点腰，这份心意值得留下。",
    "takeaway": "你想让爸爸少弯一点腰，这份心意值得留下。",
    "keywords": ["爸爸", "搬东西"],
    "anchors": ["我想让爸爸搬东西省些力"],
    "sketch_prompt": "客厅里，一个人扶着木桌，爸爸坐在旁边休息。",
}
PRIMARY = {"url": "https://primary.test/chat", "model": "primary-model", "api_key": "k1"}
FALLBACK = {"url": "https://fallback.test/chat", "model": "fallback-model", "api_key": "k2"}


def reply(note=NOTE):
    return {"choices": [{"message": {"content": json.dumps(note, ensure_ascii=False)}}]}


class TextFailoverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = patch.dict('os.environ', {'JOURNEY_SESSION_LOG': '0'})
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_balance_error_falls_back_to_the_second_provider(self):
        calls = []

        def handler(request):
            calls.append(str(request.url.host))
            if request.url.host == 'primary.test':
                return httpx.Response(402, json={'error': {'message': 'Insufficient Balance'}})
            return httpx.Response(200, json=reply())

        clients = [httpx.AsyncClient(transport=httpx.MockTransport(handler)) for _ in range(2)]
        request = journey_text.ComposeRequest(transcript=RAW, topic='idea')
        before = journey_text.metrics.events.get('text_failover', 0)
        with patch.object(journey_text, 'fallback_configuration', return_value=FALLBACK), \
             patch.object(journey_text.httpx, 'AsyncClient', side_effect=clients):
            events = []
            async for kind, note, config, session_id in journey_text.compose_notes(request, PRIMARY):
                events.append((kind, config['model']))
        self.assertEqual(events, [('draft', 'fallback-model'), ('final', 'fallback-model')])
        self.assertEqual(calls, ['primary.test', 'fallback.test', 'fallback.test'])
        self.assertEqual(journey_text.metrics.events.get('text_failover', 0), before + 1)

    async def test_balance_error_without_fallback_is_explicit(self):
        def handler(request):
            return httpx.Response(402, json={'error': {'message': 'Insufficient Balance'}})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        request = journey_text.ComposeRequest(transcript=RAW, topic='idea')
        with patch.object(journey_text, 'fallback_configuration', return_value=None), \
             patch.object(journey_text.httpx, 'AsyncClient', return_value=client):
            with self.assertRaises(HTTPException) as caught:
                async for _ in journey_text.compose_notes(request, PRIMARY):
                    pass
        self.assertEqual(caught.exception.detail['code'], 'text_balance')
        self.assertIn('额度不足', caught.exception.detail['message'])
        self.assertEqual(caught.exception.detail['upstream_status'], 402)

    async def test_fallback_defaults_to_bailian_qwen_flash(self):
        with patch.dict('os.environ', {'JOURNEY_LLM_FALLBACK_URL': '', 'JOURNEY_LLM_FALLBACK_MODEL': ''}), \
             patch('server.bailian_tts.configuration',
                   return_value={'compatible_base_url': 'https://bailian.test/compatible-mode/v1', 'api_key': 'key'}):
            config = journey_text.fallback_configuration()
        self.assertEqual(config['url'], 'https://bailian.test/compatible-mode/v1/chat/completions')
        self.assertEqual(config['model'], 'qwen-flash')
        self.assertEqual(config['api_key'], 'key')


if __name__ == '__main__':
    unittest.main()
