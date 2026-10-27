import sys
import os
import unittest
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from interfaces import Emitter
from record import LogRecord
from filters import PredicateFilterStage, ProjectionStage
from stages import FileSink


class CollectingEmitter(Emitter[any]):
    """Birim testleri için disk bağımsız çıktı toplayıcı test dublörü."""
    def __init__(self):
        self.records = []

    def emit(self, item: any) -> None:
        self.records.append(item)


class TestNewStages(unittest.TestCase):

    def setUp(self):
        self.sample_record = LogRecord(
            timestamp=datetime(2026, 9, 29, 10, 0, 1),
            client_ip="192.168.1.50",
            method="GET",
            path="/api/users",
            status=404,
            bytes=120,
            user_agent="TestAgent",
            raw="raw log line"
        )

    def test_predicate_filter_matching(self):
        """Koşulu sağlayan kayıt iletilmeli."""
        stage = PredicateFilterStage(lambda r: r.status >= 400)
        emitter = CollectingEmitter()

        stage.process(self.sample_record, emitter)

        self.assertEqual(len(emitter.records), 1)
        self.assertEqual(emitter.records[0].status, 404)

    def test_predicate_filter_non_matching(self):
        """Koşulu sağlamayan kayıt elenmeli (emit edilmemeli)."""
        stage = PredicateFilterStage(lambda r: r.status == 200)
        emitter = CollectingEmitter()

        stage.process(self.sample_record, emitter)

        self.assertEqual(len(emitter.records), 0)

    def test_projection_stage(self):
        """Yalnızca belirtilen alanlar sözlük olarak indirgenmeli."""
        stage = ProjectionStage(["timestamp", "client_ip", "status"])
        emitter = CollectingEmitter()

        stage.process(self.sample_record, emitter)

        self.assertEqual(len(emitter.records), 1)
        projected = emitter.records[0]
        self.assertIn("timestamp", projected)
        self.assertIn("client_ip", projected)
        self.assertIn("status", projected)
        self.assertNotIn("path", projected)
        self.assertNotIn("user_agent", projected)
        self.assertEqual(projected["client_ip"], "192.168.1.50")

    def test_file_sink_lifecycle_and_write(self):
        """FileSink open, write ve close yaşam döngüsünü doğru uygulamalı."""
        with tempfile.NamedTemporaryFile(delete=False, mode="w+", encoding="utf-8") as temp_file:
            temp_path = temp_file.name

        try:
            sink = FileSink(temp_path)
            sink.open()
            sink.consume("Satir 1")
            sink.consume("Satir 2")
            sink.close()

            with open(temp_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines()]

            self.assertEqual(lines, ["Satir 1", "Satir 2"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == '__main__':
    unittest.main()