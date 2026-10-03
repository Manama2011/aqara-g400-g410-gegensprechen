#!/usr/bin/env python3
"""Sprechbruecke go2rtc -> Aqara G410 (Lautsprecher der Klingel). 02.10.2026

go2rtc startet dieses Skript als zweite Quelle des Streams klingel_udp
(exec:...#backchannel=1), sobald ein Client Mikrofon-Ton schickt, und schreibt
den Ton als G.711 A-law / 8 kHz auf stdin. Das Skript wandelt ihn per ffmpeg in
AAC-LC ADTS / 16 kHz und schickt ihn ueber den Sprachkanal der Klingel:
  Steuerung TCP 54324: FE EF | Typ(1) | Laenge(2) | Nutzlast | CRC-16(2)
                       Typ 0 = Start, 1 = Stopp, 2 = Quittung, 3 = Lebenszeichen (alle 5 s)
  Sprache   UDP 54323: RTP (PT 97), Nutzlast = ein ADTS-Frame (1024 Samples)
Protokoll nach github.com/absent42/aqara-doorbell (MIT), hier ohne Integration und
ohne eigene RTSP-Sitzung: der Sprachkanal ist vom Videostream unabhaengig.

Die Sprachsitzung wird erst beim ersten Ton geoeffnet und nach 10 s ohne Ton
wieder geschlossen. Protokoll: /config/logs/klingel_sprechen.log

Aufruf: klingel_sprechen.py <IP der Klingel> [Lautstaerke-Faktor, Standard 4.0]
"""
import os
import random
import select
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

if len(sys.argv) < 2:
    sys.exit("Aufruf: klingel_sprechen.py <IP der Klingel> [Lautstaerke-Faktor]")
IP = sys.argv[1]
# Standard 4.0 (+12 dB) - an der G410 war 1.0 deutlich zu leise. Anderer Wert: 2. Argument in go2rtc.yaml.
GAIN = sys.argv[2] if len(sys.argv) > 2 else "4.0"
LOG = os.environ.get("KLINGEL_LOG", "/config/logs/klingel_sprechen.log")
CTRL_PORT, AUDIO_PORT = 54324, 54323
T_START, T_STOP, T_ACK, T_BEAT = 0, 1, 2, 3
IDLE_S = 10


def _alaw_abs(a):
    a ^= 0x55
    t = (a & 0x0F) << 4
    seg = (a & 0x70) >> 4
    t = t + 8 if seg == 0 else (t + 0x108) << (seg - 1)
    return t


# 03.10.2026: Eingangspegel je Sitzung ins Protokoll (kommt vom Mikrofon wirklich Ton oder nur Stille?)
ALAW_ABS = [_alaw_abs(i) for i in range(256)]


