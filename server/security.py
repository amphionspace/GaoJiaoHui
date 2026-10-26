"""Bounded access to server-funded generation; never retain raw client keys."""
import asyncio
import hashlib
import hmac
import os
import time
from collections import OrderedDict, deque
from fastapi import HTTPException, Request


class AccessControl:
    def __init__(self):
        self.valid = OrderedDict()
        self.windows = OrderedDict()
        self.active = {}
        self.auth_slots = asyncio.Semaphore(8)

    def consume(self, bucket, limit, seconds=60):
        now = time.monotonic()
        entries = self.windows.setdefault(bucket, deque())
        self.windows.move_to_end(bucket)
        while entries and entries[0] <= now - seconds:
            entries.popleft()
        if len(entries) >= limit:
            raise HTTPException(429, '请求较多，请稍后重试。', headers={'Retry-After': str(seconds)})
        entries.append(now)
        while len(self.windows) > 2048:
            self.windows.popitem(last=False)

    async def authorize(self, request):
        self.consume('ip:' + (request.client.host if request.client else 'unknown'), 30)
        key = request.headers.get('x-api-key', '').strip()
        if not key or len(key) > 512:
            raise HTTPException(401, '请先填写有效的语音网关密钥。')
        identity = hashlib.sha256(key.encode()).hexdigest()
        expected = os.environ.get('JOURNEY_ACCESS_KEY', '').strip()
        if expected:
            if not hmac.compare_digest(key.encode(), expected.encode()):
                raise HTTPException(401, '访问密钥无效。')
        elif self.valid.get(identity, 0) <= time.monotonic():
            if self.auth_slots.locked():
                raise HTTPException(503, '连接校验繁忙，请稍后重试。')
            async with self.auth_slots:
                await request.app.state.authenticate_key(key)
            self.valid[identity] = time.monotonic() + 60
            self.valid.move_to_end(identity)
            while len(self.valid) > 512:
                self.valid.popitem(last=False)
        self.consume('key:' + identity, 10)
        return identity


access = AccessControl()


async def compose_access(request: Request):
    identity = await access.authorize(request)
    if access.active.get(identity, 0) >= 2 or sum(access.active.values()) >= 8:
        raise HTTPException(429, '回信正在生成，请稍后再试。', headers={'Retry-After': '10'})
    access.active[identity] = access.active.get(identity, 0) + 1
    try:
        yield
    finally:
        access.active[identity] -= 1
        if not access.active[identity]:
            del access.active[identity]


class RequestLimits:
    """Reject oversize/chunked uploads before Starlette buffers or parses them."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in ('POST', 'PUT', 'PATCH'):
            return await self.app(scope, receive, send)
        path = scope['path']
        limit = 64 * 1024 if path in ('/api/journey/compose', '/api/journey/illustrate') else 2 * 1024 * 1024 if path.startswith('/api/journey/tts/') else 20 * 1024 * 1024
        messages, size = [], 0
        deadline = time.monotonic() + 30
        try:
            while True:
                message = await asyncio.wait_for(receive(), timeout=max(0.01, deadline - time.monotonic()))
                if message['type'] == 'http.disconnect':
                    return
                size += len(message.get('body', b''))
                if size > limit:
                    await self.error(send, 413, b'{"detail":"Request body too large"}')
                    return
                messages.append(message)
                if not message.get('more_body', False):
                    break
        except asyncio.TimeoutError:
            await self.error(send, 408, b'{"detail":"Upload timed out"}')
            return
        async def buffered():
            return messages.pop(0) if messages else await receive()
        await self.app(scope, buffered, send)

    @staticmethod
    async def error(send, status, body):
        await send({'type': 'http.response.start', 'status': status, 'headers': [(b'content-type', b'application/json')]})
        await send({'type': 'http.response.body', 'body': body})
