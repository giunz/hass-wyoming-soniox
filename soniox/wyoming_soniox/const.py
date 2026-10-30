"""Constants: regional endpoints, languages, defaults."""

import asyncio
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlsplit

# Regional API domains, from https://soniox.com/docs/data-residency
REGION_DOMAINS = {
    "us": "soniox.com",
    "eu": "eu.soniox.com",
    "jp": "jp.soniox.com",
}

# Languages listed in the Soniox docs for both speech-to-text and
# text-to-speech (same 60 codes on both pages, checked 2026-10-29).
LANGUAGES: List[str] = [
    "af", "sq", "ar", "az", "eu", "be", "bn", "bs", "bg", "ca", "zh", "hr",
    "cs", "da", "nl", "en", "et", "fi", "fr", "gl", "de", "el", "gu", "he",
    "hi", "hu", "id", "it", "ja", "kn", "kk", "ko", "lv", "lt", "mk", "ms",
    "ml", "mr", "no", "fa", "pl", "pt", "pa", "ro", "ru", "sr", "sk", "sl",
    "es", "sw", "sv", "tl", "ta", "te", "th", "tr", "uk", "ur", "vi", "cy",
]

# Used only if the voice list cannot be fetched from the API at startup.
# From https://soniox.com/docs/tts/concepts/voices (checked 2026-10-30).
FALLBACK_VOICES = [
    "Adrian", "Claire", "Daniel", "Emma", "Grace", "Jack",
    "Kenji", "Maya", "Mina", "Nina", "Noah", "Owen",
]

# Soniox TTS accepts these output sample rates.
TTS_SAMPLE_RATES = [8000, 16000, 24000, 44100, 48000]

# Audio sent to Soniox speech-to-text (Home Assistant already sends this).
STT_RATE = 16000
STT_WIDTH = 2
STT_CHANNELS = 1


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _require_tls(name: str, url: str, secure: str, insecure: str) -> None:
    """Allow only encrypted URLs; the unencrypted scheme only for this machine."""
    parts = urlsplit(url)
    if parts.scheme == secure:
        return
    if parts.scheme == insecure and parts.hostname in _LOOPBACK_HOSTS:
        return
    raise ValueError(
        f"The {name} URL must start with {secure}:// "
        f"({insecure}:// is only allowed for localhost): {url}"
    )


@dataclass
class Settings:
    """Runtime settings for the bridge."""

    api_key: str
    region: str = "eu"
    stt_model: str = "stt-rt-v5"
    tts_model: str = "tts-rt-v2"
    voice: str = "Adrian"
    language_hints: List[str] = field(default_factory=lambda: ["en", "el"])
    tts_default_language: str = "en"
    tts_sample_rate: int = 24000
    tts_speed: float = 1.0
    stt_enabled: bool = True
    tts_enabled: bool = True
    stt_finish_timeout: float = 10.0
    # Limits. The bridge has no login (the Wyoming protocol has none), so these
    # keep one misbehaving client from using up memory or the Soniox account.
    stt_max_seconds: float = 60.0  # audio accepted per utterance
    max_stt_sessions: int = 4  # simultaneous speech-to-text sessions
    max_tts_requests: int = 4  # simultaneous requests to Soniox TTS
    tts_max_chars: int = 8000  # text spoken per message; the rest is dropped
    stt_idle_slack: float = 10.0  # extra seconds before an unfinished session is closed
    # Endpoint overrides (normally derived from region; used for tests).
    stt_url: Optional[str] = None
    tts_url: Optional[str] = None
    api_url: Optional[str] = None

    def __post_init__(self) -> None:
        domain = REGION_DOMAINS[self.region]
        if self.stt_url is None:
            self.stt_url = f"wss://stt-rt.{domain}/transcribe-websocket"
        if self.tts_url is None:
            self.tts_url = f"https://tts-rt.{domain}/tts"
        if self.api_url is None:
            self.api_url = f"https://api.{domain}"
        # The API key is sent to these URLs, so they must be encrypted.
        _require_tls("STT", self.stt_url, "wss", "ws")
        _require_tls("TTS", self.tts_url, "https", "http")
        _require_tls("API", self.api_url, "https", "http")

    @property
    def auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}


class Limits:
    """Counters shared by all connections (one instance per server)."""

    def __init__(self, settings: Settings) -> None:
        self._max_stt = settings.max_stt_sessions
        self._stt_active = 0
        self.tts = asyncio.Semaphore(settings.max_tts_requests)

    def acquire_stt(self) -> bool:
        """Take a speech-to-text slot; False if all slots are in use."""
        if self._stt_active >= self._max_stt:
            return False
        self._stt_active += 1
        return True

    def release_stt(self) -> None:
        self._stt_active = max(0, self._stt_active - 1)
