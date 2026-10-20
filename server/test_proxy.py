import ssl
import unittest
from unittest.mock import AsyncMock, patch

import httpcore
import httpx

from server import main


class GatewayStream(httpcore.AsyncNetworkStream):
    def __init__(self):
        self.writes = []
        self.tls = None
        self.response = b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}'

    async def read(self, max_bytes, timeout=None):
        response, self.response = self.response, b''
        return response

    async def write(self, buffer, timeout=None):
        self.writes.append(buffer)

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.tls = (ssl_context, server_hostname)
        return self

    async def aclose(self):
        pass


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_journey_routes_to_dedicated_worker_without_changing_other_tts(self):
        seen = []

        def respond(request):
            seen.append(request)
            return httpx.Response(200, json={'ready': True})

        with patch.object(main, 'LegacyGatewayTransport', return_value=httpx.MockTransport(respond)):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://local.test') as client:
                await client.get('/api/journey/tts/v1/audio/voices', headers={'X-API-Key': 'test-only'})
                await client.get('/proxy/tts/v1/audio/voices')
                denied = await client.delete('/api/journey/tts/v1/audio/voices/saved_voice')
                oversized = await client.post('/api/journey/tts/v1/audio/voices', content=b'x' * (2 * 1024 * 1024 + 1))
        self.assertEqual(str(seen[0].url), 'https://amphion.top/journey-tts/v1/audio/voices')
        self.assertEqual(seen[0].headers['X-API-Key'], 'test-only')
        self.assertEqual(str(seen[1].url), 'https://amphion.top/tts/v1/audio/voices')
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(oversized.status_code, 413)

    async def test_pinned_ip_retains_hostname_and_certificate_verification(self):
        stream = GatewayStream()
        connect = AsyncMock(return_value=stream)
        with patch.object(main.AnyIOBackend, 'connect_tcp', connect):
            async with httpx.AsyncClient(transport=main.LegacyGatewayTransport('192.0.2.10')) as client:
                result = await client.post(
                    'https://amphion.top/tts/v1/audio/speech?format=wav',
                    headers={'X-API-Key': 'test-only'},
                    json={'voice': 'journey_test', 'input': 'hello'},
                )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(connect.call_args.args[:2], ('192.0.2.10', 443))
        context, hostname = stream.tls
        self.assertEqual(hostname, 'amphion.top')
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        sent = b''.join(stream.writes)
        self.assertIn(b'POST /tts/v1/audio/speech?format=wav HTTP/1.1', sent)
        self.assertIn(b'Host: amphion.top', sent)
        self.assertIn(b'X-API-Key: test-only', sent)
        self.assertIn(b'"voice":"journey_test"', sent)

    async def test_proxy_honors_explicit_ip_override_and_preserves_query(self):
        seen = []

        def respond(request):
            seen.append(request)
            return httpx.Response(401, json={'detail': 'test auth response'})

        with patch.object(main, 'UPSTREAM_IP', '192.0.2.20'), patch.object(
            main, 'LegacyGatewayTransport', return_value=httpx.MockTransport(respond)
        ) as transport:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://local.test') as client:
                result = await client.get('/proxy/tts/v1/audio/voices?limit=10')
        transport.assert_called_once_with('192.0.2.20')
        self.assertEqual(str(seen[0].url), 'https://amphion.top/tts/v1/audio/voices?limit=10')
        self.assertEqual(result.status_code, 401)


if __name__ == '__main__':
    unittest.main()
