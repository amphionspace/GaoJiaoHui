#!/usr/bin/env python3
"""Amphion 三类语音接口本地交互 Demo（Mac 直连公网，2026-09-29 实测可用）。

用法：
  python3 local_demo.py health                          # 健康检查
  python3 local_demo.py asr sample_zh_16k.wav           # 接口① 流式转写（partial→final）
  python3 local_demo.py dialogue sample_zh_16k.wav      # 接口② 多人说话人分离（open 模式）
  python3 local_demo.py enroll sample_zh_16k.wav 张三   # 接口② 声纹注册（consent）
  python3 local_demo.py token                           # 接口② 签发一次性 token
  python3 local_demo.py voices                          # 接口③ 音色列表
  python3 local_demo.py clone ref.wav my_voice          # 接口③ 上传参考音频复刻音色
  python3 local_demo.py speak "你好" my_voice out.wav   # 接口③ 克隆合成

环境：python3 >= 3.9，pip3 install --user websockets
API Key：优先读环境变量 AMPHION_API_KEY，缺省用公共测试 Key。
音频：16kHz / 16bit / 单声道 WAV（afconvert 转换命令见计划文档）。
"""
import argparse
import asyncio
import base64
import json
import os
import sys
import urllib.error
import urllib.request
import wave

try:
    import websockets
except ImportError:
    sys.exit("缺少依赖：pip3 install --user websockets")

BASE_HTTP = "https://amphion.top"
BASE_WS = "wss://amphion.top"
API_KEY = os.environ.get("AMPHION_API_KEY", "")
if not API_KEY:
    sys.exit("缺少 API Key：请设置环境变量后运行，例如 export AMPHION_API_KEY=sk-...")


# ---------- HTTP 基础 ----------

def http_bytes(path, method="GET", body=None, content_type=None, timeout=300):
    headers = {"X-API-Key": API_KEY}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(BASE_HTTP + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def http_json(path, method="GET", payload=None, timeout=300):
    body = json.dumps(payload).encode() if payload is not None else None
    status, data = http_bytes(path, method, body,
                              "application/json" if body else None, timeout)
    try:
        return status, json.loads(data)
    except Exception:
        return status, data[:500].decode("utf-8", "replace")


def multipart(fields, files):
    b = "----AmphionDemoBoundary7MA4YWxk"
    out = b""
    for k, v in fields.items():
        out += ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (b, k, v)).encode()
    for k, (fname, data, ctype) in files.items():
        out += ('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
                'Content-Type: %s\r\n\r\n' % (b, k, fname, ctype)).encode()
        out += data + b"\r\n"
    out += ("--%s--\r\n" % b).encode()
    return out, "multipart/form-data; boundary=%s" % b


def load_pcm(wav_path):
    """读取 WAV 并返回 16kHz/16bit/mono PCM 字节。"""
    w = wave.open(wav_path, "rb")
    sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
    if (sr, ch, sw) != (16000, 1, 2):
        w.close()
        sys.exit("音频须为 16kHz/16bit/单声道（当前 %dHz/%dch/%dbyte）。转换：\n"
                 "  afconvert -f WAVE -d LEI16@16000 -c 1 in.wav %s" % (sr, ch, sw, wav_path))
    pcm = w.readframes(w.getnframes())
    w.close()
    return pcm


# ---------- WS 基础与命令实现 ----------

async def _ws_send_audio(uri, setup_msgs, pcm, tail_msg, on_event_done, wait_secs,
                         audio_mode="json"):
    """通用 WS 流程：连接 → setup → 音频帧 → 结束帧 → 收事件。

    audio_mode="json"   接口① realtime：{"type":"input_audio_buffer.append","audio":<base64>}
    audio_mode="binary" 接口② target-dialogue：直接发二进制 PCM 帧
    """
    async with websockets.connect(uri, max_size=16 * 1024 * 1024, open_timeout=20) as ws:
        done = asyncio.Event()

        async def recv():
            async for m in ws:
                try:
                    d = json.loads(m)
                except Exception:
                    print("RAW:", str(m)[:200])
                    continue
                t = d.get("type", "")
                text = d.get("text", d.get("delta", ""))
                if t in ("transcription.partial", "transcription.delta"):
                    print("  partial: %s" % text)
                else:
                    print("  EVT:", json.dumps(d, ensure_ascii=False)[:360])
                if t == on_event_done:
                    done.set()

        rt = asyncio.create_task(recv())
        try:
            for m in setup_msgs:
                await ws.send(m if isinstance(m, str) else json.dumps(m))
            CH = 3200  # 100ms
            for i in range(0, len(pcm), CH):
                if audio_mode == "json":
                    await ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(pcm[i:i + CH]).decode(),
                    }))
                else:
                    await ws.send(pcm[i:i + CH])
                await asyncio.sleep(0.03)
            await ws.send(json.dumps(tail_msg))
            try:
                await asyncio.wait_for(done.wait(), wait_secs)
            except asyncio.TimeoutError:
                print("  （等待 %ds 超时，停止收流）" % wait_secs)
        finally:
            rt.cancel()


