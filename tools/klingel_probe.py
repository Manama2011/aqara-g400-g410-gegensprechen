#!/usr/bin/env python3
"""Misst die Zeit bis zum ersten dekodierten Bild der Klingel je ffmpeg-Eingangsvariante (3 Runden).
Braucht ffmpeg (bei Home Assistant im Core-Container). Dabei darf nichts anderes die RTSP-Sitzung halten.
Aufruf: klingel_probe.py rtsp://USER:PASS@IP:8554/ch1"""
import subprocess, time, sys
if len(sys.argv) < 2:
    sys.exit("usage: klingel_probe.py rtsp://USER:PASS@IP:8554/ch1")
URL = sys.argv[1]
REST = "-flags low_delay -use_wallclock_as_timestamps 1 -timeout 5000000 -user_agent go2rtc/ffmpeg -rtsp_transport udp"
VARIANTEN = {
    "A aktuell (nobuffer)": "-fflags nobuffer+genpts+discardcorrupt",
    "E ohne nobuffer": "-fflags genpts+discardcorrupt",
    "F ohne nobuffer + fps0": "-fpsprobesize 0 -fflags genpts+discardcorrupt",
    "G nobuffer, Analyse ~0": "-analyzeduration 0 -probesize 32 -fflags nobuffer+genpts+discardcorrupt",
}
RUNDEN = 3
erg = {k: [] for k in VARIANTEN}
for r in range(RUNDEN):
    for name, extra in VARIANTEN.items():
        cmd = ["ffmpeg", "-hide_banner", "-v", "warning", "-allowed_media_types", "video+audio"] + (extra + " " + REST).split() + \
              ["-i", URL, "-map", "0:v:0", "-frames:v", "1", "-vf", "scale=960:720", "-f", "null", "-"]
        t = time.monotonic()
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=25)
            d = time.monotonic() - t
            err = [l.strip() for l in p.stderr.strip().split("\n") if l and "no frame" not in l and "repeated" not in l][-2:]
            erg[name].append(d if p.returncode == 0 else None)
            print("%-26s Runde %d: %5.2f s rc=%d %s" % (name, r + 1, d, p.returncode, " | ".join(err)[:220]), flush=True)
        except subprocess.TimeoutExpired:
            erg[name].append(None); print("%-26s Runde %d: TIMEOUT" % (name, r + 1), flush=True)
        time.sleep(2)
print("---")
for k, v in erg.items():
    ok = [x for x in v if x is not None]
    print("%-26s Mittel %s  (min %s, max %s, Fehler %d)" % (k, "%.2f" % (sum(ok) / len(ok)) if ok else "-", "%.2f" % min(ok) if ok else "-", "%.2f" % max(ok) if ok else "-", len(v) - len(ok)))
print("FERTIG")