def log(msg):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 200_000:
            os.replace(LOG, LOG + ".1")
        with open(LOG, "a") as f:
            f.write("%s [%d] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid(), msg))
    except OSError:
        pass


def crc16(data):
    c = 0xFFFF
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0x8408 if c & 1 else c >> 1
    return (~c) & 0xFFFF


def packet(typ, value):
    body = struct.pack(">BHQ", typ, 8, value)
    return b"\xFE\xEF" + body + struct.pack(">H", crc16(body))


def is_ack(data):
    return len(data) >= 8 and data[:2] == b"\xFE\xEF" and data[2] == T_ACK and data[5] == 0


class Session:
    """Eine Sprachsitzung: TCP-Steuerkanal mit Lebenszeichen + UDP fuer den Ton."""

    def __init__(self):
        self.ts = int(time.time() * 1000)
        self.ssrc = random.randint(1, 0x7FFFFFFF)
        self.seq = 0
        self.tcp = None
        self.udp = None
        self.lock = threading.Lock()
        self.stop = threading.Event()

    def open(self):
        self.tcp = socket.create_connection((IP, CTRL_PORT), timeout=3)
        self.tcp.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.tcp.sendall(packet(T_START, self.ts))
        if not is_ack(self.tcp.recv(1024)):
            raise OSError("Klingel lehnt die Sprachsitzung ab")
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        threading.Thread(target=self._beat, daemon=True).start()

    def _beat(self):
        fehler = 0
        while not self.stop.wait(5):
            try:
                with self.lock:
                    self.tcp.sendall(packet(T_BEAT, self.ts))
                    ok = is_ack(self.tcp.recv(1024))
                fehler = 0 if ok else fehler + 1
            except OSError:
                fehler += 1
            if fehler > 3:
                log("Lebenszeichen 4x ohne Quittung")
                return

    def send(self, frame):
        hdr = struct.pack(">BBHII", 0x80, 97, self.seq & 0xFFFF, (self.seq * 1024) & 0xFFFFFFFF, self.ssrc)
        self.seq += 1
        try:
            self.udp.sendto(hdr + frame, (IP, AUDIO_PORT))
        except OSError:
            pass

    def close(self):
        self.stop.set()
        try:
            with self.lock:
                self.tcp.sendall(packet(T_STOP, self.ts))
        except OSError:
            pass
        for s in (self.tcp, self.udp):
            try:
                s.close()
            except (OSError, AttributeError):
                pass


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-fflags", "nobuffer", "-flags", "low_delay",
           "-probesize", "32", "-analyzeduration", "0", "-f", "alaw", "-ar", "8000", "-ac", "1", "-i", "pipe:0"]
    if GAIN != "1.0":
        cmd += ["-af", "volume=" + GAIN]
    cmd += ["-c:a", "aac", "-profile:a", "aac_low", "-b:a", "32k", "-ar", "16000", "-ac", "1",
            "-flush_packets", "1", "-f", "adts", "pipe:1"]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    state = {"sess": None, "frames": 0, "bytes": 0, "peak": 0, "sum": 0, "n": 0}

    def pegel():
        n = state["n"] or 1
        txt = "Eingangspegel Spitze %d %%, Mittel %.1f %% (%d Bytes)" % (
            state["peak"] * 100 // 32256, state["sum"] * 100.0 / n / 32256, state["n"])
        state["peak"] = state["sum"] = state["n"] = 0
        return txt

    def pump():
        buf = bytearray()
        while True:
            chunk = ff.stdout.read(4096)
            if not chunk:
                return
            buf += chunk
            while len(buf) >= 7:
                if buf[0] != 0xFF or (buf[1] & 0xF0) != 0xF0:
                    del buf[0]
                    continue
                n = ((buf[3] & 0x03) << 11) | (buf[4] << 3) | (buf[5] >> 5)
                if n < 7:
                    del buf[0]
                    continue
                if len(buf) < n:
                    break
                s = state["sess"]
                if s:
                    s.send(bytes(buf[:n]))
                    state["frames"] += 1
                    if state["frames"] in (1, 50):
                        log("Frame %d an die Klingel gesendet" % state["frames"])
                del buf[:n]

    threading.Thread(target=pump, daemon=True).start()
    log("gestartet (Klingel %s, Lautstaerke %s)" % (IP, GAIN))
    try:
        while True:
            ready = select.select([0], [], [], IDLE_S)[0]
            if not ready:
                if state["sess"]:
                    state["sess"].close()
                    state["sess"] = None
                    log("10 s kein Ton -> Sprachsitzung geschlossen (%d Frames); %s" % (state["frames"], pegel()))
                continue
            data = os.read(0, 2048)
            if not data:
                break
            if state["sess"] is None:
                s = Session()
                s.open()
                state["sess"] = s
                log("Sprachsitzung offen")
            state["bytes"] += len(data)
            werte = [ALAW_ABS[b] for b in data]
            state["peak"] = max(state["peak"], max(werte))
            state["sum"] += sum(werte)
            state["n"] += len(werte)
            ff.stdin.write(data)
    except (OSError, SystemExit) as err:
        log("Ende: %s" % (err if str(err) else type(err).__name__))
    finally:
        try:
            ff.stdin.close()
        except OSError:
            pass
        try:
            ff.wait(timeout=2)
        except subprocess.TimeoutExpired:
            ff.kill()
        time.sleep(0.2)
        if state["sess"]:
            state["sess"].close()
        log("beendet: %d Bytes Ton empfangen, %d Frames gesendet; %s" % (state["bytes"], state["frames"], pegel()))


if __name__ == "__main__":
    main()
