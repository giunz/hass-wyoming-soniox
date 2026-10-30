"""End-to-end tests: real bridge process, real Wyoming TCP client, fake Soniox.

The client side copies the event order Home Assistant's Wyoming integration
uses (homeassistant/components/wyoming/stt.py and tts.py, 2026.2).
"""

import asyncio
import math
import os
import socket
import struct
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient
from wyoming.error import Error
from wyoming.info import Describe, Info
from wyoming.tts import (
    Synthesize,
    SynthesizeChunk,
    SynthesizeStart,
    SynthesizeStop,
    SynthesizeStopped,
    SynthesizeVoice,
)

from mock_soniox import GOOD_KEY, MockSoniox

SRC = Path(__file__).resolve().parents[1] / "soniox"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest_asyncio.fixture
async def mock():
    server = MockSoniox()
    await server.start()
    yield server
    await server.stop()


async def _start_bridge(mock: MockSoniox, key: str = GOOD_KEY, *extra: str):
    port = _free_port()
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    for proxy in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env.pop(proxy, None)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "wyoming_soniox",
        "--uri", f"tcp://127.0.0.1:{port}",
        "--api-key", key,
        "--stt-url", f"ws://127.0.0.1:{mock.port}/transcribe-websocket",
        "--tts-url", f"{mock.base}/tts",
        "--api-url", mock.base,
        "--debug", *extra,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    for _ in range(100):
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            break
        except OSError:
            await asyncio.sleep(0.1)
    else:
        proc.kill()
        out = await proc.stdout.read()
        raise RuntimeError(out.decode())
    return proc, port


@pytest_asyncio.fixture
async def bridge(mock):
    proc, port = await _start_bridge(mock)
    yield port
    proc.terminate()
    await proc.wait()


def _tone(rate: int, seconds: float, channels: int = 1) -> bytes:
    out = []
    for i in range(int(rate * seconds)):
        sample = struct.pack("<h", int(6000 * math.sin(2 * math.pi * 300 * i / rate)))
        out.append(sample * channels)
    return b"".join(out)


async def _read_until(client: AsyncTcpClient, stop_type: str, timeout: float = 10):
    events = []
    async with asyncio.timeout(timeout):
        while True:
            event = await client.read_event()
            assert event is not None, "connection closed early"
            events.append(event)
            if event.type == stop_type:
                return events


async def _transcribe(port, language, audio, rate=16000, channels=1):
    async with AsyncTcpClient("127.0.0.1", port) as client:
        await client.write_event(Transcribe(language=language).event())
        await client.write_event(AudioStart(rate=rate, width=2, channels=channels).event())
        step = rate * 2 * channels // 50  # 20 ms chunks
        for i in range(0, len(audio), step):
            await client.write_event(
                AudioChunk(rate=rate, width=2, channels=channels, audio=audio[i:i + step]).event()
            )
        await client.write_event(AudioStop().event())
        events = await _read_until(client, "transcript")
        return Transcript.from_event(events[-1])


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe(bridge):
    async with AsyncTcpClient("127.0.0.1", bridge) as client:
        await client.write_event(Describe().event())
        events = await _read_until(client, "info")
    info = Info.from_event(events[-1])  # same parser Home Assistant uses
    assert info.asr[0].installed and info.tts[0].installed
    assert {"en", "el"} <= set(info.asr[0].models[0].languages)
    voices = [v.name for v in info.tts[0].voices]
    assert voices == ["Adrian", "Maya"]  # fetched from the (mock) API
    assert "Calm, warm" in info.tts[0].voices[0].description
    assert info.tts[0].supports_synthesize_streaming


@pytest.mark.asyncio
async def test_stt_english(bridge, mock):
    result = await _transcribe(bridge, "en", _tone(16000, 1.0))
    assert result.text == "Turn on the kitchen light."
    session = mock.stt_sessions[-1]
    assert session["auth"] == f"Bearer {GOOD_KEY}"
    assert session["config"] == {
        "model": "stt-rt-v5", "audio_format": "pcm_s16le", "sample_rate": 16000,
        "num_channels": 1, "language_hints": ["en", "el"],
    }
    assert session["audio_bytes"] == 32000
    assert session["ended_with_empty_text"]


