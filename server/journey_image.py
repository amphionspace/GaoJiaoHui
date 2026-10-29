"""Generate a private receipt sketch; never send provider credentials to the browser."""
import asyncio
import base64
import hashlib
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


def sketch_prompt(scene):
    scene = scene.strip() or '一个人站在安静的户外场景中，望向远处'
    return (
        '根据用户讲述的场景，制作一张1024×1024透明PNG的独立插画贴纸，主体周围必须完全透明；不是一张带底色的海报：\n'
        f'{scene}\n\n'
        '内容：提炼用户表达中最具识别度的1至3个元素，让人一眼看出这是对讲述内容的艺术化提炼。'
        '保留关键人物关系、动作、物件和场景，不添加用户未表达的愿望或事实。'
        '不默认添加山、牦牛、寺庙、机器人或飞车；下列重构方法仅在场景确有相应元素时使用。\n'
        '抽象化重构：建筑化为几何色块与简化结构；远景压缩为剪影或小色块；云层用柔软横向笔触；'
        '水面用少量波纹与色块；灯光用少量暖黄点缀。人物以简化姿态和色块呈现，不刻画繁复五官。\n'
        '插画风格：soft gouache、dry brush texture、watercolor-like、subtle paper grain、'
        'hand-painted editorial、matte printed texture。柔和水粉、干刷肌理、轻微纸张拼贴感和自然不规则边缘，'
        '像艺术杂志、城市旅行摄影集、博物馆商店海报，安静、诗意、现代、克制。\n'
        '构图：1:1正方形，疏朗、平衡，保留大量Alpha为0的透明区域，不用任何颜色填充空白。一个清晰的视觉中心，'
        '可识别的主体与留白形成自然关系，避免画满画布、密集场景或漂浮的小图标。\n'
        '色彩：warm ivory、muted navy、blue grey、smoky grey、warm ochre、mustard yellow、soft beige；'
        '低饱和，按内容选择少量协调色彩，必须有明确的彩色色块，不要求凑齐全部颜色。\n'
        '背景：必须输出带真实透明Alpha通道的PNG，主体以外完全透明。不要绘制纸面、米色底、白底、渐变底或棋盘格，不画整片天空。仅绘制少量孤立的主体色块；禁止矩形画幅和满幅风景。纸张与干刷质感仅用于主体内部，保留自然柔软的半透明边缘。\n'
        '禁止：明显描边、黑白钢笔线稿、卡通、动漫、3D、矢量图标感、赛博朋克、像素风、摄影、'
        '复杂装饰、商业广告感、塑料光泽、过度细节。禁止任何文字、汉字、字母、数字、标题、标语、Logo、水印。'
        '参考图的小字不需要复刻；只生成独立插画，不生成完整便签。'
    )


def allowed_image_url(value):
    url = urlsplit(value)
    host = url.hostname or ''
    return (url.scheme == 'https' and not url.username and not url.password and
            url.port in (None, 443) and (host.endswith('.aliyuncs.com') or host.endswith('.alicdn.com')))


async def _generate_sketch(summary):
    config = configuration()
    model = os.environ.get('JOURNEY_IMAGE_MODEL', 'qwen-image-2.1-turbo')
    prompt = sketch_prompt(summary)
    payload = {
        'model': model,
        'prompt': prompt,
        'size': '1024x1024',
        'n': 1,
        'prompt_extend': False,
        'watermark': False,
    }
    # The compatible endpoint does not advertise a common transparency field.
    # Only send it when an operator explicitly confirms support for this model.
    background_mode = os.environ.get('JOURNEY_IMAGE_BACKGROUND', '').strip().lower()
    if background_mode in {'transparent', 'opaque'}:
        payload['background'] = background_mode
    try:
        async with httpx.AsyncClient(timeout=90, follow_redirects=False) as client:
            response = await client.post(config['compatible_base_url'] + '/images/generations',
                headers=_headers(config), json=payload)
            if response.status_code >= 400:
                try:
                    failure = response.json()
                    failure = failure.get('error', failure)
                    code = failure.get('code', '') if isinstance(failure, dict) else ''
                except (ValueError, AttributeError):
                    code = ''
                if code == 'insufficient_quota':
                    raise HTTPException(503, '插画服务额度不足，请联系工作人员补充额度。文字手记已保留，额度恢复后可重试插画。')
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
            result = {'image': 'data:image/png;base64,' + base64.b64encode(raw).decode(), 'model': model}
            if os.environ.get('JOURNEY_DEBUG', '').strip().lower() in {'1', 'true', 'yes'}:
                provider_url = urlsplit(url)
                result['debug'] = {
                    'model': model,
                    'request_path': '/images/generations',
                    'prompt': prompt,
                    'reference_image_used': False,
                    'cache_hit': False,
                    'fallback_used': False,
                    'background_parameter_sent': background_mode if 'background' in payload else None,
                    'provider_image_host': provider_url.hostname,
                    'raw_image': {
                        'format': 'png',
                        'bytes': len(raw),
                        'sha256': hashlib.sha256(raw).hexdigest(),
                    },
                }
            return result
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
