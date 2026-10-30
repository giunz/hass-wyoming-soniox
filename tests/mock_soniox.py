"""A fake Soniox server that follows the documented STT/TTS protocols."""

import asyncio
import json
import math
import struct

from aiohttp import WSMsgType, web

GOOD_KEY = "test-key"


class MockSoniox:
    def __init__(self) -> None:
        self.stt_sessions = []  # dicts: headers, config, audio_bytes, ended_with_empty_text
        self.tts_requests = []
        self.app = web.Application()
        self.app.router.add_get("/transcribe-websocket", self.stt)
        self.app.router.add_post("/tts", self.tts)
        self.app.router.add_get("/v1/tts-models", self.models)
        self.runner = None
        self.port = None

    async def start(self) -> None:
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        await self.runner.cleanup()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def stt(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        record = {
            "auth": request.headers.get("Authorization"),
            "config": None,
            "audio_bytes": 0,
            "ended_with_empty_text": False,
        }
        self.stt_sessions.append(record)

        if record["auth"] != f"Bearer {GOOD_KEY}":
            await ws.send_str(json.dumps({
                "tokens": [], "error_code": 401, "error_type": "unauthenticated",
                "error_message": "Incorrect API key provided.", "request_id": "r1",
            }))
            await ws.close()
            return ws

        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                if record["config"] is None:
                    record["config"] = json.loads(msg.data)
                    continue
                if msg.data == "":
                    record["ended_with_empty_text"] = True
                    break
            elif msg.type == WSMsgType.BINARY:
                record["audio_bytes"] += len(msg.data)
                # Stream a non-final guess like the real service does.
                await ws.send_str(json.dumps({
                    "tokens": [{"text": "Tur", "is_final": False}],
                    "final_audio_proc_ms": 0, "total_audio_proc_ms": 100,
                }))

        if record["audio_bytes"] == 0:
            await ws.send_str(json.dumps({
                "tokens": [], "error_code": 400, "error_type": "invalid_request",
                "error_message": "No audio received.", "request_id": "r2",
            }))
            await ws.close()
            return ws

        greek = record["config"]["language_hints"][0] == "el"
        words = ["Άναψε", " το", " φως", " στην", " κουζίνα"] if greek else \
                ["Turn", " on", " the", " kitchen", " light", "."]
        # Final tokens split over two messages, then the endpoint marker.
        await ws.send_str(json.dumps({
            "tokens": [{"text": w, "is_final": True} for w in words[:2]],
            "final_audio_proc_ms": 500, "total_audio_proc_ms": 600,
        }))
        await ws.send_str(json.dumps({
            "tokens": [{"text": w, "is_final": True} for w in words[2:]]
                      + [{"text": "<end>", "is_final": True}],
            "final_audio_proc_ms": 900, "total_audio_proc_ms": 900,
        }))
        await ws.send_str(json.dumps({
            "tokens": [], "final_audio_proc_ms": 900,
            "total_audio_proc_ms": 900, "finished": True,
        }))
        await ws.close()
        return ws

    async def tts(self, request: web.Request) -> web.StreamResponse:
        body = await request.json()
        self.tts_requests.append({"auth": request.headers.get("Authorization"), **body})
        if request.headers.get("Authorization") != f"Bearer {GOOD_KEY}":
            return web.json_response(
                {"error_code": 401, "error_type": "unauthenticated",
                 "error_message": "Incorrect API key provided.", "request_id": "r3"},
                status=401,
            )
        rate = body["sample_rate"]
        # 0.05 s of tone per character.
        samples = int(rate * 0.05 * len(body["text"]))
        pcm = b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(samples)
        )
        resp = web.StreamResponse(headers={"Content-Type": "audio/pcm"})
        await resp.prepare(request)
        # Odd-sized pieces, so the bridge must re-align 16-bit samples.
        for i in range(0, len(pcm), 1001):
            await resp.write(pcm[i:i + 1001])
            await asyncio.sleep(0)
        await resp.write_eof()
        return resp

    async def models(self, request: web.Request) -> web.Response:
        return web.json_response({"models": [{
            "id": "tts-rt-v2", "name": "TTS v2", "aliased_model_id": None,
            "languages": [{"code": "en", "name": "English"}, {"code": "el", "name": "Greek"}],
            "voices": [
                {"id": "Adrian", "description": "Calm, warm male voice", "gender": "male"},
                {"id": "Maya", "description": "Bright female voice", "gender": "female"},
            ],
        }]})
