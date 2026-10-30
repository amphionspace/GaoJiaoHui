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
import base64
import os
import secrets
import shutil
import time
import typing
import logging
import mimetypes
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import httpcore
from httpcore._backends.anyio import AnyIOBackend
from fastapi import FastAPI, Request, Response, HTTPException, Depends, File, Form
from fastapi import UploadFile as APIUploadFile
from starlette.datastructures import UploadFile

from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
try:
    from .journey_text import router as journey_text_router
    from .journey_text import configuration as text_configuration
    from .journey_image import router as journey_image_router
    from .security import RequestLimits, compose_access
    from .metrics import metrics as metrics_store
    from . import bailian_tts, managed_asr, sessions
except ImportError:
    from journey_text import router as journey_text_router
    from journey_text import configuration as text_configuration
    from journey_image import router as journey_image_router
    from security import RequestLimits, compose_access
    from metrics import metrics as metrics_store
    import bailian_tts, managed_asr, sessions

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
# Minimal Linux MIME databases may omit resources required by the kiosk.
for extension, content_type in {
    '.webp': 'image/webp', '.woff2': 'font/woff2',
    '.wasm': 'application/wasm', '.onnx': 'application/octet-stream',
}.items():
    mimetypes.add_type(content_type, extension)
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
app.include_router(journey_image_router)
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
    kiosk = request.url.path == '/' and request.query_params.get('display') == 'kiosk'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN' if kiosk else 'DENY'
    response.headers['Content-Security-Policy'] = "frame-ancestors 'self'" if kiosk else "frame-ancestors 'none'"
    if request.url.path.startswith(('/api/', '/proxy/')):
        response.headers['Cache-Control'] = 'no-store'
    elif request.url.path in ('/', '/index.html'):
        response.headers['Cache-Control'] = 'no-cache'
    return response


@app.middleware('http')
async def collect_metrics(request, call_next):
    """Aggregate API latency/status only; admin, metrics and health polls skip it."""
    path = request.url.path
    if not (path.startswith('/api/') or path.startswith('/proxy/')):
        return await call_next(request)
    if path.startswith(('/api/admin', '/api/health')):
        return await call_next(request)
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        metrics_store.request(path, status, time.perf_counter() - started)


def frontend_check():
    built = os.path.isfile(os.path.join(DIST, 'index.html'))
    return {'ok': built, 'built': built}


def text_check():
    try:
        config = text_configuration()
        configured = bool(config.get('url') and config.get('model'))
        return {'ok': configured, 'model': config.get('model') or ''}
    except Exception:  # HTTPException from an unreadable config file.
        return {'ok': False, 'model': ''}


def asr_check():
    managed = managed_asr.enabled()
    if not managed:
        return {'ok': True, 'managed': False, 'detail': 'gateway key'}
    try:
        managed_asr.configuration()
        return {'ok': True, 'managed': True}
    except Exception:
        return {'ok': False, 'managed': True}


def tts_check():
    provider = os.environ.get('JOURNEY_TTS_PROVIDER', 'legacy').strip().lower() or 'legacy'
    if not bailian_tts.enabled():
        return {'ok': True, 'provider': provider, 'detail': 'gateway'}
    try:
        bailian_tts.configuration()
        return {'ok': True, 'provider': provider}
    except Exception:
        return {'ok': False, 'provider': provider}


def disk_check():
    usage = shutil.disk_usage(ROOT)
    percent = usage.used / usage.total * 100
    return {'ok': percent < 95, 'percent': round(percent, 1), 'free_gb': round(usage.free / 1e9, 1)}


def health_checks():
    return {
        'frontend': frontend_check(),
        'text': text_check(),
        'asr': asr_check(),
        'tts': tts_check(),
        'disk': disk_check(),
    }


def health_status(checks):
    return 'ok' if all(item['ok'] for item in checks.values()) else 'degraded'


def admin_credentials():
    return os.environ.get('JOURNEY_ADMIN_USER', '').strip(), os.environ.get('JOURNEY_ADMIN_PASSWORD', '')


def _auth_error(detail='需要后台账号。'):
    return HTTPException(401, detail, headers={'WWW-Authenticate': 'Basic realm="journey-admin"'})

