import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import FastAPI, Depends, HTTPException
from server import main, security


class SecurityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.control = security.AccessControl()
        self.patch = patch.object(security, 'access', self.control)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    async def test_real_compose_rejects_missing_key_before_model_call(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            response = await client.post('/api/journey/compose', json={'topic': 'story', 'transcript': '我的故事'})
        self.assertEqual(response.status_code, 401)

    async def test_limits_and_cache_are_applied_without_storing_raw_keys(self):
        app = FastAPI()
        app.state.authenticate_key = AsyncMock()
        @app.post('/compose', dependencies=[Depends(security.compose_access)])
        async def endpoint():
            return {'ok': True}
        with patch.dict(os.environ, {'JOURNEY_ACCESS_KEY': ''}):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                results = [await client.post('/compose', headers={'X-API-Key': 'test-only'}) for _ in range(11)]
        self.assertTrue(all(r.status_code == 200 for r in results[:10]))
        self.assertEqual(results[-1].status_code, 429)
        app.state.authenticate_key.assert_awaited_once()
        self.assertNotIn('test-only', repr(self.control.valid))
        self.assertEqual(self.control.active, {})

    async def test_invalid_key_never_reaches_handler(self):
        app = FastAPI()
        app.state.authenticate_key = AsyncMock(side_effect=HTTPException(401, 'invalid'))
        reached = []
        @app.post('/compose', dependencies=[Depends(security.compose_access)])
        async def endpoint():
            reached.append(True)
        with patch.dict(os.environ, {'JOURNEY_ACCESS_KEY': ''}):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                response = await client.post('/compose', headers={'X-API-Key': 'invalid'})
        self.assertEqual(response.status_code, 401)
        self.assertFalse(reached)

    async def test_concurrent_limit_releases_slots_after_errors(self):
        app = FastAPI()
        app.state.authenticate_key = AsyncMock()
        release, started = asyncio.Event(), asyncio.Event()
        @app.post('/compose', dependencies=[Depends(security.compose_access)])
        async def endpoint():
            if sum(self.control.active.values()) == 2:
                started.set()
            await release.wait()
            raise HTTPException(502, 'test failure')
        with patch.dict(os.environ, {'JOURNEY_ACCESS_KEY': 'test-only'}):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'X-API-Key': 'test-only'}) as client:
                jobs = [asyncio.create_task(client.post('/compose')) for _ in range(2)]
                await asyncio.wait_for(started.wait(), 2)
                blocked = await client.post('/compose')
                self.assertEqual(blocked.status_code, 429)
                release.set()
                await asyncio.gather(*jobs)
        self.assertEqual(self.control.active, {})

    async def test_chunked_body_limit_precedes_json_parsing(self):
        async def chunks():
            yield b'x' * 40000
            yield b'x' * 40000
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            response = await client.post('/api/journey/compose', content=chunks())
            config = await client.get('/api/config')
        self.assertEqual(response.status_code, 413)
        self.assertEqual(config.headers['cache-control'], 'no-store')
        self.assertNotIn('api_key', config.text)


if __name__ == '__main__':
    unittest.main()
