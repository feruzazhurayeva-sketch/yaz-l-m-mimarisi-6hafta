"""
Kaos testi girdisi üretici:  python tools/make_dirty_log.py
Üretir: data/access-dirty.log (bilerek bozuk) ve data/empty.log (boş dosya).
Çıktı belirlidir (sabit tohum); her çalıştırmada aynı dosya oluşur.
"""
import os
import random

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

def line(ip="10.0.0.5", ts="29/Sep/2026:10:00:01 +0300", req="GET /index.html HTTP/1.1",
         status="200", size="4324", ua='"Mozilla/5.0"'):
    return f'{ip} - - [{ts}] "{req}" {status} {size} {ua}'.encode()

# --- 40 geçerli satır (access-small.log'dan) ---
with open(os.path.join(ROOT, "data", "access-small.log"), "rb") as f:
    valid = [l.rstrip(b"\r\n") for l in f if l.strip()][:40]

bad = []
# 1) Kesilmiş satırlar (5)                                -> ParserStage
bad += [
    b"192.168.1.10 - - [29/Sep/2026:10:00:01 +0",
    b'192.168.1.11 - - [29/Sep/2026:10:00:02 +0300] "POST /api/log',
    b'192.168.1.12 - - [29/Sep/2026:10:00:03 +0300] "GET /dashboard HTTP/1.1"',
    b'192.168.1.13 - - [29/Sep/2026:10:00:04 +0300] "GET /a HTTP/1.1" 20',
    b"192.168.1.14",
]
# 2) UTF-8 olmayan baytlar (3)                            -> ParserStage
bad += [
    b'192.168.1.20 - - [29/Sep/2026:10:01:01 +0300] "GET /caf\xff\xfe.html HTTP/1.1" 200 512 "Agent"',
    b'192.168.1.21 - - [29/Sep/2026:10:01:02 +0300] "GET /x HTTP/1.1" 200 512 "Ag\x80\x81ent"',
    b'192.168.1.22 - - [29/Sep/2026:10:01:03 +0300] "GET /y HTTP/1.1" 200 512 "Truncated multibyte \xc3"',
]
# 3) Boş / yalnızca boşluk satırları (2)                  -> ParserStage
bad += [b"", b"     "]
# 4) 100 KB'lık tek satır (geçerli bir başlangıçla)       -> ParserStage
bad += [line(ip="192.168.1.30", req="GET /" + "A" * (100 * 1024) + " HTTP/1.1")]
# 5) Negatif bayt sayıları (3)                            -> ValidationStage
bad += [line(ip="192.168.1.40", size="-4324"), line(ip="192.168.1.41", size="-1"),
        line(ip="192.168.1.42", size="-999999")]
# 6) 1970 (2) ve 2099 (2) zaman damgaları                 -> ValidationStage
bad += [line(ip="192.168.1.50", ts="01/Jan/1970:00:00:00 +0000"),
        line(ip="192.168.1.51", ts="31/Dec/1969:23:59:59 +0000"),
        line(ip="192.168.1.52", ts="01/Jan/2099:12:00:00 +0000"),
        line(ip="192.168.1.53", ts="31/Dec/2099:23:59:59 +0300")]
# 7) Geçersiz IP (3) ve durum kodu aralığı (2)            -> ValidationStage
bad += [line(ip="999.1.1.1"), line(ip="300.300.300.300"), line(ip="not-an-ip"),
        line(ip="192.168.1.60", status="999"), line(ip="192.168.1.61", status="042")]

lines = valid + bad
random.Random(5).shuffle(lines)

os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
with open(os.path.join(ROOT, "data", "access-dirty.log"), "wb") as f:
    f.write(b"\n".join(lines) + b"\n")
open(os.path.join(ROOT, "data", "empty.log"), "wb").close()
print(f"access-dirty.log: toplam {len(lines)} satır ({len(valid)} geçerli, {len(bad)} bozuk)")
