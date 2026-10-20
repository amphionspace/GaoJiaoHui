#!/usr/bin/env python3
"""Amphion Demo 后端（FastAPI，前后端分离版）。

职责：
  1. 静态托管 frontend/dist（Vite 构建产物），单端口即可运行
  2. /proxy/* 反向代理到 https://amphion.top/*（网关未开 CORS，
     浏览器的 HTTP 请求经本代理同源转发；WS 由浏览器直连公网，不受 CORS 限制）

用法：
  生产（单端口 8766）：
    cd frontend && npm install && npm run build
    pip install fastapi uvicorn httpx
    python3 server/main.py            # http://localhost:8766/  （默认经本机 DNS 走 amphion.top）
    # 应急（本机代理 Fake-IP 故障时）：UPSTREAM_IP=106.52.52.196 python3 server/main.py
  开发（前端热更新）：
    python3 server/main.py            # 后端 8766
    cd frontend && npm run dev        # Vite 5173，/proxy 自动转发到 8766
"""
import os
import typing
import logging
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import httpcore
from httpcore._backends.anyio import AnyIOBackend
from fastapi import FastAPI, Request, Response, HTTPException
from starlette.datastructures import UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
try:
    from .journey_text import router as journey_text_router
    from .security import RequestLimits
    from . import bailian_tts
except ImportError:
    from journey_text import router as journey_text_router
    from security import RequestLimits
    import bailian_tts

UPSTREAM = os.environ.get('GATEWAY_URL', 'https://amphion.top').rstrip('/')
UPSTREAM_HOST = urlsplit(UPSTREAM).hostname
JOURNEY_TTS_URL = os.environ.get('JOURNEY_TTS_URL', UPSTREAM + '/journey-tts').rstrip('/')
ASR_WS_URL = os.environ.get('ASR_WS_URL', UPSTREAM.replace('https://', 'wss://').replace('http://', 'ws://'))
ASR_REALTIME_WS_URL = os.environ.get('ASR_REALTIME_WS_URL', 'wss://amphion-gjh.amphiondev.com/ws-legacy')
for name, value, schemes in (
    ('GATEWAY_URL', UPSTREAM, ('https', 'http')),
    ('JOURNEY_TTS_URL', JOURNEY_TTS_URL, ('https', 'http')),
    ('ASR_WS_URL', ASR_WS_URL, ('wss', 'ws')),
    ('ASR_REALTIME_WS_URL', ASR_REALTIME_WS_URL, ('wss', 'ws')),
):
    parsed = urlsplit(value)
    if parsed.scheme not in schemes or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError(name + ' must be an endpoint without credentials or query parameters')