def require_admin(request: Request):
    user, password = admin_credentials()
    if not user or not password:
        raise HTTPException(503, '后台未启用：请配置 JOURNEY_ADMIN_USER 与 JOURNEY_ADMIN_PASSWORD。')
    allowed = [ip.strip() for ip in os.environ.get('JOURNEY_ADMIN_IPS', '').split(',') if ip.strip()]
    if allowed:
        peer = request.client.host if request.client else ''
        forwarded = request.headers.get('x-forwarded-for', '').split(',')[0].strip()
        # Only trust the forwarding header when the direct peer is the local proxy.
        source = (forwarded or peer) if peer in ('127.0.0.1', '::1') else peer
        if source not in allowed:
            raise HTTPException(403, '后台只允许指定来源访问。')
    header = request.headers.get('authorization', '')
    if not header.lower().startswith('basic '):
        raise _auth_error('请输入后台账号。')
    try:
        decoded = base64.b64decode(header.split(' ', 1)[1], validate=True).decode('utf-8')
    except (ValueError, UnicodeDecodeError):
        raise _auth_error('后台账号无效。') from None
    got_user, _, got_password = decoded.partition(':')
    if not (secrets.compare_digest(got_user, user) and secrets.compare_digest(got_password, password)):
        raise _auth_error('账号或密码不正确。')
    return got_user


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
            session_id = request.headers.get("x-journey-session", "")
            if session_id:
                sample = await audio_file.read(2 * 1024 * 1024 + 1)
                await audio_file.seek(0)
                if 0 < len(sample) <= 2 * 1024 * 1024:
                    sessions.save_audio(session_id, "sample", sample)
            return await bailian_tts.create_voice(request, voice_name, audio_file)
        if request.method == "POST" and path == "v1/audio/speech":
            audio = await bailian_tts.synthesize(request)
            sessions.save_audio(request.headers.get("x-journey-session", ""), "reply", audio)
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
async def config(request: Request, response: Response):
    """前端运行时配置（示例：上游地址），便于后续将 Key 移到服务端注入。"""
    if managed_asr.enabled():
        managed_asr.issue_cookie(request, response)
    return {"upstream": UPSTREAM, "asrManaged": managed_asr.enabled(),
            "wsHost": ASR_WS_URL, "wsLegacy": ASR_REALTIME_WS_URL,
            "sessionLog": sessions.enabled(), "sessionRetentionDays": sessions.retention_days()}


@app.post('/api/journey/asr-session', dependencies=[Depends(compose_access)])
async def asr_session():
    metrics_store.event('asr_session')
    return {'url': await managed_asr.session_url()}


class PrintEvent(BaseModel):
    session_id: str = Field(default='', max_length=64, pattern=r'^[0-9a-zA-Z-]*$')


@app.post('/api/journey/print', dependencies=[Depends(compose_access)])
async def journey_print(event: PrintEvent):
    metrics_store.event('print')
    return {'printed': sessions.mark_printed(event.session_id)}


@app.post('/api/journey/audio', dependencies=[Depends(compose_access)])
async def journey_audio(audio_file: APIUploadFile = File(...), session_id: str = Form('')):
    raw = await audio_file.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(413, '录音文件过大。')
    if not raw.startswith(b'RIFF') or b'WAVE' not in raw[:16]:
        raise HTTPException(400, '请提供 WAV 格式的录音。')
    seconds = sessions.save_audio(session_id, 'visit', raw)
    return {'stored': bool(seconds), 'seconds': seconds}


@app.get('/api/admin/summary', dependencies=[Depends(require_admin)])
async def admin_summary():
    return sessions.summary()


@app.get('/api/admin/sessions/{session_id}/audio/{kind}', dependencies=[Depends(require_admin)])
async def admin_session_audio(session_id: str, kind: str):
    if kind not in ('sample', 'reply', 'visit'):
        raise HTTPException(404, '没有这段音频。')
    path = sessions.audio_path(session_id, kind)
    if not path:
        raise HTTPException(404, '没有保存这段音频。')
    return FileResponse(path, media_type='audio/wav', headers={'Cache-Control': 'no-store'})


@app.get('/api/health')
async def health():
    checks = health_checks()
    snapshot = metrics_store.snapshot()
    return {
        'status': health_status(checks), 'scope': 'application', 'version': VERSION,
        'release': os.path.basename(ROOT), 'frontend_built': checks['frontend']['built'],
        'uptime_seconds': snapshot['uptime_seconds'], 'checks': checks,
        'stats': {
            'requests_total': snapshot['requests']['total'],
            'errors_total': snapshot['requests']['errors'],
            'recent': snapshot['requests']['recent'],
        },
    }


