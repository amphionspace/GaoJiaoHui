"""Local-only FourHz credentials and browser sessions; never expose the long-lived key."""
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


def local_ports():
    ports = {5173, int(os.environ.get('PORT', '8767'))}
    extra = os.environ.get('JOURNEY_DEMO_PORT', '').strip()
    if extra:
        port = int(extra)
        if not 1 <= port <= 65535:
            raise ValueError('JOURNEY_DEMO_PORT must be a valid port')
        ports.add(port)
    return ports


def enabled():
    return bool(os.environ.get('JOURNEY_ASR_CONFIG_FILE', '').strip())


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
    return 'managed:' + hashlib.sha256(configuration()['api_key'].encode()).hexdigest()


async def mint_token():
    config = configuration()
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.get(config['base_url'] + '/v1/token',
                                        params={'expires_in_seconds': 60},
                                        headers={'Authorization': config['api_key']})
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
    token = await mint_token()
    base = configuration()['base_url'].replace('https://', 'wss://', 1)
    return base + '/v1/asr/realtime?' + urlencode({'speech_model': 'fourhz-spectrum', 'token': token})
