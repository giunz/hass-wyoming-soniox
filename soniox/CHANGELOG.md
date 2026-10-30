# Changelog

## 0.1.1

- Markdown in replies (from AI conversation agents) is no longer read aloud:
  `**bold**`, headings, list markers, links and backticks are removed before
  speaking.
- A TTS request that hits the overall timeout now reports a proper error to
  Home Assistant instead of dropping the connection.
- The STT WebSocket connection failure path also catches timeouts.
- Fallback voice list updated to the 12 voices in the Soniox docs.
- Added `scripts/live_check.py` to test against the real Soniox API, and a
  GitHub Actions workflow (tests, app linter, test builds for amd64/aarch64).

## 0.1.0

- First version: Soniox real-time speech-to-text and text-to-speech over the
  Wyoming protocol, with EU/US/JP regions, English/Greek language hints and
  sentence-by-sentence streaming of spoken responses.
