import asyncio
import time
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response

from server import journey_image, main, managed_asr, security


class ManagedAsrTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Only synthetic credentials are used; no local credential file is read.
        self.config = {'base_url': 'https://api.fourhz.amphion.top', 'api_key': 'test-private-key'}
        self.control = security.AccessControl()
        for target, name, value in (
            (managed_asr, 'enabled', lambda: True),
            (managed_asr, 'configuration', lambda: self.config.copy()),
            (security, 'access', self.control),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def client(self, app=main.app, host='127.0.0.1', client_host='127.0.0.1'):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(client_host, 12345)),
            base_url='http://' + host + ':8767',
        )

    async def test_config_issues_private_cookie_without_exposing_key(self):
        async with self.client() as client:
            result = await client.get('/api/config')
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()['asrManaged'])
        self.assertNotIn(self.config['api_key'], result.text)
        self.assertNotIn('api_key', result.text)
        cookie = result.headers['set-cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=strict', cookie)
        self.assertIn('Max-Age=28800', cookie)
        self.assertIn('Path=/api', cookie)
        self.assertEqual(result.headers['cache-control'], 'no-store')

    async def test_config_rejects_remote_clients_and_dns_rebinding_hosts(self):
        for host, client_host, headers in (
            ('127.0.0.1', '192.0.2.8', {}),
            ('evil.example', '127.0.0.1', {}),
            ('127.0.0.1', '127.0.0.1', {'Sec-Fetch-Site': 'cross-site'}),
        ):
            with self.subTest(host=host, client_host=client_host, headers=headers):
                async with self.client(host=host, client_host=client_host) as client:
                    result = await client.get('/api/config', headers=headers)
                self.assertEqual(result.status_code, 403)
                self.assertNotIn('set-cookie', result.headers)

    async def test_missing_forged_and_expired_cookies_cannot_mint_tokens(self):
        expired = str(int(time.time()) - 10)
        mint = AsyncMock(return_value='test-token')
        with patch.object(managed_asr, 'mint_token', mint):
            async with self.client() as client:
                for cookie in ('', '9999999999.forged', expired + '.' + managed_asr.signature(expired)):
                    with self.subTest(cookie_kind='empty' if not cookie else 'invalid'):
                        result = await client.post('/api/journey/asr-session', headers={
                            'Origin': 'http://127.0.0.1:5173',
                            'Cookie': managed_asr.COOKIE + '=' + cookie,
                        })
                        self.assertEqual(result.status_code, 401)
        mint.assert_not_awaited()

    async def test_mutation_requires_allowed_origin_even_with_a_valid_cookie(self):
        mint = AsyncMock(return_value='test-token')
        with patch.object(managed_asr, 'mint_token', mint):
            async with self.client() as client:
                await client.get('/api/config')
                for headers in (
                    {}, {'Origin': 'https://evil.example'}, {'Origin': 'null'},
                    {'Origin': 'http://127.0.0.1:9999'},
                    {'Origin': 'http://127.0.0.1:5173', 'Sec-Fetch-Site': 'cross-site'},
                ):
                    with self.subTest(headers=headers):
                        result = await client.post('/api/journey/asr-session', headers=headers)
                        self.assertEqual(result.status_code, 403)
        mint.assert_not_awaited()

    async def test_valid_browser_gets_only_temporary_websocket_credentials(self):
        mint = AsyncMock(return_value='short-token+with/slash=')
        with patch.object(managed_asr, 'mint_token', mint):
            async with self.client() as client:
                await client.get('/api/config')
                result = await client.post('/api/journey/asr-session', headers={'Origin': 'http://127.0.0.1:5173'})
        self.assertEqual(result.status_code, 200)
        url = urlsplit(result.json()['url'])
        self.assertEqual(url.scheme, 'wss')
        self.assertEqual(url.hostname, 'api.fourhz.amphion.top')
        self.assertEqual(url.path, '/v1/asr/realtime')
        self.assertEqual(parse_qs(url.query), {'speech_model': ['fourhz-spectrum'], 'token': ['short-token+with/slash=']})
        self.assertNotIn(self.config['api_key'], result.text)
        self.assertEqual(result.headers['cache-control'], 'no-store')
        self.assertEqual(self.control.active, {})

    async def test_explicit_local_demo_port_can_mint_a_session(self):
        mint = AsyncMock(return_value='test-token')
        with patch.dict('os.environ', {'JOURNEY_DEMO_PORT': '5174'}), patch.object(managed_asr, 'mint_token', mint):
            async with self.client() as client:
                await client.get('/api/config')
                allowed = await client.post('/api/journey/asr-session', headers={'Origin': 'http://127.0.0.1:5174'})
                calls_after_allowed = mint.await_count
                remote = await client.post('/api/journey/asr-session', headers={'Origin': 'https://evil.example'})
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(remote.status_code, 403)
        self.assertGreater(calls_after_allowed, 0)
        self.assertEqual(mint.await_count, calls_after_allowed)

    async def test_public_demo_accepts_only_its_https_origin(self):
        mint = AsyncMock(return_value='test-token')
        with patch.dict('os.environ', {'JOURNEY_PUBLIC_HOST': 'amphion-gjh.amphiondev.com'}), patch.object(managed_asr, 'mint_token', mint):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=main.app, client=('198.51.100.42', 12345)),
                base_url='https://amphion-gjh.amphiondev.com',
            ) as client:
                config = await client.get('/api/config')
                valid = await client.post('/api/journey/asr-session', headers={'Origin': 'https://amphion-gjh.amphiondev.com'})
                before_invalid = mint.await_count
                invalid = await client.post('/api/journey/asr-session', headers={'Origin': 'https://evil.example'})
                missing = await client.post('/api/journey/asr-session')
        self.assertEqual(config.status_code, 200)
        self.assertIn('Secure', config.headers['set-cookie'])
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(invalid.status_code, 403)
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(mint.await_count, before_invalid)

    async def test_changed_invalid_key_blocks_real_illustration_route_before_model_call(self):
        mint = AsyncMock(return_value='test-token')
        generate = AsyncMock(return_value={'image': 'test-image'})
        with patch.object(managed_asr, 'mint_token', mint), patch.object(journey_image, 'generate_sketch', generate):
            async with self.client() as client:
                await client.get('/api/config')
                request = {'headers': {'Origin': 'http://127.0.0.1:5173'}, 'json': {'summary': '我想去看海。'}}
                first = await client.post('/api/journey/illustrate', **request)
                self.assertEqual(first.status_code, 200)
                self.config['api_key'] = 'test-new-invalid-key'
                mint.side_effect = HTTPException(401, '新的 ASR 密钥无效。')
                blocked = await client.post('/api/journey/illustrate', **request)
        self.assertEqual(blocked.status_code, 401)
        generate.assert_awaited_once()
        self.assertEqual(mint.await_count, 2)
        self.assertNotIn('test-private-key', repr(self.control.valid))
        self.assertNotIn('test-new-invalid-key', repr(self.control.valid))
        self.assertEqual(self.control.active, {})

    def protected_app(self, endpoint):
        app = FastAPI()

        @app.get('/api/config')
        async def config(request: Request, response: Response):
            managed_asr.issue_cookie(request, response)
            return {'ready': True}

        app.post('/api/protected', dependencies=[Depends(security.compose_access)])(endpoint)
        return app

    async def test_managed_auth_cache_and_rate_limit_remain_effective(self):
        async def endpoint():
            return {'ok': True}

        mint = AsyncMock(return_value='test-token')
        with patch.object(managed_asr, 'mint_token', mint):
            async with self.client(app=self.protected_app(endpoint)) as client:
                await client.get('/api/config')
                responses = [await client.post('/api/protected', headers={'Origin': 'http://127.0.0.1:5173'}) for _ in range(11)]
        self.assertTrue(all(response.status_code == 200 for response in responses[:10]))
        self.assertEqual(responses[-1].status_code, 429)
        mint.assert_awaited_once()
        self.assertEqual(self.control.active, {})

    async def test_managed_generation_concurrency_is_bounded_and_released(self):
        release, started = asyncio.Event(), asyncio.Event()

        async def endpoint():
            if sum(self.control.active.values()) == 2:
                started.set()
            await release.wait()
            raise HTTPException(502, 'test generation failure')

        mint = AsyncMock(return_value='test-token')
        with patch.object(managed_asr, 'mint_token', mint):
            async with self.client(app=self.protected_app(endpoint)) as client:
                await client.get('/api/config')
                headers = {'Origin': 'http://127.0.0.1:5173'}
                tasks = [asyncio.create_task(client.post('/api/protected', headers=headers)) for _ in range(2)]
                try:
                    await asyncio.wait_for(started.wait(), 2)
                    blocked = await client.post('/api/protected', headers=headers)
                    self.assertEqual(blocked.status_code, 429)
                finally:
                    release.set()
                    await asyncio.gather(*tasks)
        self.assertEqual(self.control.active, {})

    async def token_request(self, handler):
        provider = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
        with patch.object(managed_asr.httpx, 'AsyncClient', return_value=provider) as factory:
            result = await managed_asr.mint_token()
        factory.assert_called_once_with(timeout=15, follow_redirects=False)
        return result

    async def test_token_request_uses_raw_authorization_and_never_url_credentials(self):
        seen = []

        def handler(request):
            seen.append(request)
            self.assertEqual(request.method, 'GET')
            self.assertEqual(request.headers['authorization'], self.config['api_key'])
            self.assertEqual(str(request.url), 'https://api.fourhz.amphion.top/v1/token?expires_in_seconds=60')
            self.assertNotIn('x-api-key', request.headers)
            return httpx.Response(200, json={'token': 'temporary-token'})

        self.assertEqual(await self.token_request(handler), 'temporary-token')
        self.assertEqual(len(seen), 1)

    async def test_token_failures_are_sanitized_and_redirects_are_not_followed(self):
        for status, expected in ((401, 401), (403, 401), (402, 503), (429, 429), (500, 503), (302, 503)):
            with self.subTest(status=status):
                with self.assertRaises(HTTPException) as error:
                    await self.token_request(lambda _: httpx.Response(status, text='private-provider-diagnostics', headers={'Location': 'https://evil.example'}))
                self.assertEqual(error.exception.status_code, expected)
                self.assertNotIn('private-provider-diagnostics', error.exception.detail)
                self.assertNotIn(self.config['api_key'], error.exception.detail)

    async def test_malformed_token_payloads_fail_without_raw_provider_details(self):
        for content in ('[]', 'null', '"private-provider-diagnostics"', '{}', '{"token":false}', '{"token":""}', 'not-json'):
            with self.subTest(payload=content):
                with self.assertRaises(HTTPException) as error:
                    await self.token_request(lambda _: httpx.Response(200, content=content))
                self.assertEqual(error.exception.status_code, 503)
                self.assertNotIn('private-provider-diagnostics', error.exception.detail)

    async def test_token_transport_failure_is_sanitized(self):
        def handler(_):
            raise httpx.ConnectError('private-provider-diagnostics')

        with self.assertRaises(HTTPException) as error:
            await self.token_request(handler)
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn('private-provider-diagnostics', error.exception.detail)


if __name__ == '__main__':
    unittest.main()
