import asyncio, base64, json, os, sys, wave
import websockets

KEY = os.environ.get("AMPHION_API_KEY", "")
if not KEY:
    sys.exit("请先设置环境变量 AMPHION_API_KEY，例如：export AMPHION_API_KEY=sk-...")
URL = "ws://127.0.0.1:18910/asr/v1/realtime?api_key=" + KEY
WAV = "/home/ubuntu/cn-asr-fixture-16k-6s.wav"


async def main():
    w = wave.open(WAV, "rb")
    print("wav:", w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes())
    pcm = w.readframes(w.getnframes())
    print(f"pcm={len(pcm)}B dur={len(pcm)/32000:.1f}s")
    async with websockets.connect(URL, max_size=10 * 1024 * 1024, open_timeout=15) as ws:

        async def recv():
            try:
                async for m in ws:
                    d = json.loads(m)
                    print("EVT:", json.dumps(d, ensure_ascii=False)[:400])
            except websockets.ConnectionClosed as e:
                print("CLOSED:", e.code, e.reason)

        rt = asyncio.create_task(recv())
        await ws.send(json.dumps({"type": "session.update", "session": {"language": "auto"}}))
        CH = 3200
        for i in range(0, len(pcm), CH):
            await ws.send(json.dumps({"type": "input_audio_buffer.append",
                                      "audio": base64.b64encode(pcm[i:i + CH]).decode()}))
            await asyncio.sleep(0.03)
        await ws.send(json.dumps({"type": "input_audio_buffer.commit", "final": True}))
        await asyncio.sleep(20)
        rt.cancel()


asyncio.run(main())
