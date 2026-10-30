# Wyoming Soniox

A [Wyoming protocol](https://www.home-assistant.io/integrations/wyoming/)
server that lets Home Assistant's Assist use
[Soniox](https://soniox.com) for speech-to-text and text-to-speech. Built for
low-power hardware (Raspberry Pi, Home Assistant Green) where local Whisper is
too slow, and for English and Greek.

- Speech-to-text: Soniox real-time WebSocket API (`stt-rt-v5`)
- Text-to-speech: Soniox REST API (`tts-rt-v2`), streamed sentence by sentence
- Regions: EU (default), US, JP

## Install as a Home Assistant app (add-on)

1. In Home Assistant: **Settings > Apps > App store > ⋮ > Repositories**,
   add `https://github.com/giunz/hass-wyoming-soniox`.
2. Install **Soniox Speech**, set the API key, start it. Details are in
   [soniox/DOCS.md](soniox/DOCS.md).

The app builds on your device the first time (a few minutes on a Pi).

## Run with Docker instead

```sh
export SONIOX_API_KEY=...
docker compose up -d
```

Then add the *Wyoming Protocol* integration in Home Assistant with the host's
IP and port `10500`.

## Run directly

```sh
pip install -r soniox/requirements.txt
cd soniox
SONIOX_API_KEY=... python -m wyoming_soniox --uri tcp://0.0.0.0:10500 --region eu
```

`python -m wyoming_soniox --help` lists all options.

## How it works

| Home Assistant sends | The bridge does |
|---|---|
| `transcribe`, then audio | Opens a Soniox WebSocket at once and streams the audio (converted to 16 kHz mono) |
| `audio-stop` | Ends the Soniox stream, joins the final tokens, returns `transcript` |
| `synthesize` | One Soniox TTS request per ~1000 characters, streams PCM back |
| `synthesize-start/chunk/stop` | Speaks each finished sentence as soon as it arrives |

Home Assistant's TTS client sends a voice name but no language, so the bridge
picks Greek for text in Greek letters and the configured default otherwise.

## Tests

```sh
pip install -r soniox/requirements.txt pytest pytest-asyncio
python -m pytest
```

The tests run the real bridge against a fake Soniox server that follows the
documented protocol. They do not contact Soniox.

## Check against the real Soniox API

```sh
SONIOX_API_KEY=... python scripts/live_check.py --region us   # or eu / jp
```

It starts the bridge, speaks an English and a Greek sentence (saved as
`live_en.wav` / `live_el.wav`), sends that audio back through speech-to-text
and prints the transcripts and timings. Use the region your API key's
project belongs to.

## Status

The test suite passes against the fake server, and the request formats were
checked against the Soniox docs (October 2026). The bridge has not yet run
against the live Soniox service or inside a real Home Assistant install, so
the first real run may need small fixes. Check the app log.