@pytest.mark.asyncio
async def test_stt_greek_puts_greek_hint_first(bridge, mock):
    result = await _transcribe(bridge, "el-GR", _tone(16000, 0.5))
    assert result.text == "Άναψε το φως στην κουζίνα"
    assert mock.stt_sessions[-1]["config"]["language_hints"] == ["el", "en"]


@pytest.mark.asyncio
async def test_stt_converts_48k_stereo(bridge, mock):
    await _transcribe(bridge, "en", _tone(48000, 1.0, channels=2), rate=48000, channels=2)
    # 1 s of 16 kHz mono 16-bit is 32000 bytes; resampling may shift a few.
    assert abs(mock.stt_sessions[-1]["audio_bytes"] - 32000) < 64


@pytest.mark.asyncio
async def test_stt_no_audio_returns_empty(bridge):
    result = await _transcribe(bridge, "en", b"")
    assert result.text == ""


@pytest.mark.asyncio
async def test_stt_bad_key_returns_empty_quickly(mock):
    proc, port = await _start_bridge(mock, "wrong-key")
    try:
        start = asyncio.get_running_loop().time()
        result = await _transcribe(port, "en", _tone(16000, 0.3))
        assert result.text == ""
        assert asyncio.get_running_loop().time() - start < 5
    finally:
        proc.terminate()
        out = (await proc.communicate())[0].decode()
    assert "Incorrect API key" in out
    assert "wrong-key" not in out  # never log the key


@pytest.mark.asyncio
async def test_tts_full_message_like_home_assistant(bridge, mock):
    text = "Η θερμοκρασία είναι 21 βαθμοί."
    async with AsyncTcpClient("127.0.0.1", bridge) as client:
        await client.write_event(Synthesize(text=text, voice=SynthesizeVoice(name="Maya")).event())
        events = await _read_until(client, "audio-stop")
    assert events[0].type == "audio-start"
    start = AudioStart.from_event(events[0])
    assert (start.rate, start.width, start.channels) == (24000, 2, 1)
    chunks = [AudioChunk.from_event(e) for e in events if e.type == "audio-chunk"]
    total = sum(len(c.audio) for c in chunks)
    assert all(len(c.audio) % 2 == 0 for c in chunks)
    assert total == int(24000 * 0.05 * len(text)) * 2
    req = mock.tts_requests[-1]
    assert (req["language"], req["voice"], req["model"]) == ("el", "Maya", "tts-rt-v2")
    assert req["audio_format"] == "pcm_s16le" and req["sample_rate"] == 24000


@pytest.mark.asyncio
async def test_tts_default_voice_and_english_detection(bridge, mock):
    async with AsyncTcpClient("127.0.0.1", bridge) as client:
        await client.write_event(Synthesize(text="The door is locked.").event())
        await _read_until(client, "audio-stop")
    req = mock.tts_requests[-1]
    assert (req["language"], req["voice"]) == ("en", "Adrian")


@pytest.mark.asyncio
async def test_tts_streaming_like_home_assistant(bridge, mock):
    """HA order: SynthesizeStart, chunks, full Synthesize, SynthesizeStop."""
    pieces = ["Hello there. How", " are you? I am", " fine"]
    async with AsyncTcpClient("127.0.0.1", bridge) as client:
        await client.write_event(SynthesizeStart(voice=SynthesizeVoice(name="Adrian")).event())
        for piece in pieces:
            await client.write_event(SynthesizeChunk(text=piece).event())
        await client.write_event(Synthesize(text="".join(pieces), voice=SynthesizeVoice(name="Adrian")).event())
        await client.write_event(SynthesizeStop().event())
        events = await _read_until(client, "synthesize-stopped")
    types = [e.type for e in events]
    assert types[0] == "audio-start" and types.count("audio-start") == 1
    assert types[-2:] == ["audio-stop", "synthesize-stopped"]
    sent = [r["text"] for r in mock.tts_requests]
    assert sent == ["Hello there.", "How are you?", "I am fine"]  # no duplicate full text


