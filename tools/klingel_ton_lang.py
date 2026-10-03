#!/usr/bin/env python3
"""Hoertest ueber den kompletten Weg: go2rtc -> Sprechbruecke -> Klingel.

Erzeugt einen 4 s langen, lauten 1000-Hz-Ton und laesst go2rtc ihn in den Rueckkanal des Streams
spielen (API ?dst=<stream>). Muss dort laufen, wo go2rtc die Datei lesen kann (bei Home Assistant:
im Core-Container, z. B. ueber einen shell_command).

Aufruf: klingel_ton_lang.py [Streamname, Standard klingel_udp] [go2rtc-API, Standard http://127.0.0.1:1984]
"""
import math, struct, sys, urllib.parse, urllib.request, wave

STREAM = sys.argv[1] if len(sys.argv) > 1 else "klingel_udp"
API = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:1984"
TON = "/tmp/klingel_testton_lang.wav"
sr = 8000
with wave.open(TON, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(sr)
    s = [0] * (sr // 2) + [int(32767 * 0.8 * math.sin(2 * math.pi * 1000 * i / sr)) for i in range(sr * 4)] + [0] * (sr // 2)
    w.writeframes(struct.pack("<%dh" % len(s), *s))
src = "ffmpeg:%s#audio=pcma#input=file" % TON
url = "%s/api/streams?dst=%s&src=%s" % (API, urllib.parse.quote(STREAM), urllib.parse.quote(src, safe=""))
with urllib.request.urlopen(urllib.request.Request(url, method="POST"), timeout=15) as r:
    print(r.status, r.read().decode()[:200])
