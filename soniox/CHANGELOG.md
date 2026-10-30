# Changelog

## 0.1.3

Security hardening.

- Limits so one client cannot use up memory or the Soniox account: 60 seconds
  of audio per speech-to-text request, 4 simultaneous speech-to-text sessions
  (extra ones get a "busy" error), 4 simultaneous text-to-speech requests and
  8000 characters per spoken message. Audio is no longer kept in memory after
  Soniox has closed the stream. A session that never ends is closed.
- Connections to Soniox must be encrypted; `http://` and `ws://` are accepted
  only for localhost.
- The compose file publishes the port on 127.0.0.1 by default (`BIND_ADDRESS`
  changes it). The standalone Docker image runs as a non-root user.
- CI uses read-only permissions and also builds the standalone image.

## 0.1.2

- The app does not start when the API key is empty; it logs an error and stops.
- If the bridge is not listening within 10 seconds, the app stops and the
  container exits, so Home Assistant shows it as failed.
- The voice list request times out after 5 seconds (was 10), so startup stays
  inside the 10-second limit. The built-in voice list is used if it times out.

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