@pytest.mark.asyncio
async def test_tts_bad_key_reports_error(mock):
    proc, port = await _start_bridge(mock, "wrong-key")
    try:
        async with AsyncTcpClient("127.0.0.1", port) as client:
            await client.write_event(Synthesize(text="Hello.").event())
            async with asyncio.timeout(5):
                event = await client.read_event()
                assert Error.is_type(event.type)
                assert "401" in Error.from_event(event).text
                # Bridge then closes the connection, which HA treats as a failure.
                assert await client.read_event() is None
    finally:
        proc.terminate()
        await proc.wait()


@pytest.mark.asyncio
async def test_falls_back_to_static_voices_when_api_down(mock):
    proc, port = await _start_bridge(mock, GOOD_KEY, "--api-url", "http://127.0.0.1:1")
    try:
        async with AsyncTcpClient("127.0.0.1", port) as client:
            await client.write_event(Describe().event())
            events = await _read_until(client, "info")
        voices = [v.name for v in Info.from_event(events[-1]).tts[0].voices]
        assert "Adrian" in voices and len(voices) >= 3
    finally:
        proc.terminate()
        await proc.wait()


@pytest.mark.asyncio
async def test_stt_realtime_pacing_and_reuse(bridge, mock):
    """Audio at real-time speed, then a second request on a new connection."""
    audio = _tone(16000, 0.6)
    async with AsyncTcpClient("127.0.0.1", bridge) as client:
        await client.write_event(Transcribe(language="en").event())
        await client.write_event(AudioStart(rate=16000, width=2, channels=1).event())
        for i in range(0, len(audio), 640):
            await client.write_event(AudioChunk(rate=16000, width=2, channels=1, audio=audio[i:i + 640]).event())
            await asyncio.sleep(0.02)
        await client.write_event(AudioStop().event())
        events = await _read_until(client, "transcript")
    assert Transcript.from_event(events[-1]).text.startswith("Turn on")
    result = await _transcribe(bridge, "el", _tone(16000, 0.3))
    assert result.text.startswith("Άναψε")
    assert len(mock.stt_sessions) == 2


@pytest.mark.asyncio
async def test_long_message_split_into_requests(bridge, mock):
    text = " ".join(f"Sentence number {i} is here." for i in range(80))  # ~2200 chars
    async with AsyncTcpClient("127.0.0.1", bridge) as client:
        await client.write_event(Synthesize(text=text).event())
        events = await _read_until(client, "audio-stop", timeout=30)
    assert [e.type for e in events].count("audio-start") == 1
    assert len(mock.tts_requests) >= 3
    assert all(len(r["text"]) <= 1000 for r in mock.tts_requests)
    assert " ".join(r["text"] for r in mock.tts_requests) == text


@pytest.mark.asyncio
async def test_tts_markdown_is_not_spoken(bridge, mock):
    text = "**Done.** The *kitchen* light is on.\n1. Lamp"
    async with AsyncTcpClient("127.0.0.1", bridge) as client:
        await client.write_event(Synthesize(text=text).event())
        await _read_until(client, "audio-stop")
    sent = " ".join(r["text"] for r in mock.tts_requests)
    assert "*" not in sent
    assert sent == "Done. The kitchen light is on. Lamp"


@pytest.mark.asyncio
async def test_synthesize_total_timeout_becomes_soniox_error(monkeypatch):
    """aiohttp raises a plain TimeoutError on total timeout; it must be wrapped."""
    import aiohttp
    from aiohttp import web

    from wyoming_soniox import soniox_api
    from wyoming_soniox.const import Settings

    async def slow(request):
        resp = web.StreamResponse()
        await resp.prepare(request)
        await resp.write(b"\0\0")
        await asyncio.sleep(3)
        return resp

    app = web.Application()
    app.router.add_post("/tts", slow)
    runner = web.AppRunner(app)
    await runner.setup()
    port = _free_port()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    real_timeout = aiohttp.ClientTimeout
    monkeypatch.setattr(
        soniox_api.aiohttp, "ClientTimeout", lambda **kw: real_timeout(total=0.5)
    )
    settings = Settings(api_key="k", tts_url=f"http://127.0.0.1:{port}/tts")
    try:
        async with aiohttp.ClientSession() as http:
            with pytest.raises(soniox_api.SonioxError):
                async for _ in soniox_api.synthesize(http, settings, "Hi.", "Adrian", "en"):
                    pass
    finally:
        await runner.cleanup()
