import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from interfaces import Emitter, StageException, ConfigurationError
from record import LogRecord
from validation import ValidationStage


class Collect(Emitter):
    def __init__(self):
        self.records = []

    def emit(self, item):
        self.records.append(item)


def rec(**kw):
    base = dict(timestamp=datetime(2026, 9, 29, 10, 0, 1, tzinfo=timezone(timedelta(hours=3))),
                client_ip="192.168.1.1", method="GET", path="/a", status=200, bytes=10,
                user_agent="UA", raw="raw")
    base.update(kw)
    return LogRecord(**base)


CFG = {
    "required_fields": ["client_ip", "method", "path"],
    "ranges": {"status": {"min": 100, "max": 599}, "bytes": {"min": 0}},
    "timestamp": {"min": "2000-01-01", "max": "now"},
    "ip_format": True,
}


class TestValidationStage(unittest.TestCase):
    def setUp(self):
        self.stage = ValidationStage.from_config(CFG)
        self.out = Collect()

    def reject(self, r, fragment):
        with self.assertRaises(StageException) as ctx:
            self.stage.process(r, self.out)
        self.assertIn(fragment, str(ctx.exception))
        self.assertEqual(self.out.records, [])

    def test_valid_passes(self):
        r = rec()
        self.stage.process(r, self.out)
        self.assertEqual(self.out.records, [r])

    def test_negative_bytes(self):
        self.reject(rec(bytes=-1), "bytes=-1")

    def test_status_range(self):
        self.reject(rec(status=999), "status=999")
        self.reject(rec(status=42), "status=42")

    def test_timestamp_1970_and_2099(self):
        self.reject(rec(timestamp=datetime(1970, 1, 1, tzinfo=timezone.utc)), "çok eski")
        self.reject(rec(timestamp=datetime(2099, 1, 1, tzinfo=timezone.utc)), "gelecekte")

    def test_ip_format(self):
        self.reject(rec(client_ip="999.1.1.1"), "geçersiz IP")
        self.reject(rec(client_ip="not-an-ip"), "geçersiz IP")
        self.stage.process(rec(client_ip="2001:db8::1"), self.out)  # IPv6 geçerli
        self.assertEqual(len(self.out.records), 1)

    def test_required_field(self):
        self.reject(rec(path=""), "zorunlu alan eksik: path")

    def test_all_violations_are_reported_together(self):
        with self.assertRaises(StageException) as ctx:
            self.stage.process(rec(bytes=-5, client_ip="x"), self.out)
        self.assertIn("bytes=-5", str(ctx.exception))
        self.assertIn("geçersiz IP", str(ctx.exception))

    def test_config_errors(self):
        for bad in [{"nope": 1}, {"ranges": []}, {"ranges": {"status": {"mn": 1}}},
                    {"ranges": {"status": {"min": "a"}}}, {"ip_format": "yes"},
                    {"timestamp": {"min": "tarih-degil"}}, {"required_fields": "path"}]:
            with self.assertRaises(ConfigurationError, msg=str(bad)):
                ValidationStage.from_config(bad)


if __name__ == '__main__':
    unittest.main()
