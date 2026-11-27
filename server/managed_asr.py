"""Local-only FourHz credentials and browser sessions; never expose the long-lived key."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import HTTPException

COOKIE = 'journey_local_session'
_SIGNING_KEY = secrets.token_bytes(32)
LOCAL_HOSTS = {'127.0.0.1', 'localhost', '::1'}
# 临时凭证本身有效期 60 秒；签发一次约需 1 秒，此前每个录音会话（以及每次访问
# 校验）都要重新签发，占掉「点击开始说话 -> 可以说话」这段关键路径。凭证只用于
# 建立 WS 握手，40 秒内复用仍留有 20 秒连接余量。
# 服务商允许 1 到 600 秒；签得越长，越不容易撞上「签发限流」。
TOKEN_SECONDS = max(60, min(600, int(os.environ.get('JOURNEY_ASR_TOKEN_SECONDS', '600') or 600)))
SESSION_REUSE_SECONDS = TOKEN_SECONDS
_token_cache = {'fingerprint': None, 'token': '', 'expires': 0.0}
_token_locks = {}


def _token_lock():
    # asyncio locks bind to the loop that first uses them; keep one per loop so
    # tests (one loop per case) and the server (one loop) both stay valid.
    loop = asyncio.get_running_loop()
    lock = _token_locks.get(loop)
    if lock is None:
        lock = _token_locks[loop] = asyncio.Lock()
    return lock


def local_ports():
    ports = {5173, int(os.environ.get('PORT', '8767'))}
    extra = os.environ.get('JOURNEY_DEMO_PORT', '').strip()
    if extra:
        port = int(extra)
        if not 1 <= port <= 65535:
            raise ValueError('JOURNEY_DEMO_PORT must be a valid port')
        ports.add(port)
    return ports


def deepfake_url():
    """A server-owned Deepfake DashScope ASR bridge URL, if configured."""
    raw = os.environ.get('JOURNEY_DEEPFAKE_ASR_URL', '').strip()
    if not raw:
        return ''
    try:
        url = urlsplit(raw)
        query = dict(pair.split('=', 1) for pair in url.query.split('&') if '=' in pair)
    except (TypeError, ValueError):
        raise HTTPException(503, 'Deepfake ASR 地址配置无效。') from None
    if (url.scheme != 'wss' or not url.hostname or url.username or url.password
            or url.fragment or not query.get('token')):
        raise HTTPException(503, 'Deepfake ASR 地址配置无效。')
    return raw


def deepfake_enabled():
    return bool(deepfake_url())


def enabled():
    return deepfake_enabled() or bool(os.environ.get('JOURNEY_ASR_CONFIG_FILE', '').strip())


def public_host():
    host = os.environ.get('JOURNEY_PUBLIC_HOST', '').strip().lower()
    if not host:
        return ''
    url = urlsplit('https://' + host)
    if (url.hostname != host or url.port or url.username or url.password or url.path
            or url.query or url.fragment or host in LOCAL_HOSTS):
        raise ValueError('JOURNEY_PUBLIC_HOST must be a hostname without a scheme or port')
    return host


def configuration():
    if not enabled():
        raise HTTPException(503, '本地 ASR 尚未配置。')
    if os.environ.get('HOST', '') not in LOCAL_HOSTS:
        raise HTTPException(503, '本地 ASR 配置只能用于回环地址服务。')
    try:
        value = json.loads(Path(os.environ['JOURNEY_ASR_CONFIG_FILE']).read_text())
        base = str(value['base_url']).rstrip('/')
        key = str(value['api_key']).strip()
        url = urlsplit(base)
        if (url.scheme != 'https' or url.hostname not in {'api.fourhz.ai', 'api.fourhz.amphion.top'}
                or url.username or url.password or url.query or url.fragment or url.path or url.port not in (None, 443)
                or not key or len(key) > 512):
            raise ValueError()
        return {'base_url': base, 'api_key': key}
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(503, '本地 ASR 配置无法读取，请检查私有配置文件。') from None


def local_request(request, mutation=False):
    try:
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return False
        host = request.url.hostname
        if host == public_host():
            origin = request.headers.get('origin')
            return not mutation or origin == 'https://' + host
        if not request.client or request.client.host not in LOCAL_HOSTS or host not in LOCAL_HOSTS:
            return False
        origin = request.headers.get('origin')
        if origin:
            url = urlsplit(origin)
            if url.scheme != 'http' or url.hostname not in LOCAL_HOSTS or url.port not in local_ports() or url.username or url.password:
                return False
        elif mutation:
            return False
        return True
    except ValueError:
        return False


def signature(value):
    return hmac.new(_SIGNING_KEY, value.encode(), hashlib.sha256).hexdigest()


def issue_cookie(request, response):
    if not local_request(request):
        raise HTTPException(403, '请从本机 Demo 页面连接。')
    if not deepfake_enabled():
        configuration()
    expires = str(int(time.time()) + 8 * 3600)
    response.set_cookie(COOKIE, expires + '.' + signature(expires), max_age=8 * 3600,
                        httponly=True, secure=request.url.hostname == public_host(), samesite='strict', path='/api')


def require_session(request):
    if not local_request(request, mutation=request.method not in {'GET', 'HEAD'}):
        raise HTTPException(403, '只允许本机 Demo 页面访问。')
    try:
        expires, signed = request.cookies.get(COOKIE, '').split('.', 1)
        valid = int(expires) > time.time() and hmac.compare_digest(signed, signature(expires))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise HTTPException(401, '本机会话已过期，请刷新 Demo 后重试。')
    if deepfake_enabled():
        return 'deepfake:' + hashlib.sha256(deepfake_url().encode()).hexdigest()
    return 'managed:' + hashlib.sha256(configuration()['api_key'].encode()).hexdigest()


def _fingerprint(config):
    return hashlib.sha256((config['base_url'] + '\0' + config['api_key']).encode()).hexdigest()


def reset_session_cache():
    """Test hook: forget any reused temporary token."""
    _token_cache.update(fingerprint=None, token='', expires=0.0)


def _reusable(fingerprint):
    return (_token_cache['fingerprint'] == fingerprint and _token_cache['token']
            and _token_cache['expires'] > time.monotonic())


def _token_lifetime(token):
    """Seconds this token can still be handed out for a WS handshake."""
    try:
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        left = float(claims['exp']) - time.time()
    except (KeyError, IndexError, ValueError, TypeError):
        return float(SESSION_REUSE_SECONDS)
    # Keep a margin for the handshake itself, and never exceed the fixed window.
    return max(12.0, min(float(SESSION_REUSE_SECONDS), left - 15.0))


async def mint_token(config=None):
    if deepfake_enabled() and config is None:
        return 'deepfake'
    config = config or configuration()
    fingerprint = _fingerprint(config)
    if _reusable(fingerprint):
        return _token_cache['token']
    async with _token_lock():
        if _reusable(fingerprint):
            return _token_cache['token']
        token = await _request_token(config)
        _token_cache.update(fingerprint=fingerprint, token=token,
                            expires=time.monotonic() + _token_lifetime(token))
        return token


async def _request_token(config):
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            for attempt in range(2):
                response = await client.get(config['base_url'] + '/v1/token',
                                            params={'expires_in_seconds': TOKEN_SECONDS},
                                            headers={'Authorization': config['api_key']})
                # The provider rate-limits minting per minute; one short retry
                # turns most bursts into a delay instead of a failed visit.
                if response.status_code != 429 or attempt:
                    break
                await asyncio.sleep(1.2)
        if response.status_code in (401, 403):
            raise HTTPException(401, '新的 ASR 密钥无效或无访问权限，请检查本机配置。')
        if response.status_code == 402:
            raise HTTPException(503, 'ASR 账户余额不足，请补充额度后重试。')
        if response.status_code == 429:
            raise HTTPException(429, 'ASR 服务请求较多，请稍后重试。')
        if response.status_code != 200:
            raise HTTPException(503, 'ASR 授权服务暂时不可用，请稍后重试。')
        payload = response.json()
        token = payload.get('token') if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token or len(token) > 16000:
            raise ValueError()
        return token
    except (httpx.RequestError, ValueError):
        raise HTTPException(503, '无法取得 ASR 临时凭证，请稍后重试。') from None


async def session_url():
    if deepfake_enabled():
        return deepfake_url()
    config = configuration()
    token = await mint_token(config)
    base = config['base_url'].replace('https://', 'wss://', 1)
    return base + '/v1/asr/realtime?' + urlencode({'speech_model': 'fourhz-spectrum', 'token': token})
