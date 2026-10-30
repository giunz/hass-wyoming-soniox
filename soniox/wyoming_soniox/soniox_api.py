"""Clients for the Soniox real-time STT WebSocket and TTS REST APIs."""

import asyncio
import json
import logging
import re
from typing import AsyncIterator, List, Optional

import aiohttp

from .const import STT_CHANNELS, STT_RATE, Settings

_LOGGER = logging.getLogger(__name__)

# Control markers such as <end> (endpoint detection) are not spoken words.
_CONTROL_TOKEN = re.compile(r"^\s*<[a-z_]+>\s*$")


class SonioxError(Exception):
    """Error reported by Soniox or while talking to it."""


def _describe_error(data: dict) -> str:
    return (
        f"{data.get('error_code')} {data.get('error_type', '')}: "
        f"{data.get('error_message', '')} (request {data.get('request_id', '?')})"
    )


class SttSession:
    """One real-time transcription stream.

    The WebSocket opens as soon as the session is created, so the connection
    is set up while the person is still speaking. Audio sent before it is
    ready is queued.
    """

    def __init__(
        self, http: aiohttp.ClientSession, settings: Settings, language: Optional[str]
    ) -> None:
        self._http = http
        self._settings = settings
        self._queue: "asyncio.Queue[Optional[bytes]]" = asyncio.Queue()
        self._final_text: List[str] = []
        self._hints = _language_hints(language, settings.language_hints)
        self._task = asyncio.create_task(self._run())

    @property
    def language_hints(self) -> List[str]:
        return self._hints

    def send_audio(self, pcm: bytes) -> None:
        if pcm:
            self._queue.put_nowait(pcm)

    async def finish(self) -> str:
        """Signal end of audio and wait for the final transcript."""
        self._queue.put_nowait(None)
        try:
            await asyncio.wait_for(self._task, self._settings.stt_finish_timeout)
        except asyncio.TimeoutError as err:
            raise SonioxError("Timed out waiting for the final transcript") from err
        return _join_tokens(self._final_text)

    async def cancel(self) -> None:
        if not self._task.done():
            self._task.cancel()
        try:
            await self._task
        except BaseException:  # noqa: BLE001 - closing down, errors are moot
            pass

    async def _run(self) -> None:
        config = {
            "model": self._settings.stt_model,
            "audio_format": "pcm_s16le",
            "sample_rate": STT_RATE,
            "num_channels": STT_CHANNELS,
            "language_hints": self._hints,
        }
        try:
            ws = await self._http.ws_connect(
                self._settings.stt_url,
                headers=self._settings.auth_headers,
                heartbeat=None,
                autoping=True,
                timeout=aiohttp.ClientWSTimeout(ws_close=5),
            )
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise SonioxError(f"Could not connect to Soniox STT: {err}") from err

        async with ws:
            await ws.send_str(json.dumps(config))
            reader = asyncio.create_task(self._read(ws))
            try:
                while True:
                    getter = asyncio.ensure_future(self._queue.get())
                    done, _ = await asyncio.wait(
                        {getter, reader}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if reader in done:
                        # Soniox ended the stream early (usually an error).
                        getter.cancel()
                        break
                    chunk = getter.result()
                    if chunk is None:
                        # An empty text frame ends the stream.
                        await ws.send_str("")
                        break
                    await ws.send_bytes(chunk)
                await reader
            finally:
                if not reader.done():
                    reader.cancel()

    async def _read(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                if msg.type == aiohttp.WSMsgType.ERROR:
                    raise SonioxError(f"WebSocket error: {ws.exception()}")
                continue
            data = json.loads(msg.data)
            if data.get("error_code") is not None:
                raise SonioxError(_describe_error(data))
            for token in data.get("tokens", []):
                if token.get("is_final"):
                    self._final_text.append(token.get("text", ""))
            if data.get("finished"):
                return
        # Socket closed without a "finished" message.
        if not self._final_text:
            _LOGGER.debug("Soniox closed the stream without a finished message")


def _language_hints(language: Optional[str], extra: List[str]) -> List[str]:
    hints: List[str] = []
    for code in ([language] if language else []) + list(extra):
        code = code.split("-")[0].split("_")[0].lower().strip()
        if code and code not in hints:
            hints.append(code)
    return hints


def _join_tokens(texts: List[str]) -> str:
    words = [t for t in texts if not _CONTROL_TOKEN.match(t)]
    return re.sub(r"\s+", " ", "".join(words)).strip()


async def synthesize(
    http: aiohttp.ClientSession,
    settings: Settings,
    text: str,
    voice: str,
    language: str,
) -> AsyncIterator[bytes]:
    """Stream 16-bit mono PCM for text from the Soniox TTS REST API."""
    body = {
        "model": settings.tts_model,
        "language": language,
        "voice": voice,
        "audio_format": "pcm_s16le",
        "sample_rate": settings.tts_sample_rate,
        "text": text,
    }
    if settings.tts_speed != 1.0:
        body["speed"] = settings.tts_speed

    timeout = aiohttp.ClientTimeout(total=120, sock_connect=10, sock_read=20)
    try:
        async with http.post(
            settings.tts_url, json=body, headers=settings.auth_headers, timeout=timeout
        ) as resp:
            if resp.status != 200:
                detail = await resp.text()
                try:
                    detail = _describe_error(json.loads(detail))
                except ValueError:
                    detail = detail[:300]
                raise SonioxError(f"TTS request failed: HTTP {resp.status} {detail}")

            remainder = b""
            async for chunk in resp.content.iter_chunked(4096):
                data = remainder + chunk
                cut = len(data) - (len(data) % 2)  # keep whole 16-bit samples
                remainder = data[cut:]
                if cut:
                    yield data[:cut]
    except aiohttp.ClientError as err:
        raise SonioxError(f"TTS connection failed: {err}") from err
    except asyncio.TimeoutError as err:
        # aiohttp raises a plain TimeoutError (not a ClientError) when the
        # total timeout expires.
        raise SonioxError("TTS request timed out") from err


async def fetch_voices(http: aiohttp.ClientSession, settings: Settings) -> List[dict]:
    """Return [{id, description, gender}] for the configured TTS model."""
    url = f"{settings.api_url}/v1/tts-models"
    timeout = aiohttp.ClientTimeout(total=10)
    async with http.get(url, headers=settings.auth_headers, timeout=timeout) as resp:
        if resp.status != 200:
            raise SonioxError(f"Listing voices failed: HTTP {resp.status}")
        data = await resp.json()

    models = data.get("models", [])
    for model in models:
        if settings.tts_model in (model.get("id"), model.get("aliased_model_id")):
            return model.get("voices", [])
    # Model id not found (for example an alias): use the first model with voices.
    for model in models:
        if model.get("voices"):
            return model["voices"]
    return []
