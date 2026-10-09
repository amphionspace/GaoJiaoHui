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

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

UPSTREAM = "https://amphion.top"
UPSTREAM_HOST = "amphion.top"
# 应急开关：本机代理（Surge/Clash 增强模式 Fake-IP 198.18.x.x）链路故障时，
# 设 UPSTREAM_IP=106.52.52.196 可绕过本机 DNS 直连上游真实 IP（Host/SNI 仍用域名，证书校验不变）
UPSTREAM_IP = os.environ.get("UPSTREAM_IP", "").strip()
# cn-test 迁移期（2026-10-09 发现）：amphion.top DNS 已切国内新集群，/tts/v1/* 路由未迁移
# （返回 route_not_migrated），仍存活在 legacy 网关 106.52.52.196（Host/SNI 仍用 amphion.top）。
# /proxy 对 tts/* 路径自动分流到 legacy；其余（ASR WS 认证 / 声纹档案）走 DNS 新集群。
LEGACY_TTS_IP = os.environ.get("LEGACY_TTS_IP", "106.52.52.196").strip()
PORT = int(os.environ.get("PORT", "8766"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "frontend", "dist")
HOP_HEADERS = {"host", "connection", "content-length", "transfer-encoding",
               "accept-encoding", "origin", "referer", "user-agent"}

app = FastAPI(title="Amphion Demo Server")


@app.api_route("/proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(path: str, request: Request):
    use_ip = UPSTREAM_IP or (LEGACY_TTS_IP if path.startswith(("tts/", "asr/health")) else "")
    target = f"https://{use_ip}/{path}" if use_ip else f"{UPSTREAM}/{path}"
    if request.url.query:
        target += "?" + request.url.query
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}
    ext = {"sni_hostname": UPSTREAM_HOST} if use_ip else None
    if use_ip:
        headers["host"] = UPSTREAM_HOST   # host 已被剥离，直连 IP 时必须补回，网关按 Host 路由
    body = await request.body()
    async with httpx.AsyncClient(timeout=300) as client:
        try:
            r = await client.request(request.method, target, headers=headers,
                                     content=body or None, extensions=ext)
        except Exception as e:  # 网络错误等
            msg = f"{type(e).__name__}: {str(e) or '（无错误消息）'}"
            print(f"[proxy] {request.method} {target} -> {msg}", flush=True)
            return Response(content=f'{{"detail":"proxy error: {msg[:200]}"}}',
                            status_code=502, media_type="application/json")
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("Content-Type", "application/octet-stream"))


@app.get("/api/config")
async def config():
    """前端运行时配置（示例：上游地址），便于后续将 Key 移到服务端注入。"""
    return {"upstream": UPSTREAM}


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
    print(f"Amphion Demo Server (FastAPI) -> http://localhost:{PORT}/  (/proxy -> {UPSTREAM})")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")  # 0.0.0.0：同一 Wi-Fi 下手机/iPad 可用本机 IP 访问
