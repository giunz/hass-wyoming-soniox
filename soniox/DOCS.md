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
Log level **debug** writes your words to the app log, so leave it on
**normal** except while troubleshooting.

## Security

The Wyoming protocol has no login, so anyone who can connect to port 10500
can use your Soniox account. The app does not publish that port outside Home
Assistant, which is the safe default: leave the port field empty in the app's
network settings unless you need it, and never expose it to the internet.

**Allowed client addresses** limits who may connect. Left empty, the app
accepts home and local networks only (`192.168.x.x`, `10.x.x.x`,
`172.16-31.x.x`, which includes Home Assistant itself) and refuses public
internet addresses. To restrict it further, list the addresses or networks
that may connect, separated by commas, for example
`192.168.1.20, 192.168.1.0/24`. When the list is filled in, only those are
allowed (plus the machine the app runs on), so also include Home Assistant,
usually `172.30.32.0/23`.

To find out which addresses your devices use, look in the log: each client
address is logged once, the first time it connects (`New client address:
192.168.1.20`), and refused ones are logged as warnings. Set **Log level** to
`connections` to log every connection with its address.

To protect memory and your account from a client that misbehaves, the app
accepts at most 60 seconds of audio per request, 4 simultaneous
speech-to-text requests, 4 simultaneous text-to-speech requests, and 8000
characters of text per spoken message. Extra requests get a "busy" error.

## Cost

Soniox lists speech-to-text at about $0.12 per hour of audio and
text-to-speech at about $0.70 per hour of generated speech. Voice commands are
a few seconds each. Check [soniox.com/pricing](https://soniox.com/pricing).

## Troubleshooting

- `Incorrect API key provided` with region `eu`: the key is not from an EU
  project (see above).
- `Organization balance exhausted`: add credit in the Soniox Console.
- Assist says it did not understand: set **Log level** to `debug` and look at
  the `Transcript:` lines in the log.
