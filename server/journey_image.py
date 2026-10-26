"""Generate a private receipt sketch; never send provider credentials to the browser."""
import asyncio
import base64
import os
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
try:
    from .bailian_tts import configuration, _headers
    from .security import compose_access
except ImportError:
    from bailian_tts import configuration, _headers
    from security import compose_access

router = APIRouter(prefix='/api/journey')
MAX_IMAGE_BYTES = 8 * 1024 * 1024


class SketchRequest(BaseModel):
    summary: str = Field(min_length=2, max_length=110)
    scene: str = Field(default='', max_length=180)


def sketch_prompt(summary):
    return ('黑白简笔画：' + summary + '。稀疏的黑色钢笔细线，纯白背景，主体完整。'
            '温暖轻盈的手绘风格，横向构图，大量留白，极少阴影。无文字，无边框，无水印。')


def allowed_image_url(value):
    url = urlsplit(value)
    host = url.hostname or ''
    return (url.scheme == 'https' and not url.username and not url.password and
            url.port in (None, 443) and (host.endswith('.aliyuncs.com') or host.endswith('.alicdn.com')))


async def _generate_sketch(summary):
    config = configuration()
    model = os.environ.get('JOURNEY_IMAGE_MODEL', 'qwen-image-2.1-turbo')
    try:
        async with httpx.AsyncClient(timeout=90, follow_redirects=False) as client:
            response = await client.post(config['compatible_base_url'] + '/images/generations',
                headers=_headers(config), json={'model': model, 'prompt': sketch_prompt(summary),
                    'size': '1024x768', 'n': 1, 'prompt_extend': False, 'watermark': False})
            if response.status_code >= 400:
                raise HTTPException(502, '插画暂时未能生成，可以重试插画或直接打印文字手记。')
            try:
                url = response.json()['data'][0]['url']
                if not isinstance(url, str) or not allowed_image_url(url):
                    raise ValueError()
            except (KeyError, IndexError, TypeError, ValueError):
                raise HTTPException(502, '插画服务没有返回有效图片，请重试。') from None
            # Fetch only provider-owned image hosts, without forwarding the API key.
            async with client.stream('GET', url) as image:
                if image.status_code != 200:
                    raise HTTPException(502, '插画读取失败，请重试。')
                raw = bytearray()
                async for chunk in image.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_IMAGE_BYTES:
                        raise HTTPException(502, '插画文件过大，请重试。')
            if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
                raise HTTPException(502, '插画格式无效，请重试。')
            return {'image': 'data:image/png;base64,' + base64.b64encode(raw).decode(), 'model': model}
    except (asyncio.TimeoutError, httpx.TimeoutException):
        raise HTTPException(504, '插画生成超时，文字手记已保留。') from None
    except httpx.RequestError:
        raise HTTPException(502, '暂时无法连接插画服务，文字手记已保留。') from None


async def generate_sketch(summary):
    try:
        return await asyncio.wait_for(_generate_sketch(summary), timeout=100)
    except asyncio.TimeoutError:
        raise HTTPException(504, '插画生成超时，文字手记已保留。') from None


@router.post('/illustrate', dependencies=[Depends(compose_access)])
async def illustrate(request: SketchRequest):
    return await generate_sketch(request.scene.strip() or request.summary)
