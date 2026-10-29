import base64
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from server import journey_image


class JourneyImageTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
        config = {'compatible_base_url': 'https://api.example.test/v1', 'api_key': 'test-only'}
        with patch.object(journey_image, 'configuration', return_value=config), patch.object(journey_image.httpx, 'AsyncClient', return_value=client):
            return await journey_image.generate_sketch('2036年，我想让机器人陪爸妈散步。')

    async def test_private_image_fetched_without_forwarding_credentials(self):
        raw = b'\x89PNG\r\n\x1a\nexample'
        calls = []
        def handler(request):
            calls.append(request)
            if request.method == 'POST':
                self.assertEqual(request.headers['authorization'], 'Bearer test-only')
                self.assertEqual(json.loads(request.content)['size'], '1024x1024')
                self.assertIn('保留大量', json.loads(request.content)['prompt'])
                self.assertIn('soft gouache', json.loads(request.content)['prompt'])
                self.assertIn('机器人陪爸妈散步', json.loads(request.content)['prompt'])
                self.assertIn('彩色极简叙事插画', json.loads(request.content)['prompt'])
                self.assertIn('低饱和', json.loads(request.content)['prompt'])
                self.assertIn('纸张拼贴感', json.loads(request.content)['prompt'])
                self.assertIn('明确的彩色色块', json.loads(request.content)['prompt'])
                self.assertIn('像素风', json.loads(request.content)['prompt'])
                self.assertIn('黑白钢笔线稿', json.loads(request.content)['prompt'])
                self.assertIn('完整便签', json.loads(request.content)['prompt'])
                self.assertNotIn('固定风格：简约漫画风格', json.loads(request.content)['prompt'])
                return httpx.Response(200, json={'data': [{'url': 'https://image.oss-cn-beijing.aliyuncs.com/test.png'}]})
            self.assertNotIn('authorization', request.headers)
            return httpx.Response(200, content=raw)
        result = await self.invoke(handler)
        self.assertEqual(base64.b64decode(result['image'].split(',')[1]), raw)
        self.assertEqual(len(calls), 2)
        self.assertNotIn('test-only', str(result))

    async def test_unknown_hosts_or_redirects_cannot_fetch_arbitrary_urls(self):
        for url in ['http://127.0.0.1/a', 'https://localhost/a', 'https://aliyuncs.com.evil.test/a', 'https://user:pass@image.aliyuncs.com/a']:
            calls = []
            def handler(request):
                calls.append(request)
                return httpx.Response(200, json={'data': [{'url': url}]})
            with self.assertRaises(HTTPException):
                await self.invoke(handler)
            self.assertEqual(len(calls), 1)
        def redirect(request):
            if request.method == 'POST':
                return httpx.Response(200, json={'data': [{'url': 'https://image.aliyuncs.com/a'}]})
            return httpx.Response(302, headers={'Location': 'http://127.0.0.1/private'})
        with self.assertRaises(HTTPException):
            await self.invoke(redirect)

    async def test_provider_failure_does_not_leak_raw_error_or_return_a_placeholder(self):
        with self.assertRaises(HTTPException) as error:
            await self.invoke(lambda _: httpx.Response(401, text='test-only secret upstream diagnostics'))
        self.assertEqual(error.exception.status_code, 502)
        self.assertNotIn('test-only', str(error.exception.detail))

    async def test_download_limits_and_invalid_content(self):
        for raw in [b'<html>not an image</html>', b'\x89PNG\r\n\x1a\n' + b'x' * 100]:
            def handler(request):
                if request.method == 'POST':
                    return httpx.Response(200, json={'data': [{'url': 'https://image.aliyuncs.com/a'}]})
                return httpx.Response(200, content=raw)
            with patch.object(journey_image, 'MAX_IMAGE_BYTES', 64), self.assertRaises(HTTPException):
                await self.invoke(handler)

    async def test_quota_failure_reports_actionable_reason_without_provider_details(self):
        with self.assertRaises(HTTPException) as error:
            await self.invoke(lambda _: httpx.Response(403, json={'error': {'code': 'insufficient_quota', 'message': 'private account details'}}))
        self.assertEqual(error.exception.status_code, 503)
        self.assertIn('额度不足', error.exception.detail)
        self.assertNotIn('private', error.exception.detail)

    async def test_timeout_is_recoverable(self):
        def handler(request):
            raise httpx.ReadTimeout('private upstream details')
        with self.assertRaises(HTTPException) as error:
            await self.invoke(handler)
        self.assertEqual(error.exception.status_code, 504)


if __name__ == '__main__':
    unittest.main()
