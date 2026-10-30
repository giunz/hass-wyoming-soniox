"""Check the bridge against the real Soniox API, the way Home Assistant uses it.

Usage (from the repository root):

    python -m venv .venv && .venv/bin/pip install -r soniox/requirements.txt
    SONIOX_API_KEY=... .venv/bin/python scripts/live_check.py --region us

It starts the bridge, lists the voices, speaks one English and one Greek
sentence (saved as live_en.wav / live_el.wav so you can listen), then sends
that audio back through speech-to-text and prints the transcripts. The API
key is read from SONIOX_API_KEY and never printed. Cost: well under one cent.
"""

import argparse
import asyncio
import os
import socket
import sys
import time
import wave
from pathlib import Path

from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioChunkConverter, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient
from wyoming.error import Error
from wyoming.info import Describe, Info
from wyoming.tts import Synthesize, SynthesizeVoice

SRC = Path(__file__).resolve().parent.parent / "soniox"
SENTENCES = {
    "en": "Turn on the kitchen lights and set the temperature to twenty one degrees.",
    "el": "Άναψε τα φώτα στην κουζίνα και βάλε τη θερμοκρασία στους είκοσι ένα βαθμούς.",
}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _tts(port: int, text: str, voice: str):
    started = time.monotonic()
    first_audio = None
    audio = bytearray()
    rate = None
    async with AsyncTcpClient("127.0.0.1", port) as client:
        await client.write_event(Synthesize(text=text, voice=SynthesizeVoice(name=voice)).event())
        while True:
            event = await asyncio.wait_for(client.read_event(), 30)
            if event is None:
                raise RuntimeError("bridge closed the connection")
            if Error.is_type(event.type):
                raise RuntimeError(Error.from_event(event).text)
            if AudioStart.is_type(event.type):
                rate = AudioStart.from_event(event).rate
            elif AudioChunk.is_type(event.type):
                first_audio = first_audio or time.monotonic() - started
                audio += AudioChunk.from_event(event).audio
            elif AudioStop.is_type(event.type):
                break
    return bytes(audio), rate, first_audio, time.monotonic() - started


async def _stt(port: int, pcm: bytes, rate: int, language: str):
    converter = AudioChunkConverter(rate=16000, width=2, channels=1)
    chunk = converter.convert(AudioChunk(rate=rate, width=2, channels=1, audio=pcm))
    audio = chunk.audio
    async with AsyncTcpClient("127.0.0.1", port) as client:
        await client.write_event(Transcribe(language=language).event())
        await client.write_event(AudioStart(rate=16000, width=2, channels=1).event())
        step = 16000 * 2 // 10  # 100 ms, sent in real time like a microphone
        for i in range(0, len(audio), step):
            await client.write_event(
                AudioChunk(rate=16000, width=2, channels=1, audio=audio[i : i + step]).event()
            )
            await asyncio.sleep(0.1)
        stopped = time.monotonic()
        await client.write_event(AudioStop().event())
        while True:
            event = await asyncio.wait_for(client.read_event(), 30)
            if event is None:
                raise RuntimeError("bridge closed the connection")
            if Transcript.is_type(event.type):
                return Transcript.from_event(event).text, time.monotonic() - stopped


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default="eu", choices=["eu", "us", "jp"])
    parser.add_argument("--voice", default="Adrian")
    parser.add_argument("bridge_args", nargs="*", help="Extra bridge arguments, after --")
    args = parser.parse_args()
    if not os.environ.get("SONIOX_API_KEY"):
        print("Set SONIOX_API_KEY first.")
        return 2

    port = _free_port()
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "wyoming_soniox",
        "--uri", f"tcp://127.0.0.1:{port}", "--region", args.region,
        *args.bridge_args, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    failures = 0
    try:
        for _ in range(100):
            try:
                _, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.close()
                break
            except OSError:
                await asyncio.sleep(0.1)
        else:
            raise RuntimeError("bridge did not start")

        async with AsyncTcpClient("127.0.0.1", port) as client:
            await client.write_event(Describe().event())
            info = Info.from_event(await asyncio.wait_for(client.read_event(), 10))
        voices = [v.name for v in info.tts[0].voices] if info.tts else []
        print(f"Voices ({len(voices)}): {', '.join(voices)}")

        for lang, text in SENTENCES.items():
            print(f"\n[{lang}] TTS: {text}")
            try:
                pcm, rate, first, total = await _tts(port, text, args.voice)
                path = Path(f"live_{lang}.wav")
                with wave.open(str(path), "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(rate)
                    wav.writeframes(pcm)
                print(f"  OK: {len(pcm) / 2 / rate:.1f}s of audio at {rate} Hz, "
                      f"first audio after {first:.2f}s, done after {total:.2f}s -> {path}")
            except Exception as err:  # noqa: BLE001
                failures += 1
                print(f"  FAILED: {err}")
                continue

            try:
                transcript, latency = await _stt(port, pcm, rate, lang)
                ok = bool(transcript)
                failures += 0 if ok else 1
                print(f"  STT {'OK' if ok else 'EMPTY'} ({latency:.2f}s after audio-stop): {transcript!r}")
            except Exception as err:  # noqa: BLE001
                failures += 1
                print(f"  STT FAILED: {err}")
    finally:
        proc.terminate()
        out = (await proc.stdout.read()).decode(errors="replace")
        await proc.wait()
        warnings = [l for l in out.splitlines() if " WARNING " in l or " ERROR " in l]
        if warnings:
            print("\nBridge log warnings/errors:")
            print("\n".join(warnings))

    print("\nAll checks passed." if not failures else f"\n{failures} check(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
