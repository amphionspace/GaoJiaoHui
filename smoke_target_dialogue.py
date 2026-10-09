import asyncio
import json
import os
import sys
import wave
import urllib.request

import websockets

KEY = os.environ.get("AMPHION_API_KEY", "")
if not KEY:
    sys.exit("请先设置环境变量 AMPHION_API_KEY，例如：export AMPHION_API_KEY=sk-...")
BASE = "http://127.0.0.1:18910"
WAV = "/home/ubuntu/cn-asr-fixture-16k-6s.wav"


def get_token():
    req = urllib.request.Request(
        BASE + "/auth/v1/ephemeral-tokens",
        data=json.dumps({
            "resource": "asr.target_dialogue",
            "expires_in_seconds": 180,
            "max_session_seconds": 180,
        }).encode(),
        headers={"X-API-Key": KEY, "Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=15).read())["access_token"]


SU = {
    "type": "session.update",
    "session": {
        "filter": {"mode": "open"},
        "participants": [],
        "audio": {"sample_rate_hz": 16000},
        "recognition": {"mode": "role_separation"},
    },
}


async def run(url, first_msgs, label):
    print(f"--- attempt [{label}] {url}")
    async with websockets.connect(url, max_size=10 * 1024 * 1024, open_timeout=15) as ws:

        async def recv():
            try:
                async for m in ws:
                    print("EVT:", str(m)[:350])
            except websockets.ConnectionClosed as e:
                print("CLOSED:", e.code, e.reason)

        rt = asyncio.create_task(recv())
        try:
            for msg in first_msgs:
                await ws.send(msg if isinstance(msg, str) else json.dumps(msg))
            w = wave.open(WAV, "rb")
            data = w.readframes(w.getnframes())
            CH = 3200
            for i in range(0, len(data), CH):
                await ws.send(data[i:i + CH])
                await asyncio.sleep(0.03)
            await ws.send(json.dumps({"type": "input_audio_buffer.commit", "final": True}))
            await asyncio.sleep(25)
        finally:
            rt.cancel()


async def main():
    tok = get_token()
    print("token ok:", tok[:40])
    try:
        await run(
            "ws://127.0.0.1:18910/asr/v1/target-dialogue",
            [{"type": "session.authenticate", "access_token": tok}, SU],
            "auth-frame",
        )
    except Exception as e:
        print("attempt1 failed:", type(e).__name__, str(e)[:200])
    try:
        await run(
            "ws://127.0.0.1:18910/asr/v1/target-dialogue?api_key=" + KEY,
            [SU],
            "query-key",
        )
    except Exception as e:
        print("attempt2 failed:", type(e).__name__, str(e)[:200])


asyncio.run(main())