@app.get('/api/admin/stats', dependencies=[Depends(require_admin)])
async def admin_stats():
    checks = health_checks()
    snapshot = metrics_store.snapshot()
    return {
        'release': os.path.basename(ROOT), 'version': VERSION, 'status': health_status(checks),
        'processed_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'uptime_seconds': snapshot['uptime_seconds'], 'checks': checks, 'stats': snapshot,
    }


@app.get('/api/admin/sessions', dependencies=[Depends(require_admin)])
async def admin_sessions(limit: int = 30, offset: int = 0):
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    summary = sessions.summary()
    return {
        'enabled': summary['enabled'], 'retention_days': summary['retention_days'],
        'keep_transcript': sessions.keep_transcript(), 'total': summary['total'], 'audio': summary['audio'],
        'sessions': sessions.recent(limit, offset),
    }


@app.post('/api/admin/sessions/clear', dependencies=[Depends(require_admin)])
async def admin_sessions_clear():
    sessions.clear()
    return {'cleared': True}


@app.get('/metrics', dependencies=[Depends(require_admin)])
async def prometheus_metrics():
    checks = health_checks()
    body = metrics_store.prometheus()
    for name, check in checks.items():
        body += f'journey_health_ok{{check="{name}"}} {1 if check["ok"] else 0}\n'
    body += f'journey_disk_used_ratio {checks["disk"]["percent"] / 100}\n'
    return PlainTextResponse(body, media_type='text/plain; version=0.0.4')


