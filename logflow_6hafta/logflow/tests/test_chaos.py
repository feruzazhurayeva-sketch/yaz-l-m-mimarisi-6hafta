"""Kaos testi: bilerek bozuk dosya -> çalıştırma tamamlanır, her kayıt hesaba katılır."""
import json
import os
import sys
import tempfile
import unittest
from collections import Counter

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from loader import PipelineLoader
from interfaces import PipelineException

# tools/make_dirty_log.py ile üretilen dosyanın bilinen bileşimi
TOTAL, VALID = 63, 40
PARSE_FAILS, VALIDATE_FAILS = 11, 12


def read_lines(path):
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


def load_with_outputs(cfg_path, tmp):
    p = PipelineLoader.load_from_file(os.path.join(ROOT, cfg_path))
    p.source.file_path = os.path.join(ROOT, p.source.file_path)
    p.sink.output_path = os.path.join(tmp, "clean.txt")
    if p.dead_letter is not None:
        p.dead_letter.sink.path = os.path.join(tmp, "dead.jsonl")
    return p


class TestChaos(unittest.TestCase):
    def test_dirty_file_completes_and_everything_is_accounted_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = load_with_outputs("configs/dirty-report.yaml", tmp)
            s = p.run()

            # tamamlandı, sayılar birbirini tutuyor
            self.assertEqual(s.status, "COMPLETED")
            self.assertEqual(s.records_in, TOTAL)
            self.assertEqual(s.records_out, VALID)
            self.assertEqual(s.dead_letter_count, PARSE_FAILS + VALIDATE_FAILS)
            self.assertEqual(s.records_in, s.records_out + s.dead_letter_count)
            self.assertTrue(s.is_balanced)
            by_stage = {st.name: st for st in s.stages}
            self.assertEqual(by_stage["parse"].dead_lettered, PARSE_FAILS)
            self.assertEqual(by_stage["validate"].dead_lettered, VALIDATE_FAILS)

            # geçerli kayıtlar ana hedefe ulaştı
            clean = read_lines(os.path.join(tmp, "clean.txt"))
            self.assertEqual(len(clean), VALID)

            # hatalı kayıtlar dead-letter hedefinde, bağlamıyla birlikte
            rows = [json.loads(l) for l in read_lines(os.path.join(tmp, "dead.jsonl"))]
            self.assertEqual(len(rows), PARSE_FAILS + VALIDATE_FAILS)
            kinds = Counter()
            for r in rows:
                m = r["message"]
                if r["stage"] == "parse":
                    key = ("utf8" if "UTF-8" in m else "uzun" if "çok uzun" in m
                           else "boş" if "Boş" in m else "kesik")
                else:
                    key = ("negatif-bayt" if "bytes=" in m else "1970" if "çok eski" in m
                           else "2099" if "gelecekte" in m else "ip" if "IP" in m else "durum-kodu")
                kinds[key] += 1
                self.assertIn("line_number", r)
            self.assertEqual(dict(kinds), {
                "kesik": 5, "utf8": 3, "boş": 2, "uzun": 1,
                "negatif-bayt": 3, "1970": 2, "2099": 2, "ip": 3, "durum-kodu": 2,
            })
            # 100 KB'lık satır kesilerek yazıldı, tam uzunluğu kayıtlı
            long_row = next(r for r in rows if "çok uzun" in r["message"])
            self.assertTrue(long_row["raw_truncated"])
            self.assertGreater(long_row["raw_length"], 100_000)
            self.assertLessEqual(len(long_row["raw"]), 200)

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = load_with_outputs("configs/dirty-report.yaml", tmp)
            p.source.file_path = os.path.join(ROOT, "data", "empty.log")
            s = p.run()
            self.assertEqual((s.status, s.records_in, s.records_out, s.dead_letter_count),
                             ("COMPLETED", 0, 0, 0))
            self.assertTrue(s.is_balanced)

    def test_same_dirty_file_with_fail_fast_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = load_with_outputs("configs/dirty-report.yaml", tmp)
            from policy import ErrorPolicy
            p.policies[0] = ErrorPolicy.fail_fast()
            with self.assertRaises(PipelineException):
                p.run()
            self.assertEqual(p.summary.status, "FAILED")
            self.assertLess(p.summary.records_in, TOTAL)

    def test_clean_file_unaffected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = load_with_outputs("configs/error-report.yaml", tmp)
            s = p.run()
            self.assertEqual(s.dead_letter_count, 0)
            self.assertTrue(s.is_balanced)


if __name__ == '__main__':
    unittest.main()
