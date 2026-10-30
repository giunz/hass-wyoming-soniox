"""Wyoming event handler: one instance per connection from Home Assistant."""

import logging
from typing import Optional

import aiohttp
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioChunkConverter, AudioStart, AudioStop
from wyoming.error import Error
from wyoming.event import Event
from wyoming.info import Describe, Info
from wyoming.server import AsyncEventHandler
from wyoming.tts import (
    Synthesize,
    SynthesizeChunk,
    SynthesizeStart,
    SynthesizeStop,
    SynthesizeStopped,
)

from .const import STT_CHANNELS, STT_RATE, STT_WIDTH, Settings
from .soniox_api import SonioxError, SttSession, synthesize
from .text import (
    chunk_text,
    clean_for_speech,
    detect_language,
    split_complete_sentences,
)

_LOGGER = logging.getLogger(__name__)


class SonioxEventHandler(AsyncEventHandler):
    """Handle speech-to-text and text-to-speech requests."""

    def __init__(
        self,
        wyoming_info: Info,
        settings: Settings,
        http: aiohttp.ClientSession,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._info_event = wyoming_info.event()
        self._settings = settings
        self._http = http

        # Speech-to-text state
        self._stt: Optional[SttSession] = None
        self._stt_language: Optional[str] = None
        self._converter = AudioChunkConverter(
            rate=STT_RATE, width=STT_WIDTH, channels=STT_CHANNELS
        )

        # Text-to-speech state
        self._streaming = False
        self._stream_buffer = ""
        self._stream_voice: Optional[str] = None
        self._stream_language: Optional[str] = None
        self._audio_started = False

    async def handle_event(self, event: Event) -> bool:
        if Describe.is_type(event.type):
            await self.write_event(self._info_event)
            return True

        if self._settings.stt_enabled:
            if Transcribe.is_type(event.type):
                transcribe = Transcribe.from_event(event)
                self._stt_language = transcribe.language
                await self._start_stt()
                return True
            if AudioStart.is_type(event.type):
                if self._stt is None:
                    await self._start_stt()
                return True
            if AudioChunk.is_type(event.type):
                if self._stt is None:
                    await self._start_stt()
                chunk = self._converter.convert(AudioChunk.from_event(event))
                self._stt.send_audio(chunk.audio)
                return True
            if AudioStop.is_type(event.type):
                await self._finish_stt()
                return True

        if self._settings.tts_enabled:
            if SynthesizeStart.is_type(event.type):
                start = SynthesizeStart.from_event(event)
                self._streaming = True
                self._stream_buffer = ""
                self._audio_started = False
                self._stream_voice = start.voice.name if start.voice else None
                self._stream_language = start.voice.language if start.voice else None
                return True
            if SynthesizeChunk.is_type(event.type):
                if not self._streaming:
                    return True
                self._stream_buffer += SynthesizeChunk.from_event(event).text
                sentences, self._stream_buffer = split_complete_sentences(
                    self._stream_buffer
                )
                for sentence in sentences:
                    if not await self._speak(
                        sentence, self._stream_voice, self._stream_language
                    ):
                        return False
                return True
            if Synthesize.is_type(event.type):
                if self._streaming:
                    # Home Assistant also sends the full text for older
                    # servers; it was already handled chunk by chunk.
                    return True
                return await self._synthesize_full(Synthesize.from_event(event))
            if SynthesizeStop.is_type(event.type):
                if not self._streaming:
                    return True
                rest = self._stream_buffer.strip()
                self._stream_buffer = ""
                ok = True
                if rest:
                    ok = await self._speak(
                        rest, self._stream_voice, self._stream_language
                    )
                if ok and self._audio_started:
                    await self.write_event(AudioStop().event())
                await self.write_event(SynthesizeStopped().event())
                self._streaming = False
                return ok

        return True

    async def disconnect(self) -> None:
        if self._stt is not None:
            await self._stt.cancel()
            self._stt = None

    # ------------------------------------------------------------------
    # Speech-to-text

    async def _start_stt(self) -> None:
        if self._stt is not None:
            await self._stt.cancel()
        self._converter = AudioChunkConverter(
            rate=STT_RATE, width=STT_WIDTH, channels=STT_CHANNELS
        )
        self._stt = SttSession(self._http, self._settings, self._stt_language)
        _LOGGER.debug("STT started, language hints %s", self._stt.language_hints)

    async def _finish_stt(self) -> None:
        if self._stt is None:
            await self.write_event(Transcript(text="").event())
            return
        stt, self._stt = self._stt, None
        try:
            text = await stt.finish()
        except SonioxError as err:
            _LOGGER.error("Speech-to-text failed: %s", err)
            text = ""
        except Exception:  # noqa: BLE001 - never leave Home Assistant waiting
            _LOGGER.exception("Unexpected speech-to-text error")
            text = ""
        finally:
            await stt.cancel()
        _LOGGER.debug("Transcript: %s", text)
        await self.write_event(
            Transcript(text=text, language=self._stt_language).event()
        )

    # ------------------------------------------------------------------
    # Text-to-speech

    async def _synthesize_full(self, request: Synthesize) -> bool:
        voice = request.voice.name if request.voice else None
        language = request.voice.language if request.voice else None
        self._audio_started = False
        # Clean before chunking: list markers are only recognisable at the
        # start of a line, and chunking joins lines.
        for piece in chunk_text(clean_for_speech(request.text)):
            if not await self._speak(piece, voice, language):
                return False
        if not self._audio_started:
            await self._write_audio_start()
        await self.write_event(AudioStop().event())
        return True

    async def _speak(
        self, text: str, voice: Optional[str], language: Optional[str]
    ) -> bool:
        """Synthesize one piece of text; returns False on failure."""
        text = clean_for_speech(text)
        if not text:
            return True
        voice = voice or self._settings.voice
        language = (
            language.split("-")[0].lower()
            if language
            else detect_language(text, self._settings.tts_default_language)
        )
        _LOGGER.debug("TTS %s/%s: %s", voice, language, text)
        try:
            async for pcm in synthesize(
                self._http, self._settings, text, voice, language
            ):
                if not self._audio_started:
                    await self._write_audio_start()
                await self.write_event(
                    AudioChunk(
                        rate=self._settings.tts_sample_rate,
                        width=2,
                        channels=1,
                        audio=pcm,
                    ).event()
                )
        except SonioxError as err:
            _LOGGER.error("Text-to-speech failed: %s", err)
            await self.write_event(Error(text=str(err), code="soniox-tts").event())
            return False
        return True

    async def _write_audio_start(self) -> None:
        self._audio_started = True
        await self.write_event(
            AudioStart(rate=self._settings.tts_sample_rate, width=2, channels=1).event()
        )
