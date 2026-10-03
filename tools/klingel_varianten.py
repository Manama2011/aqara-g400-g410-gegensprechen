#!/usr/bin/env python3
"""Format-Probe: Welche Tonformate spielt die Klingel ueber den LAN-Sprachkanal ab?

Sendet nacheinander denselben 3-s-Ton (1000 Hz) in sieben Varianten, je mit eigener Sprachsitzung und
3 s Pause dazwischen. Jemand muss an der Klingel zuhoeren und mitzaehlen: Das Mikrofon der G410 ist
stumm, solange ihr Lautsprecher spielt - automatisch per Aufnahme laesst sich der Ton nicht nachweisen.

Braucht ffmpeg im PATH (im Home-Assistant-Core-Container vorhanden).
Aufruf: klingel_varianten.py <IP der Klingel>
"""
import random, socket, struct, subprocess, sys, time

if len(sys.argv) < 2:
    sys.exit(__doc__)
IP = sys.argv[1]


def crc16(d):
    c = 0xFFFF
    for b in d:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0x8408 if c & 1 else c >> 1
    return (~c) & 0xFFFF


def pkt(t, v):
    body = struct.pack(">BHQ", t, 8, v)
    return b"\xFE\xEF" + body + struct.pack(">H", crc16(body))


def ff(args):
    return subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                           "sine=frequency=1000:duration=3", "-af", "volume=6dB"] + args + ["pipe:1"],
                          capture_output=True).stdout


def adts(data):
    fr, o = [], 0
    while o < len(data) - 7:
        if data[o] != 0xFF or (data[o + 1] & 0xF0) != 0xF0:
            o += 1
            continue
        n = ((data[o + 3] & 3) << 11) | (data[o + 4] << 3) | (data[o + 5] >> 5)
        if n < 7 or o + n > len(data):
            break
        fr.append(data[o:o + n])
        o += n
    return fr


def variante(name, frames, pt, ts_step, dauer_ms):
    ts_ms = int(time.time() * 1000)
    tcp = socket.create_connection((IP, 54324), timeout=3)
    tcp.sendall(pkt(0, ts_ms))
    ack = tcp.recv(1024)
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ssrc = random.randint(1, 0x7FFFFFFF)
    start = time.time()
    print("%s  Ton %-34s %3d Pakete, Quittung %s" % (time.strftime("%H:%M:%S"), name, len(frames), ack.hex()), flush=True)
    for i, f in enumerate(frames):
        udp.sendto(struct.pack(">BBHII", 0x80, pt, i & 0xFFFF, (i * ts_step) & 0xFFFFFFFF, ssrc) + f, (IP, 54323))
        soll = start + (i + 1) * dauer_ms / 1000.0
        if soll > time.time():
            time.sleep(soll - time.time())
    time.sleep(0.4)
    try:
        tcp.sendall(pkt(1, ts_ms))
    except OSError:
        pass
    tcp.close()
    udp.close()


def main():
    chunk = lambda d, n: [d[i:i + n] for i in range(0, len(d) - n + 1, n)]
    a16 = adts(ff(["-c:a", "aac", "-profile:a", "aac_low", "-b:a", "32k", "-ar", "16000", "-ac", "1", "-f", "adts"]))
    a8 = adts(ff(["-c:a", "aac", "-profile:a", "aac_low", "-b:a", "24k", "-ar", "8000", "-ac", "1", "-f", "adts"]))
    a48 = adts(ff(["-c:a", "aac", "-profile:a", "aac_low", "-b:a", "64k", "-ar", "48000", "-ac", "1", "-f", "adts"]))
    al = ff(["-ar", "8000", "-ac", "1", "-f", "alaw"])
    mu = ff(["-ar", "8000", "-ac", "1", "-f", "mulaw"])
    s16 = ff(["-ar", "16000", "-ac", "1", "-f", "s16be"])
    tests = [
        ("1 AAC-ADTS 16k PT97 (wie Bruecke)", a16, 97, 1024, 64),
        ("2 AAC roh ohne ADTS 16k PT97", [f[7:] for f in a16], 97, 1024, 64),
        ("3 G.711 A-law 8k PT8", chunk(al, 160), 8, 160, 20),
        ("4 G.711 u-law 8k PT0", chunk(mu, 160), 0, 160, 20),
        ("5 AAC-ADTS 8k PT97", a8, 97, 1024, 128),
        ("6 AAC-ADTS 48k PT97", a48, 97, 1024, 21.333),
        ("7 PCM L16 16k PT97", chunk(s16, 640), 97, 320, 20),
    ]
    for t in tests:
        try:
            variante(*t)
        except OSError as e:
            print("FEHLER", t[0], repr(e))
        time.sleep(3)


if __name__ == "__main__":
    main()
