import sys
import os
import unittest
from datetime import datetime

# src klasöründeki modülleri import edebilmek için yolu ekliyoruz
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from interfaces import Emitter, StageException
from record import LogRecord
from parser import ParserStage


class CollectingEmitter(Emitter[LogRecord]):
    """
    Test Dublörü (Test Double / Spy):
    Aşamanın emit ettiği kayıtları bir listede toplayarak
    dosya sistemine dokunmadan test yapmayı sağlar.
    """
    def __init__(self):
        self.records = []

    def emit(self, item: LogRecord) -> None:
        self.records.append(item)


class TestParserStage(unittest.TestCase):

    def setUp(self):
        self.stage = ParserStage()
        self.emitter = CollectingEmitter()

    def test_01_valid_line(self):
        """1. Geçerli satır testi"""
        line = '192.168.1.1 - - [29/Sep/2026:10:00:01 +0300] "GET /index.html HTTP/1.1" 200 4324 "Mozilla/5.0"'
        self.stage.process(line, self.emitter)

        self.assertEqual(len(self.emitter.records), 1)
        rec = self.emitter.records[0]
        self.assertEqual(rec.client_ip, "192.168.1.1")
        self.assertEqual(rec.method, "GET")
        self.assertEqual(rec.path, "/index.html")
        self.assertEqual(rec.status, 200)
        self.assertEqual(rec.bytes, 4324)
        self.assertEqual(rec.user_agent, "Mozilla/5.0")

    def test_02_missing_field(self):
        """2. Eksik alan içeren satır (durum kodu ve byte eksik)"""
        line = '192.168.1.1 - - [29/Sep/2026:10:00:01 +0300] "GET /index.html HTTP/1.1"'
        with self.assertRaises(StageException):
            self.stage.process(line, self.emitter)

        self.assertEqual(len(self.emitter.records), 0)

    def test_03_invalid_timestamp(self):
        """3. Hatalı zaman damgası (geçersiz ay adı)"""
        line = '192.168.1.1 - - [29/BilinmeyenAy/2026:10:00:01 +0300] "GET /index.html HTTP/1.1" 200 4324 "Mozilla/5.0"'
        with self.assertRaises(StageException):
            self.stage.process(line, self.emitter)

        self.assertEqual(len(self.emitter.records), 0)

    def test_04_invalid_status_code(self):
        """4. Hatalı durum kodu (sayı yerine metin)"""
        line = '192.168.1.1 - - [29/Sep/2026:10:00:01 +0300] "GET /index.html HTTP/1.1" ABC 4324 "Mozilla/5.0"'
        with self.assertRaises(StageException):
            self.stage.process(line, self.emitter)

        self.assertEqual(len(self.emitter.records), 0)

    def test_05_empty_line(self):
        """5. Boş satır testi"""
        line = '    \n'
        with self.assertRaises(StageException):
            self.stage.process(line, self.emitter)

        self.assertEqual(len(self.emitter.records), 0)

    def test_06_extra_spaces(self):
        """6. Alanlar arasında fazladan boşluklar olan geçerli format"""
        line = '192.168.1.1   -   -   [29/Sep/2026:10:00:01 +0300]   "GET /home HTTP/1.1"   200   512   "Agent"'
        self.stage.process(line, self.emitter)

        self.assertEqual(len(self.emitter.records), 1)
        self.assertEqual(self.emitter.records[0].path, "/home")

    def test_07_user_agent_with_spaces(self):
        """7. Boşluk içeren tırnaklı karmaşık user-agent"""
        line = '10.0.0.1 - - [29/Sep/2026:10:00:01 +0300] "GET /api HTTP/1.1" 200 120 "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"'
        self.stage.process(line, self.emitter)

        self.assertEqual(len(self.emitter.records), 1)
        self.assertEqual(
            self.emitter.records[0].user_agent,
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

    def test_08_query_string_in_path(self):
        """8. Sorgu dizesi (query string) içeren satır"""
        line = '192.168.1.1 - - [29/Sep/2026:10:00:01 +0300] "GET /search?q=laptop&sort=asc HTTP/1.1" 200 8900 "-"'
        self.stage.process(line, self.emitter)

        self.assertEqual(len(self.emitter.records), 1)
        self.assertEqual(self.emitter.records[0].path, "/search?q=laptop&sort=asc")

    def test_09_negative_bytes_reaches_validation(self):
        """9. Negatif bayt sayısı ayrıştırılır (reddi ValidationStage'in işidir)."""
        line = '192.168.1.1 - - [29/Sep/2026:10:00:01 +0300] "GET /a HTTP/1.1" 200 -50 "UA"'
        self.stage.process(line, self.emitter)
        self.assertEqual(self.emitter.records[0].bytes, -50)

    def test_10_non_utf8_raises(self):
        """10. UTF-8 olmayan bayt (surrogateescape ile taşınır) StageException olmalı."""
        line = '192.168.1.1 - - [29/Sep/2026:10:00:01 +0300] "GET /a\udcff HTTP/1.1" 200 5 "UA"'
        with self.assertRaises(StageException) as ctx:
            self.stage.process(line, self.emitter)
        self.assertIn("UTF-8", str(ctx.exception))

    def test_11_overlong_line_raises(self):
        """11. Sınırı aşan satır StageException olmalı (geçerli başlangıç olsa bile)."""
        line = '192.168.1.1 - - [29/Sep/2026:10:00:01 +0300] "GET /' + "A" * 100_000 + ' HTTP/1.1" 200 5 "UA"'
        with self.assertRaises(StageException) as ctx:
            self.stage.process(line, self.emitter)
        self.assertIn("çok uzun", str(ctx.exception))
        self.assertEqual(len(self.emitter.records), 0)


if __name__ == '__main__':
    unittest.main()