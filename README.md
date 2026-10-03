# Aqara G410 / G400 – Gegensprechen aus Home Assistant (local two-way talk)

Talk to the speaker of an **Aqara Doorbell Camera Hub G410** (and, untested by me, the
**G400**, which uses the same LAN talk protocol) from a Home Assistant
dashboard – locally, without cloud, without an extra integration and without a second
RTSP session to the doorbell.

*Deutsch:* Sprechen-Knopf im Dashboard → Mikrofon per WebRTC an go2rtc → kleines
Python-Skript → Lautsprecher der Klingel. Kommentare, Protokollzeilen und die Texte
der Karte sind deutsch.

> **Status:** works for me, tested on one G410 (October 2026) from an iPhone and
> from Safari on macOS. The **G400** is not tested by me – the protocol was originally
> proven on the G400 by absent42, so it should work the same way; reports welcome. No stable product, no support
> promise. Use at your own risk.

## How it works

```
Dashboard card (microphone, WebRTC send-only)
        │  /api/webrtc/ws  (signed path, HA proxy of the WebRTC integration)
        ▼
go2rtc stream "klingel_udp"
   source 1: rtsp://…/ch1                      video + audio FROM the doorbell
   source 2: exec:klingel_sprechen.py#backchannel=1
        │  G.711 A-law, 8 kHz on stdin
        ▼
klingel_sprechen.py ── ffmpeg ──► AAC-LC ADTS, 16 kHz, mono, 32 kbit/s
        │  TCP 54324  control: start / heartbeat / stop
        │  UDP 54323  RTP, payload type 97, one ADTS frame per packet
        ▼
Aqara G410 speaker
```

go2rtc starts the script only while a client actually sends microphone audio. The
voice session to the doorbell is opened with the first audio and closed after 10 s
of silence. Normal viewing does not start it, and the video stream is untouched.

## Requirements

- Aqara G410 (or G400) with RTSP enabled (user/password from the Aqara app), reachable on the LAN
- Home Assistant with go2rtc **1.9.9** (the built-in one is fine) and a custom
  `/config/go2rtc.yaml`
- [AlexxIT WebRTC Camera](https://github.com/AlexxIT/WebRTC) integration (tested with
  v3.6.1) – the card uses its `/api/webrtc/ws` proxy for signalling
- `ffmpeg` and `python3` where go2rtc runs (both exist in the HA Core container)
- HTTPS access to Home Assistant – browsers only allow the microphone on secure origins

## Installation

1. Copy `klingel_sprechen.py` to `/config/scripts/`.
2. Add the back channel as a **second source** to your doorbell stream in
   `/config/go2rtc.yaml` (see [`examples/go2rtc.yaml`](examples/go2rtc.yaml)):

   ```yaml
   streams:
     klingel_udp:
       - rtsp://RTSP_USER:RTSP_PASS@192.168.1.50:8554/ch1
       - exec:python3 /config/scripts/klingel_sprechen.py 192.168.1.50#backchannel=1
   ```

3. Restart go2rtc (or Home Assistant).
4. Copy `klingel-sprechen-card.js` to `/config/www/` and add it as a dashboard
   resource (`/local/klingel-sprechen-card.js`, JavaScript module).
5. Add the card (see [`examples/lovelace.yaml`](examples/lovelace.yaml)):

   ```yaml
   type: custom:klingel-sprechen-card
   stream: klingel_udp
   name: Sprechen
   ```

Tap the button to switch the microphone on, tap again to switch it off (it switches
off by itself after `max_sekunden`, default 60).

### Volume

The second argument of the script is a gain factor (ffmpeg `volume`), default `4.0`
(+12 dB – with `1.0` the G410 was far too quiet here):

```yaml
- exec:python3 /config/scripts/klingel_sprechen.py 192.168.1.50 2.5#backchannel=1
```

### Log

`/config/logs/klingel_sprechen.log` (override with the environment variable
`KLINGEL_LOG`). Per session it records the number of frames sent and the input level
(peak / mean in percent), so you can tell silence from real microphone audio.

## What I found out about the G410

- The LAN talk protocol published for the G400 by
  [absent42/aqara-doorbell](https://github.com/absent42/aqara-doorbell) works unchanged
  on the G410.
- The doorbell only plays **AAC-LC with ADTS header, 16 kHz, RTP payload type 97**.
  Raw AAC without ADTS, G.711 A-law/µ-law, AAC at 8 or 48 kHz and L16 PCM are
  acknowledged but stayed silent in my test (`tools/klingel_varianten.py`).
- **Half duplex:** the G410 mutes its own microphone while its speaker is playing. You
  cannot verify playback by recording the doorbell's microphone – someone has to listen.
- The voice channel is independent of the RTSP stream; it does not cost the single
  RTSP session the doorbell offers.
- One voice session at a time.

## Limitations

- go2rtc 1.9.9 delivers the back channel as G.711 A-law at 8 kHz – telephone quality.
- No echo cancellation beyond what the browser does; with the dashboard playing the
  doorbell's audio next to the microphone you may get feedback.
- The macOS Companion app does not expose `navigator.mediaDevices` in its web view –
  use Safari there.
- go2rtc ends the script with a kill, so no explicit STOP packet is sent then; closing
  the TCP connection has been enough for the doorbell so far.
- No doorbell-press detection here – this is talk only.

## Video stream

Settings and findings for a fast and stable G410 video stream in go2rtc (timestamps,
audio tracks, start time, TCP vs. UDP): [`docs/stream.md`](docs/stream.md).

## Tools

- `tools/klingel_varianten.py <ip>` – sends the same test tone in seven formats, one
  after the other, so you can check which ones your device plays.
- `tools/klingel_probe.py <rtsp-url>` – measures the time to the first picture for
  several ffmpeg input variants.
- `tools/klingel_ton_lang.py [stream] [go2rtc-api]` – plays a 4 s tone through the
  complete path (go2rtc → script → doorbell).

Both need `ffmpeg`, so on Home Assistant run them inside the Core container (for
example via a `shell_command`).

## Protocol (short)

Control channel, TCP 54324:
`FE EF | type (1) | payload length (2) | payload | CRC-16 (2)` – type 0 start,
1 stop, 2 ack, 3 heartbeat (every 5 s). Payload of start/stop/heartbeat is the session
timestamp in ms as uint64, payload of ack is one byte (0 = ok). CRC-16 with
polynomial 0x8408, init 0xFFFF, final XOR 0xFFFF over type..payload.

Audio channel, UDP 54323: plain RTP (version 2, payload type 97), timestamp advances
by 1024 per frame (16 kHz clock), payload = one complete ADTS frame.

## Credits and license

Protocol reverse-engineered and first published by **absent42**
([aqara-doorbell](https://github.com/absent42/aqara-doorbell), MIT, archived). This
project re-implements the talk part as a single go2rtc `exec` back channel plus a
dashboard card.

MIT License – see [LICENSE](LICENSE). Not affiliated with Aqara / Lumi.
