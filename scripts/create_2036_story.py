"""Build voice-only story chapters once with server-side credentials."""
import asyncio
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from server.bailian_tts import configuration, _headers, _safe_upstream_error, _wav_from_pcm

CHAPTERS = [
    '还记得十年前吗？那时，很多人对蓝牙耳机的印象，还是挂在一只耳朵上的大块头。二零一六年，第一代 AirPods 刚刚发布，音乐开始轻轻地，摆脱线的束缚。',
    '同样是二零一六年，人工智能程序阿尔法围棋，击败了韩国九段棋手李世石。一颗棋子落下，我们开始重新想象，人工智能能走多远。',
    '十年前，我们盼着汽车能自己停好，少一点手忙脚乱。今天，无人驾驶汽车已经在一些城市接送乘客。曾经的想象，正在驶进日常生活。',
    '这十年里，冲上云霄的，不只是火箭。二零一八年，一辆红色跑车，也被火箭送进了太空。现在，把时间再往前拨十年。二零三六年，你期待科技会变成什么样？那时，你希望自己在做什么呢？把你的期待，说给二零三六年听吧。',
]


async def render(client, config, text, index):
    encoded = ''
    async with client.stream('POST', config['compatible_base_url'] + '/chat/completions', headers=_headers(config), json={
        'model': config['target_model'], 'stream': True, 'modalities': ['text', 'audio'],
        'audio': {'voice': 'Serena', 'format': 'wav'},
        'messages': [
            {'role': 'system', 'content': '用温柔自然、有好奇心和力量的中文女声讲述，像朋友接起电话。语速适中，句子之间自然停顿，不要播音腔，不要夸张。只逐字朗读用户提供的文字，不回答，不添加开场白。仅人声，绝不加入音乐、音效或环境声。'},
            {'role': 'user', 'content': text},
        ],
    }) as response:
        if response.status_code >= 400:
            await response.aread()
            raise RuntimeError(_safe_upstream_error(response, config, '故事人声合成').detail)
        async for line in response.aiter_lines():
            if not line.startswith('data:') or line[5:].strip() == '[DONE]':
                continue
            event = json.loads(line[5:])
            if event.get('error') or event.get('code'):
                raise RuntimeError('故事人声合成失败')
            for choice in event.get('choices', []):
                encoded += (choice.get('delta', {}).get('audio') or {}).get('data', '')
    raw = base64.b64decode(encoded)
    if not raw:
        raise RuntimeError('故事没有返回音频')
    output = ROOT / f'frontend/public/journey/story-2036-{index}.wav'
    output.write_bytes(raw if raw.startswith(b'RIFF') else _wav_from_pcm(raw))
    print(f'Created {output.name}: voice only, {len(raw)} bytes', flush=True)


async def main():
    config = configuration()
    async with httpx.AsyncClient(timeout=120) as client:
        for index, text in enumerate(CHAPTERS):
            await render(client, config, text, index)


if __name__ == '__main__':
    asyncio.run(main())