ADMIN_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>运维看板 · 和 2036 对话</title>
<style>
:root{--bg:#f6f3ec;--panel:#fff;--line:#e3ddd0;--ink:#2a3e35;--dim:#7c8a83;--acc:#305b4b;--ok:#2f8f5b;--bad:#c4553b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;justify-content:space-between;padding:18px 24px;background:var(--panel);border-bottom:1px solid var(--line)}
header h1{font-size:16px;margin:0;display:flex;gap:10px;align-items:baseline}
header h1 small{font-weight:400;color:var(--dim);font-size:12px}
.meta{display:flex;gap:16px;color:var(--dim);font-size:12px;flex-wrap:wrap;align-items:center}
main{max-width:1180px;margin:0 auto;padding:20px 24px 40px;display:grid;gap:16px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card h2{margin:0 0 10px;font-size:12px;font-weight:600;color:var(--dim);letter-spacing:.06em}
.chip{display:flex;align-items:center;gap:8px;font-size:13px}
.dot{width:9px;height:9px;border-radius:50%;background:var(--dim);flex:none}
.dot.ok{background:var(--ok)}.dot.bad{background:var(--bad)}
.chip .detail{color:var(--dim);font-size:11px;margin-left:auto;text-align:right}
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}
.num{display:flex;justify-content:space-between;gap:12px;padding:4px 0;border-bottom:1px dashed var(--line);font-size:13px}
.num:last-child{border-bottom:0}
.num b{font-variant-numeric:tabular-nums;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:left;padding:7px 6px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--dim);font-weight:500}
td.path{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;white-space:normal;word-break:break-all}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.empty{color:var(--dim);padding:10px 0;font-size:12.5px}
.note{color:var(--dim);font-size:11.5px;margin-top:8px}
footer{color:var(--dim);font-size:12px;line-height:1.8}
button{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:7px;padding:7px 14px;cursor:pointer;font-size:12px}
button:hover{border-color:var(--acc);color:var(--acc)}
.alert{background:#fbe9e3;border-color:#f0c9bd;color:#8f3b24}
.metric-value{font-size:34px;font-weight:700;color:#1c6bb0;line-height:1.1}
.metric-value.bad{color:var(--bad)}
.session-body audio{width:100%;max-width:420px;height:34px}
.s-user{font-weight:600;font-size:12px}
.session-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:10px}
.session-head h2{margin:0}
.session-tools{display:flex;align-items:center;gap:10px;color:var(--dim);font-size:11.5px}
details.session{border-top:1px solid var(--line);padding:8px 0}
details.session:first-of-type{border-top:0}
details.session summary{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:baseline;cursor:pointer;list-style:none;font-size:12.5px}
details.session summary::-webkit-details-marker{display:none}
details.session summary .s-time{color:var(--dim);font-size:11.5px;font-variant-numeric:tabular-nums}
details.session summary .s-topic{color:var(--acc);font-size:11.5px}
details.session summary .s-note{flex:1;min-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
details.session[open] summary .s-note{white-space:normal}
details.session summary .s-meta{color:var(--dim);font-size:11px;white-space:nowrap}
.session-body{margin:10px 0 4px;display:grid;gap:10px}
.session-body h4{margin:0 0 4px;font-size:11px;color:var(--dim);font-weight:600}
.session-body p{margin:0;font-size:12.5px;line-height:1.7;white-space:pre-wrap;word-break:break-word;max-height:220px;overflow:auto;background:#fbf9f4;border:1px solid var(--line);border-radius:7px;padding:8px 10px}
@media (max-width:640px){header{padding:14px 16px}main{padding:14px 16px 32px}}
</style>
</head>
<body>
<header>
  <h1>和 2036 对话 <small>运维看板</small></h1>
  <div class="meta">
    <span id="meta-release">-</span><span id="meta-version">-</span>
    <span id="meta-uptime">-</span><span id="meta-updated">-</span>
    <button id="refresh" type="button">立即刷新</button>
  </div>
</header>
<main>
  <div id="alert" class="card alert" hidden></div>
  <section class="cards" id="summary"></section>
  <section class="cards" id="status"></section>
  <div class="grid3">
    <div class="card"><h2>请求</h2><div id="requests"></div></div>
    <div class="card"><h2>旅程阶段</h2><div id="events"></div></div>
    <div class="card"><h2>阶段时延</h2><div id="latency"></div></div>
  </div>
  <section class="card">
    <div class="session-head"><h2>最近会话</h2><div class="session-tools"><span id="session-meta"></span><button id="session-clear" type="button">清空</button></div></div>
    <div id="sessions"></div>
    <p class="note" id="session-note"></p>
  </section>
  <section class="card"><h2>接口</h2><div id="paths"></div><p class="note">流式接口（compose/stream）的时延为首字节时间；草稿与终版的实际时延见上方“阶段时延”。</p></section>
  <section class="card"><h2>最近错误</h2><div id="errors"></div></section>
  <footer>看板默认只统计聚合数据；会话记录可在服务器开启并自动过期，音频始终不保存。企业微信告警由 journey-monitor.timer 每分钟检查并推送。</footer>
</main>
<script>
const $ = id => document.getElementById(id)
const esc = value => String(value == null ? '' : value).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
const dot = ok => '<span class="dot ' + (ok ? 'ok' : 'bad') + '"></span>'
const CHECK_LABELS = { frontend: '前端构建', text: '文本模型', asr: '语音识别', tts: '声音合成', disk: '磁盘' }
const TOPIC_LABELS = { future: '未来', product: '产品', idea: '想法', story: '故事' }
let openSessions = new Set()
const EVENT_LABELS = { compose_draft: '草稿上屏', compose_final: '审校完成', compose_review_fallback: '审校回退', compose_error: '整理失败', asr_session: '语音会话', illustrate: '插画请求', illustrate_error: '插画失败' }
const LATENCY_LABELS = { compose_draft_seconds: '草稿时延', compose_final_seconds: '终版时延' }
function detail(name, check) {
  if (name === 'text') return check.model || ''
  if (name === 'tts') return check.provider || ''
  if (name === 'disk') return (check.percent || 0) + '% · 剩余 ' + (check.free_gb || 0) + 'G'
  if (name === 'asr') return check.managed ? '托管凭证' : '网关密钥'
  return check.built === false ? '未构建' : ''
}
function uptime(seconds) {
  if (seconds == null) return '-'
  const days = Math.floor(seconds / 86400), hours = Math.floor(seconds % 86400 / 3600), minutes = Math.floor(seconds % 3600 / 60)
  if (days) return '已运行 ' + days + ' 天 ' + hours + ' 小时'
  if (hours) return '已运行 ' + hours + ' 小时 ' + minutes + ' 分'
  return '已运行 ' + minutes + ' 分'
}
function render(data) {
  $('meta-release').textContent = data.release || ''
  $('meta-version').textContent = 'v' + (data.version || '')
  $('meta-uptime').textContent = uptime(data.uptime_seconds)
  $('meta-updated').textContent = '更新于 ' + (data.processed_at || '')
  const overall = data.status === 'ok'
  $('status').innerHTML = '<div class="card"><h2>服务</h2><div class="chip">' + dot(overall) + '<span>' + (overall ? '全部正常' : '有异常项') + '</span></div></div>' +
    Object.entries(data.checks || {}).map(([name, check]) =>
      '<div class="card"><h2>' + esc(CHECK_LABELS[name] || name) + '</h2><div class="chip">' + dot(check.ok) +
      '<span>' + (check.ok ? '正常' : '异常') + '</span><span class="detail">' + esc(detail(name, check)) + '</span></div></div>').join('')
  const requests = data.stats.requests
  $('requests').innerHTML =
    '<div class="num"><span>请求总数</span><b>' + requests.total + '</b></div>' +
    '<div class="num"><span>5xx 错误</span><b>' + requests.errors + '</b></div>' +
    '<div class="num"><span>最近 5 分钟</span><b>' + requests.recent.total + '</b></div>' +
    '<div class="num"><span>最近 5 分钟错误</span><b>' + requests.recent.errors + '</b></div>'
  const events = Object.entries(data.stats.events || {})
  $('events').innerHTML = events.length
    ? events.map(([name, count]) => '<div class="num"><span>' + esc(EVENT_LABELS[name] || name) + '</span><b>' + count + '</b></div>').join('')
    : '<div class="empty">服务启动后还没有阶段事件。</div>'
  const observations = Object.entries(data.stats.observations || {})
  $('latency').innerHTML = observations.length
    ? observations.map(([name, series]) => '<div class="num"><span>' + esc(LATENCY_LABELS[name] || name) + '</span><b>' + Math.round(series.p50_ms) + ' / ' + Math.round(series.p95_ms) + ' ms</b></div>').join('')
    : '<div class="empty">还没有可用的阶段时延。</div>'
  const paths = data.stats.paths || []
  $('paths').innerHTML = paths.length
    ? '<table><thead><tr><th>接口</th><th class="num">次数</th><th class="num">5xx</th><th class="num">P50</th><th class="num">P95</th></tr></thead><tbody>' +
      paths.map(item => '<tr><td class="path">' + esc(item.path) + '</td><td class="num">' + item.count + '</td><td class="num">' + item.errors +
        '</td><td class="num">' + Math.round(item.p50_ms) + ' ms</td><td class="num">' + Math.round(item.p95_ms) + ' ms</td></tr>').join('') + '</tbody></table>'
    : '<div class="empty">暂无接口请求。</div>'
  const errors = data.stats.errors || []
  $('errors').innerHTML = errors.length
    ? '<table><thead><tr><th>时间</th><th>接口</th><th class="num">状态</th><th>代码</th></tr></thead><tbody>' +
      errors.map(item => '<tr><td>' + esc(item.at) + '</td><td class="path">' + esc(item.path) + '</td><td class="num">' + item.status +
        '</td><td>' + esc(item.code) + '</td></tr>').join('') + '</tbody></table>'
    : '<div class="empty">暂无错误。</div>'
}
function ms(value) { return value == null ? '-' : (value / 1000).toFixed(1) + 's' }
const SUMMARY = [['today', '今日体验'], ['total', '总体验'], ['generated', '已生成'], ['printed', '已打印'], ['failed', '异常']]
function renderSummary(data) {
  $('summary').innerHTML = SUMMARY.map(([key, label]) =>
    '<div class="card"><h2>' + label + '</h2><div class="metric-value' + (key === 'failed' && data[key] ? ' bad' : '') + '">' + (data[key] || 0) + '</div></div>').join('')
}
async function loadSummary() {
  try {
    const response = await fetch('/api/admin/summary', { cache: 'no-store' })
    if (response.ok) renderSummary(await response.json())
  } catch (error) { /* keep the previous numbers */ }
}
function audioTag(item, kind, label) {
  return '<div><h4>' + label + '</h4><audio controls preload="none" src="/api/admin/sessions/' +
    encodeURIComponent(item.id) + '/audio/' + kind + '"></audio></div>'
}
function renderSessions(data) {
  $('session-meta').textContent = data.enabled ? ('共 ' + data.total + ' 条 · 保留 ' + data.retention_days + ' 天 · 音频 ' + (data.audio || 0) + ' 条') : '未开启'
  $('session-note').textContent = data.enabled
    ? '会话内容与音频仅用于现场复盘，按保留期自动清理；包含访客录音、参考音与回信语音。'
    : '会话记录未开启：在服务器 /etc/amphion-gjh/session.env 设置 JOURNEY_SESSION_LOG=1 后重启。'
  if (!data.enabled) { $('sessions').innerHTML = '<div class="empty">会话记录未开启。</div>'; return }
  if (!data.sessions.length) { $('sessions').innerHTML = '<div class="empty">还没有会话记录，完成一次讲述后会出现。</div>'; return }
  $('sessions').innerHTML = data.sessions.map(item => {
    const who = item.visitor_no ? '用户' + item.visitor_no : '访客'
    const failed = item.status === 'failed'
    const meta = failed
      ? '未生成 · ' + esc(item.error_code || '失败')
      : item.transcript_chars + ' 字 · 草稿 ' + ms(item.draft_ms) + ' · 终版 ' + ms(item.final_ms) +
        (item.reviewed ? ' · 已审校' : ' · 未审校') + (item.printed_at ? ' · 已打印' : '')
    return '<details class="session" data-id="' + esc(item.id) + '"' + (openSessions.has(item.id) ? ' open' : '') + '>' +
      '<summary><span class="s-user">' + esc(who) + '</span>' +
      '<span class="s-time">' + esc(item.created_at.slice(5)) + '</span>' +
      '<span class="s-topic">' + esc(TOPIC_LABELS[item.topic] || item.topic) + '</span>' +
      '<span class="s-note">' + esc(failed ? '（未生成）' : (item.note_text || '（无手记）')) + '</span>' +
      '<span class="s-meta">' + meta + '</span></summary>' +
      '<div class="session-body">' +
        '<div><h4>讲述原文</h4><p>' + esc(item.transcript || '未保存') + '</p></div>' +
        '<div><h4>手记</h4><p>' + esc(item.note_text || '（无）') + '</p></div>' +
        '<div><h4>回信</h4><p>' + esc(item.message || '（无）') + '</p></div>' +
        '<div><h4>关键词</h4><p>' + esc((item.keywords || []).join(' · ') || '（无）') + '</p></div>' +
        (item.has_visit ? audioTag(item, 'visit', '访客录音' + (item.visit_seconds ? '（' + item.visit_seconds + ' 秒）' : '')) : '') +
        (item.has_sample ? audioTag(item, 'sample', '访客参考音') : '') +
        (item.has_reply ? audioTag(item, 'reply', '回信语音' + (item.reply_seconds ? '（' + item.reply_seconds + ' 秒）' : '')) : '') +
        '<div><h4>元信息</h4><p>模型 ' + esc(item.model || '-') + ' · 语言 ' + esc(item.language || '-') +
          (item.printed_at ? ' · 打印于 ' + esc(item.printed_at) : '') + '</p></div>' +
      '</div></details>'
  }).join('')
  document.querySelectorAll('details.session').forEach(node => {
    node.addEventListener('toggle', () => {
      if (node.open) openSessions.add(node.dataset.id)
      else openSessions.delete(node.dataset.id)
    })
  })
}
async function loadSessions() {
  try {
    const response = await fetch('/api/admin/sessions?limit=30', { cache: 'no-store' })
    if (!response.ok) return
    renderSessions(await response.json())
  } catch (error) { /* keep the previous list on a transient failure */ }
}
async function refresh() {
  try {
    const response = await fetch('/api/admin/stats', { cache: 'no-store' })
    if (!response.ok) throw new Error('HTTP ' + response.status)
    render(await response.json())
    $('alert').hidden = true
  } catch (error) {
    const box = $('alert')
    box.hidden = false
    box.textContent = '看板数据读取失败：' + error.message + '。若刚修改过后台密码，请关闭浏览器后重新登录。'
  }
}
$('refresh').addEventListener('click', refresh)
$('session-clear').addEventListener('click', async () => {
  if (!confirm('清空全部会话记录？此操作不可撤销。')) return
  const response = await fetch('/api/admin/sessions/clear', { method: 'POST' })
  if (response.ok) { openSessions.clear(); loadSessions() }
})
refresh(); loadSessions(); loadSummary()
setInterval(() => { if (!document.hidden) { refresh(); loadSessions(); loadSummary() } }, 10000)
document.addEventListener('visibilitychange', () => { if (!document.hidden) { refresh(); loadSessions(); loadSummary() } })
</script>
</body>
</html>"""


@app.get('/admin', dependencies=[Depends(require_admin)])
async def admin_page():
    return HTMLResponse(ADMIN_PAGE, headers={'Cache-Control': 'no-store'})


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
