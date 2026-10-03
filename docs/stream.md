# G410 video stream in go2rtc – what made it stable and fast

Notes from getting the RTSP stream of an Aqara G410 to start quickly and run without
freezes in Home Assistant dashboards (go2rtc 1.9.9, WebRTC and MSE). The complete
example is in [`examples/go2rtc.yaml`](../examples/go2rtc.yaml).

*Deutsch:* Erfahrungen und Einstellungen, mit denen der Videostream der G410 in
go2rtc schnell startet und nicht einfriert.

## Findings

| Problem | Cause | Fix |
|---|---|---|
| WebRTC picture freezes after about a second, card restarts | the G410 occasionally sends RTSP timestamps that run backwards | own ffmpeg input template with `-use_wallclock_as_timestamps 1` |
| WebRTC does not start at all | the doorbell only sends AAC 16 kHz, which WebRTC cannot play | add an Opus track; keep AAC for MSE/MP4: `#audio=copy#audio=opus` |
| first picture only after 5–6 s | `-fflags nobuffer` threw away the keyframe read during probing, ffmpeg then waited for the next one (GOP of the doorbell 2–4 s) | no `nobuffer`, add `-fpsprobesize 0` → about 2 s here |
| every extra viewer waits for a keyframe | long GOP of the camera | transcode with one keyframe per second (`-g 15` at 15 fps) |
| second stream or second client breaks the first | the doorbell serves **one RTSP session** | one go2rtc stream holds the session; everything else (Home Assistant camera entity, dashboards) pulls from go2rtc |
| substreams (`ch2`, `ch3`) stall | unstable on the device side here | use `ch1` and scale down in go2rtc |

## One stream, both audio tracks

Do the Opus transcode in the same go2rtc source as the video, not in a second stream
that pulls from the first: every additional ffmpeg hop waits for a keyframe again and
adds seconds to the start.

```yaml
streams:
  klingel_udp:
    - ffmpeg:rtsp://RTSP_USER:RTSP_PASS@192.168.1.50:8554/ch1#input=rtsp_tcp_wallclock#video=klingel_h264#width=960#height=720#audio=copy#audio=opus
```

## TCP or UDP

- With a **good Wi-Fi link** use TCP (`rtsp_tcp_wallclock`). Over UDP the first
  keyframe of every cold start arrived only partly here (upper part of the picture,
  rest grey until the next keyframe).
- With a **bad link** (here once: -76 dBm, about 30–60 % retries) TCP collapses – the
  stream runs for half a minute and then stalls with gaps of several seconds
  (retransmission back-off). UDP kept flowing in that situation. The real fix was the
  radio link: closer access point, free channel.

Check the radio link before tuning software: signal, retry rate and channel
utilisation of the doorbell's access point.

## Home Assistant camera entity

Point the Generic Camera at go2rtc instead of the doorbell, so there is still only one
session to the device:

```
rtsp://127.0.0.1:8554/klingel_udp
```

## Measuring the start time

[`tools/klingel_probe.py`](../tools/klingel_probe.py) measures the time to the first
decoded picture for several ffmpeg input variants, three rounds each. Run it where
ffmpeg is available (Home Assistant: inside the Core container) while nothing else
holds the RTSP session.

All numbers are from one G410 and one network – treat them as a starting point.
