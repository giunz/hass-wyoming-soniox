"""Constants: regional endpoints, languages, defaults."""

from dataclasses import dataclass, field
from typing import List, Optional

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

    @property
    def auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}
