import pytest

from wyoming_soniox.const import REGION_DOMAINS, Limits, Settings


@pytest.mark.parametrize("region", sorted(REGION_DOMAINS))
def test_default_urls_are_encrypted(region):
    s = Settings(api_key="k", region=region)
    assert s.stt_url.startswith("wss://")
    assert s.tts_url.startswith("https://") and s.api_url.startswith("https://")


@pytest.mark.parametrize(
    "field,url",
    [
        ("stt_url", "ws://stt.example.com/transcribe-websocket"),
        ("tts_url", "http://tts.example.com/tts"),
        ("api_url", "http://api.example.com"),
        ("tts_url", "ftp://localhost/tts"),
    ],
)
def test_unencrypted_urls_to_other_hosts_are_refused(field, url):
    with pytest.raises(ValueError, match="must start with"):
        Settings(api_key="k", **{field: url})


def test_unencrypted_urls_to_this_machine_are_allowed():
    Settings(
        api_key="k",
        stt_url="ws://127.0.0.1:9/x",
        tts_url="http://localhost:9/tts",
        api_url="http://127.0.0.1:9",
    )


@pytest.mark.asyncio
async def test_stt_slots():
    limits = Limits(Settings(api_key="k", max_stt_sessions=2))
    assert limits.acquire_stt() and limits.acquire_stt()
    assert not limits.acquire_stt()
    limits.release_stt()
    assert limits.acquire_stt()
    limits.release_stt(); limits.release_stt(); limits.release_stt()  # never below zero
    assert limits.acquire_stt()