def cmd_health(_):
    status, data = http_json("/asr/health")
    print("[/asr/health]", status, json.dumps(data, ensure_ascii=False))
    status, data = http_json("/health")
    if isinstance(data, dict):
        brief = {k: v.get("status") for k, v in data.get("services", {}).items()}
        print("[/health]", status, "overall=%s" % data.get("overall"), brief)
        print("ephemeral_auth:", json.dumps(data.get("ephemeral_auth", {}), ensure_ascii=False)[:200])


def cmd_asr(args):
    pcm = load_pcm(args.wav)
    print("== 接口① 流式转写 %s（%.1fs）==" % (args.wav, len(pcm) / 32000))
    uri = "%s/asr/v1/realtime?api_key=%s" % (BASE_WS, API_KEY)
    setup = [{"type": "session.update", "session": {"language": "auto"}}]
    tail = {"type": "input_audio_buffer.commit", "final": True}
    asyncio.run(_ws_send_audio(uri, setup, pcm, tail, "transcription.done", 40))


def get_token(resource="asr.target_dialogue"):
    status, data = http_json("/auth/v1/ephemeral-tokens", "POST",
                             {"resource": resource, "expires_in_seconds": 180,
                              "max_session_seconds": 180})
    if status != 200 or "access_token" not in data:
        sys.exit("签发 token 失败：%s %s" % (status, data))
    return data["access_token"]


def cmd_token(_):
    tok = get_token()
    with open("/tmp/amphion_token.txt", "w") as f:
        f.write(tok)
    print("access_token =", tok[:60] + "...（完整 token 已写入 /tmp/amphion_token.txt）")


def cmd_dialogue(args):
    pcm = load_pcm(args.wav)
    print("== 接口② 多人说话人分离（open 模式）%s（%.1fs）==" % (args.wav, len(pcm) / 32000))
    tok = get_token()
    uri = "%s/asr/v1/target-dialogue" % BASE_WS
    setup = [
        {"type": "session.authenticate", "access_token": tok},
        {"type": "session.update", "session": {
            "filter": {"mode": "open"},
            "participants": [],
            "audio": {"sample_rate_hz": 16000},
            "recognition": {"mode": "role_separation"},
        }},
    ]
    tail = {"type": "input_audio_buffer.commit", "final": True}
    asyncio.run(_ws_send_audio(uri, setup, pcm, tail, "session.done", 45,
                               audio_mode="binary"))


def cmd_enroll(args):
    with open(args.wav, "rb") as f:
        audio = f.read()
    body, ctype = multipart(
        {"display_name": args.name, "consent": "true"},
        {"audio": ("audio.wav", audio, "audio/wav")},
    )
    status, data = http_bytes("/speaker/v1/profiles", "POST", body, ctype)
    try:
        parsed = json.loads(data)
    except Exception:
        parsed = data[:500]
    print("== 接口② 声纹注册 ==", status)
    print(json.dumps(parsed, ensure_ascii=False, indent=2)[:800])


def cmd_voices(_):
    status, data = http_json("/tts/v1/audio/voices")
    print("== 接口③ 音色列表 ==", status)
    if isinstance(data, dict):
        for v in data.get("voices", []):
            print(" -", v)


def cmd_clone(args):
    with open(args.wav, "rb") as f:
        audio = f.read()
    body, ctype = multipart(
        {"voice_name": args.name},
        {"audio_file": (os.path.basename(args.wav), audio, "audio/wav")},
    )
    status, data = http_bytes("/tts/v1/audio/voices", "POST", body, ctype)
    try:
        parsed = json.loads(data)
    except Exception:
        parsed = data[:500]
    print("== 接口③ 音色复刻注册 ==", status)
    print(json.dumps(parsed, ensure_ascii=False, indent=2)[:900])


def cmd_speak(args):
    payload = {"model": "qwen-tts-0.6b", "input": args.text,
               "voice": args.voice, "response_format": "wav"}
    status, data = http_bytes("/tts/v1/audio/speech", "POST",
                              json.dumps(payload).encode(), "application/json")
    print("== 接口③ 克隆合成 ==", status, len(data), "bytes")
    if status == 200:
        with open(args.out, "wb") as f:
            f.write(data)
        print("已保存：%s（%d KB）" % (args.out, len(data) // 1024))
    else:
        print(data[:300])


def main():
    p = argparse.ArgumentParser(description="Amphion 三类语音接口本地 Demo")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health")
    sub.add_parser("token")
    sub.add_parser("voices")
    sp = sub.add_parser("asr"); sp.add_argument("wav")
    dp = sub.add_parser("dialogue"); dp.add_argument("wav")
    ep = sub.add_parser("enroll"); ep.add_argument("wav"); ep.add_argument("name")
    cp = sub.add_parser("clone"); cp.add_argument("wav"); cp.add_argument("name")
    kp = sub.add_parser("speak"); kp.add_argument("text"); kp.add_argument("voice")
    kp.add_argument("out", nargs="?", default="tts_out.wav")
    args = p.parse_args()
    {"health": cmd_health, "asr": cmd_asr, "dialogue": cmd_dialogue,
     "enroll": cmd_enroll, "token": cmd_token, "voices": cmd_voices,
     "clone": cmd_clone, "speak": cmd_speak}[args.cmd](args)


if __name__ == "__main__":
    main()
