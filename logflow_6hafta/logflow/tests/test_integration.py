import sys
import os
import unittest
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from stages import FileLineSource, FileSink
from parser import ParserStage
from filters import PredicateFilterStage, ProjectionStage
from pipeline import PipelineBuilder


class TestPipelineIntegration(unittest.TestCase):

    def test_full_pipeline_run(self):
        """
        FileLineSource -> ParserStage -> PredicateFilterStage -> ProjectionStage -> FileSink
        uçtan uca çalıştırılıp çıktı dosyasının doğrulanması testi.
        """
        # 1. Test Girdisi (Fixture) oluştur
        sample_logs = (
            '192.168.1.1 - - [29/Sep/2026:10:00:01 +0300] "GET /api/data HTTP/1.1" 200 100 "Agent"\n'
            '192.168.1.2 - - [29/Sep/2026:10:00:02 +0300] "POST /api/login HTTP/1.1" 500 200 "Agent"\n'
            '192.168.1.3 - - [29/Sep/2026:10:00:03 +0300] "GET /index.html HTTP/1.1" 404 150 "Agent"\n'
        )

        with tempfile.NamedTemporaryFile(delete=False, mode="w+", encoding="utf-8") as in_file:
            in_file.write(sample_logs)
            in_path = in_file.name

        with tempfile.NamedTemporaryFile(delete=False, mode="w+", encoding="utf-8") as out_file:
            out_path = out_file.name

        try:
            # 2. PipelineBuilder ile akıcı kurulum
            pipeline = (
                PipelineBuilder.from_source(FileLineSource(in_path))
                .via(ParserStage())
                .via(PredicateFilterStage(lambda r: r.status >= 400 and r.path.startswith("/api")))
                .via(ProjectionStage(["client_ip", "status", "path"]))
                .to(FileSink(out_path))
            )

            # 3. Çalıştır
            pipeline.run()

            # 4. Çıktıyı Doğrula
            with open(out_path, "r", encoding="utf-8") as f:
                output_lines = [line.strip() for line in f.readlines() if line.strip()]

            # Sadece 2. kayıt eşleşmeli: status 500 ve path /api/login
            self.assertEqual(len(output_lines), 1)
            self.assertIn("192.168.1.2", output_lines[0])
            self.assertIn("500", output_lines[0])
            self.assertIn("/api/login", output_lines[0])

        finally:
            if os.path.exists(in_path):
                os.remove(in_path)
            if os.path.exists(out_path):
                os.remove(out_path)


if __name__ == '__main__':
    unittest.main()