# 应急开关：本机代理（Surge/Clash 增强模式 Fake-IP 198.18.x.x）链路故障时，
# 设 UPSTREAM_IP=106.52.52.196 可绕过本机 DNS 直连上游真实 IP（Host/SNI 仍用域名，证书校验不变）
UPSTREAM_IP = os.environ.get("UPSTREAM_IP", "").strip()
# cn-test 迁移期（2026-10-09 发现）：amphion.top DNS 已切国内新集群，/tts/v1/* 路由未迁移
# （返回 route_not_migrated），仍存活在 legacy 网关 106.52.52.196（Host/SNI 仍用 amphion.top）。
# /proxy 对 tts/* 路径自动分流到 legacy；其余（ASR WS 认证 / 声纹档案）走 DNS 新集群。
LEGACY_TTS_IP = os.environ.get("LEGACY_TTS_IP", "106.52.52.196").strip()
PORT = int(os.environ.get("PORT", "8766"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = (Path(ROOT) / 'VERSION').read_text(encoding='utf-8').strip()
DIST = os.path.join(ROOT, "frontend", "dist")
HOP_HEADERS = {"host", "connection", "content-length", "transfer-encoding",
               "accept-encoding", "origin", "referer", "user-agent"}


class LegacyGatewayBackend(AnyIOBackend):
    """Connect to the legacy IP while keeping TLS verification on the hostname."""

    def __init__(self, connect_ip: str):
        self.connect_ip = connect_ip

    async def connect_tcp(
        self, host: str, port: int, timeout: typing.Optional[float] = None,
        local_address: typing.Optional[str] = None,
        socket_options: typing.Optional[typing.Iterable[typing.Any]] = None,
    ):
        target = self.connect_ip if host == UPSTREAM_HOST else host
        return await super().connect_tcp(target, port, timeout, local_address, socket_options)


class LegacyGatewayTransport(httpx.AsyncBaseTransport):
    def __init__(self, connect_ip: str):
        self.pool = httpcore.AsyncConnectionPool(network_backend=LegacyGatewayBackend(connect_ip))

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        core_request = httpcore.Request(
            method=request.method,
            url=str(request.url),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        response = await self.pool.handle_async_request(core_request)
        try:
            content = await response.aread()
        finally:
            await response.aclose()
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            content=content,
            extensions=response.extensions,
            request=request,
        )

    async def aclose(self):
        await self.pool.aclose()

app = FastAPI(title="Amphion Voice Booth")
app.add_middleware(RequestLimits)
app.include_router(journey_text_router)
app.state.bailian_client = httpx.AsyncClient(timeout=300, trust_env=False)


async def authenticate_key(key):
    transport = LegacyGatewayTransport(UPSTREAM_IP) if UPSTREAM_IP else None
    try:
        async with httpx.AsyncClient(timeout=8, transport=transport) as client:
            response = await client.post(UPSTREAM + '/auth/v1/ephemeral-tokens',
                headers={'X-API-Key': key}, json={'resource': 'asr.target_dialogue', 'expires_in_seconds': 60, 'max_session_seconds': 60})
        if response.status_code in (401, 403):
            raise HTTPException(401, '语音网关密钥无效，请检查设置。')
        if response.status_code != 200 or not response.json().get('access_token'):
            raise HTTPException(503, '访问校验服务暂时不可用，讲述已保留。')
    except (httpx.RequestError, ValueError):
        raise HTTPException(503, '无法校验访问密钥，请稍后重试。')


app.state.authenticate_key = authenticate_key


@app.middleware('http')
async def response_headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Request-ID'] = uuid.uuid4().hex
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    if request.url.path.startswith(('/api/', '/proxy/')):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.api_route("/proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(path: str, request: Request):
    use_ip = UPSTREAM_IP or (LEGACY_TTS_IP if path.startswith(("tts/", "journey-tts/", "asr/health")) else "")
    target = f"{UPSTREAM}/{path}"
    if path.startswith('journey-tts/'):
        target = JOURNEY_TTS_URL + '/' + path[len('journey-tts/'):]
        if urlsplit(target).hostname != UPSTREAM_HOST:
            use_ip = ''
    if request.url.query:
        target += "?" + request.url.query
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}
    body = await request.body()
    transport = LegacyGatewayTransport(use_ip) if use_ip else None
    async with httpx.AsyncClient(timeout=300, transport=transport) as client:
        try:
            r = await client.request(request.method, target, headers=headers,
                                     content=body or None)
        except Exception as e:
            logging.getLogger('gateway').warning('upstream_failure type=%s', type(e).__name__)
            return JSONResponse({"detail": "语音服务连接失败，请稍后重试。"}, status_code=504 if isinstance(e, httpx.TimeoutException) else 502)
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("Content-Type", "application/octet-stream"))


@app.api_route("/api/journey/tts/{path:path}", methods=["GET", "POST", "DELETE"])
async def journey_tts(path: str, request: Request):
    if bailian_tts.enabled():
        if request.method == "GET" and path == "v1/audio/voices":
            return await bailian_tts.list_voices(request)
        if request.method == "POST" and path == "v1/audio/voices":
            form = await request.form()
            voice_name = form.get("voice_name")
            audio_file = form.get("audio_file")
            if not isinstance(voice_name, str) or not isinstance(audio_file, UploadFile):
                raise HTTPException(400, "请提供音色编号和本人录音。")
            return await bailian_tts.create_voice(request, voice_name, audio_file)
        if request.method == "POST" and path == "v1/audio/speech":
            audio = await bailian_tts.synthesize(request)
            return Response(content=audio, media_type="audio/wav")
        if request.method == "DELETE" and path.startswith("v1/audio/voices/"):
            return await bailian_tts.delete_voice(request, path.rsplit("/", 1)[-1])
        return JSONResponse({"detail": "Unknown journey voice endpoint"}, status_code=404)
    allowed = {
        ("GET", "v1/audio/voices"), ("POST", "v1/audio/voices"),
        ("POST", "v1/audio/speech"),
    }
    deletion = request.method == "DELETE" and path.startswith("v1/audio/voices/journey_") and path.count("/") == 3
    if (request.method, path) not in allowed and not deletion:
        return JSONResponse({"detail": "Unknown journey voice endpoint"}, status_code=404)
    if len(await request.body()) > 2 * 1024 * 1024:
        return JSONResponse({"detail": "录音文件过大。"}, status_code=413)
    return await proxy("journey-tts/" + path, request)


@app.get("/api/config")
async def config():
    """前端运行时配置（示例：上游地址），便于后续将 Key 移到服务端注入。"""
    return {"upstream": UPSTREAM,
            "wsHost": ASR_WS_URL, "wsLegacy": ASR_REALTIME_WS_URL}


@app.get('/api/health')
async def health():
    return {'status': 'ok', 'scope': 'application', 'version': VERSION, 'frontend_built': os.path.isfile(os.path.join(DIST, 'index.html'))}


if os.path.isdir(DIST):
    INDEX = os.path.join(DIST, "index.html")

    @app.get("/", include_in_schema=False)           # no-cache：保证发版后浏览器立刻拿到新 bundle
    @app.get("/index.html", include_in_schema=False)
    async def index_no_cache():
        return FileResponse(INDEX, headers={"Cache-Control": "no-cache"})

    app.mount("/", StaticFiles(directory=DIST, html=True), name="static")
else:
    @app.get("/")
    async def no_dist():
        return Response(content="frontend/dist 不存在：请先 cd frontend && npm install && npm run build",
                        media_type="text/plain; charset=utf-8")


if __name__ == "__main__":
    import uvicorn
    print(f"Amphion Voice Booth -> http://localhost:{PORT}/")
    uvicorn.run(app, host=os.environ.get('HOST', '127.0.0.1'), port=PORT, log_level="warning", access_log=False)
