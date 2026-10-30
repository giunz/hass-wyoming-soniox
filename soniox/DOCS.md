# Soniox Speech

Uses [Soniox](https://soniox.com) for Assist's speech-to-text (what you say)
and text-to-speech (what Assist says back). The processing runs in Soniox's
cloud, so this app works on a Raspberry Pi or Home Assistant Green.

## Before you start

1. Create an account at [console.soniox.com](https://console.soniox.com) and
   create an API key.
2. **For the EU region** (recommended for GDPR): EU processing is enabled on
   request. Email `sales@soniox.com`, then create a new project with the EU
   region selected and use an API key from that project. A key from a normal
   (US) project is rejected by the EU servers.
   If you want to try things first, set **Region** to `us` with a normal key.

## Setup

1. Install this app, open **Configuration**, paste your API key, save, and
   start the app.
2. Home Assistant should show a new **Wyoming Protocol** device under
   **Settings > Devices & services** (discovered). Select **Configure**.
   If it does not appear, add the *Wyoming Protocol* integration by hand with
   the host shown in this app's log and port `10500`.
3. Go to **Settings > Voice assistants**, open your assistant and set:
   - **Speech-to-text**: Soniox, language English or Greek
   - **Text-to-speech**: Soniox, then pick a voice

## Languages

- **Speech-to-text**: the assistant's language is tried first, then the
  **Language hints** (default `en,el`). Soniox can follow you if you switch
  between English and Greek mid-sentence.
- **Text-to-speech**: Home Assistant only tells this app the voice, not the
  language, so the app looks at the text. Greek letters are spoken as Greek,
  anything else in **Language for non-Greek text** (default English).

## Privacy

According to Soniox's documentation, real-time audio and transcripts are not
stored and are never used for training; logs contain only metadata. With the
EU region, audio and text stay in the EU. This app does not store anything.
**Debug logging** writes your words to the app log, so leave it off normally.

## Cost

Soniox lists speech-to-text at about $0.12 per hour of audio and
text-to-speech at about $0.70 per hour of generated speech. Voice commands are
a few seconds each. Check [soniox.com/pricing](https://soniox.com/pricing).

## Troubleshooting

- `Incorrect API key provided` with region `eu`: the key is not from an EU
  project (see above).
- `Organization balance exhausted`: add credit in the Soniox Console.
- Assist says it did not understand: turn on **Debug logging** and look at
  the `Transcript:` lines in the log.
