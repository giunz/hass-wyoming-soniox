"""Entry point: python -m wyoming_soniox --uri tcp://0.0.0.0:10300"""

import argparse
import asyncio
import logging
import os
import sys
from functools import partial
from pathlib import Path

import aiohttp
from wyoming.info import (
    AsrModel,
    AsrProgram,
    Attribution,
    Info,
    TtsProgram,
    TtsVoice,
)
from wyoming.server import AsyncServer

from . import __version__
from .const import FALLBACK_VOICES, LANGUAGES, REGION_DOMAINS, TTS_SAMPLE_RATES, Settings
from .handler import SonioxEventHandler
from .soniox_api import fetch_voices

_LOGGER = logging.getLogger("wyoming_soniox")
_ATTRIBUTION = Attribution(name="Soniox", url="https://soniox.com")


def _csv(value: str) -> list:
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_args(argv=None) -> argparse.Namespace:
    env = os.environ.get
    parser = argparse.ArgumentParser(prog="wyoming_soniox")
    parser.add_argument("--uri", default="tcp://0.0.0.0:10300", help="Wyoming server URI")
    parser.add_argument("--api-key", default=env("SONIOX_API_KEY"), help="Soniox API key (or SONIOX_API_KEY)")
    parser.add_argument("--api-key-file", help="Read the API key from this file")
    parser.add_argument("--region", default=env("SONIOX_REGION", "eu"), choices=sorted(REGION_DOMAINS))
    parser.add_argument("--stt-model", default="stt-rt-v5")
    parser.add_argument("--tts-model", default="tts-rt-v2")
    parser.add_argument("--voice", default="Adrian", help="Default TTS voice")
    parser.add_argument("--language-hints", type=_csv, default=["en", "el"], help="Comma-separated, e.g. en,el")
    parser.add_argument("--tts-default-language", default="en", help="TTS language for non-Greek text")
    parser.add_argument("--tts-sample-rate", type=int, default=24000, choices=TTS_SAMPLE_RATES)
    parser.add_argument("--tts-speed", type=float, default=1.0, help="0.7 to 1.3")
    parser.add_argument("--voices", type=_csv, default=None, help="Only advertise these voices")
    parser.add_argument("--no-stt", action="store_true", help="Disable speech-to-text")
    parser.add_argument("--no-tts", action="store_true", help="Disable text-to-speech")
    parser.add_argument("--stt-url", help=argparse.SUPPRESS)
    parser.add_argument("--tts-url", help=argparse.SUPPRESS)
    parser.add_argument("--api-url", help=argparse.SUPPRESS)
    parser.add_argument("--debug", action="store_true", help="Log debug messages (includes transcripts)")
    args = parser.parse_args(argv)

    if args.api_key_file:
        args.api_key = Path(args.api_key_file).read_text(encoding="utf-8").strip()
    if not args.api_key:
        parser.error("A Soniox API key is required (--api-key or SONIOX_API_KEY)")
    if not 0.7 <= args.tts_speed <= 1.3:
        parser.error("--tts-speed must be between 0.7 and 1.3")
    if args.no_stt and args.no_tts:
        parser.error("Both speech-to-text and text-to-speech are disabled")
    return args


async def build_info(settings: Settings, http: aiohttp.ClientSession, only_voices) -> Info:
    voices = []
    if settings.tts_enabled:
        try:
            voices = await fetch_voices(http, settings)
            _LOGGER.info("Loaded %d voices from Soniox", len(voices))
        except Exception as err:  # noqa: BLE001 - fall back to a static list
            _LOGGER.warning("Could not load the voice list (%s); using defaults", err)
        if not voices:
            voices = [{"id": name, "description": None} for name in FALLBACK_VOICES]

    names = [v["id"] for v in voices]
    if settings.voice not in names:
        # A cloned voice ID, or a name missing from the list.
        voices.insert(0, {"id": settings.voice, "description": None})
    if only_voices:
        keep = set(only_voices) | {settings.voice}
        voices = [v for v in voices if v["id"] in keep]

    def label(v: dict) -> str:
        description = (v.get("description") or "").strip()
        return f"{v['id']} – {description}" if description else v["id"]

    asr = []
    if settings.stt_enabled:
        asr.append(
            AsrProgram(
                name="Soniox",
                description="Soniox speech-to-text (cloud, real-time)",
                attribution=_ATTRIBUTION,
                installed=True,
                version=__version__,
                models=[
                    AsrModel(
                        name=settings.stt_model,
                        description=f"Soniox {settings.stt_model}",
                        attribution=_ATTRIBUTION,
                        installed=True,
                        version=None,
                        languages=LANGUAGES,
                    )
                ],
            )
        )

    tts = []
    if settings.tts_enabled:
        tts.append(
            TtsProgram(
                name="Soniox",
                description="Soniox text-to-speech (cloud)",
                attribution=_ATTRIBUTION,
                installed=True,
                version=__version__,
                supports_synthesize_streaming=True,
                voices=[
                    TtsVoice(
                        name=v["id"],
                        description=label(v),
                        attribution=_ATTRIBUTION,
                        installed=True,
                        version=None,
                        languages=LANGUAGES,
                    )
                    for v in voices
                ],
            )
        )
    return Info(asr=asr, tts=tts)


async def main(argv=None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    if not args.debug:
        logging.getLogger("aiohttp").setLevel(logging.WARNING)

    settings = Settings(
        api_key=args.api_key,
        region=args.region,
        stt_model=args.stt_model,
        tts_model=args.tts_model,
        voice=args.voice,
        language_hints=args.language_hints,
        tts_default_language=args.tts_default_language,
        tts_sample_rate=args.tts_sample_rate,
        tts_speed=args.tts_speed,
        stt_enabled=not args.no_stt,
        tts_enabled=not args.no_tts,
        stt_url=args.stt_url,
        tts_url=args.tts_url,
        api_url=args.api_url,
    )

    async with aiohttp.ClientSession() as http:
        info = await build_info(settings, http, args.voices)
        _LOGGER.info(
            "Soniox bridge %s ready on %s (region %s, STT %s, TTS %s)",
            __version__,
            args.uri,
            settings.region,
            "on" if settings.stt_enabled else "off",
            "on" if settings.tts_enabled else "off",
        )
        server = AsyncServer.from_uri(args.uri)
        await server.run(partial(SonioxEventHandler, info, settings, http))


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
