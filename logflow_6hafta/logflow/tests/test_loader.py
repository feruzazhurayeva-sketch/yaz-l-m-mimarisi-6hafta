import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from interfaces import ConfigurationError
from loader import PipelineLoader
from pipeline import Pipeline


class TestPipelineLoader(unittest.TestCase):

    def setUp(self):
        # Geçerli bir temel yapılandırma sözlüğü
        self.valid_config = {
            "pipeline": {
                "name": "test-pipeline",
                "source": {
                    "type": "file",
                    "params": {"path": "data/access-small.log"}
                },
                "stages": [
                    {"type": "parse", "params": {"format": "clf"}},
                    {"type": "filter", "params": {"field": "status", "op": ">=", "value": 400}},
                    {"type": "project", "params": {"fields": ["client_ip", "status"]}}
                ],
                "sink": {
                    "type": "console",
                    "params": {}
                }
            }
        }

    def test_valid_configuration(self):
        """1. Geçerli bir yapılandırma başarıyla Pipeline nesnesi üretmelidir."""
        pipeline = PipelineLoader.load_from_dict(self.valid_config)
        self.assertIsInstance(pipeline, Pipeline)
        self.assertEqual(len(pipeline.stages), 3)

    def test_unknown_stage_type(self):
        """2. Bilinmeyen bir aşama türü ConfigurationError fırlatmalıdır."""
        cfg = dict(self.valid_config)
        cfg["pipeline"] = dict(self.valid_config["pipeline"])
        cfg["pipeline"]["stages"] = [
            {"type": "non_existent_stage", "params": {}}
        ]

        with self.assertRaises(ConfigurationError) as ctx:
            PipelineLoader.load_from_dict(cfg)
        self.assertIn("Bilinmeyen aşama türü", str(ctx.exception))

    def test_missing_required_parameter(self):
        """3. Zorunlu bir parametrenin eksik olması ConfigurationError fırlatmalıdır."""
        cfg = dict(self.valid_config)
        cfg["pipeline"] = dict(self.valid_config["pipeline"])
        # 'op' parametresi eksik filtre aşaması
        cfg["pipeline"]["stages"] = [
            {"type": "filter", "params": {"field": "status", "value": 400}}
        ]

        with self.assertRaises(ConfigurationError) as ctx:
            PipelineLoader.load_from_dict(cfg)
        self.assertIn("zorunlu 'op' parametresi eksik", str(ctx.exception))

    def test_invalid_parameter_type(self):
        """4. Yanlış türde parametre girilmesi ConfigurationError fırlatmalıdır."""
        cfg = dict(self.valid_config)
        cfg["pipeline"] = dict(self.valid_config["pipeline"])
        # 'fields' bir liste olmalıyken integer verilmiş
        cfg["pipeline"]["stages"] = [
            {"type": "project", "params": {"fields": 12345}}
        ]

        with self.assertRaises(ConfigurationError) as ctx:
            PipelineLoader.load_from_dict(cfg)
        self.assertIn("liste olmalıdır", str(ctx.exception))

    def test_empty_pipeline(self):
        """5. Hiç aşama içermeyen boş bir işlem hattı ConfigurationError fırlatmalıdır."""
        cfg = dict(self.valid_config)
        cfg["pipeline"] = dict(self.valid_config["pipeline"])
        cfg["pipeline"]["stages"] = []

        with self.assertRaises(ConfigurationError) as ctx:
            PipelineLoader.load_from_dict(cfg)
        self.assertIn("en az bir aşama (stage) içermelidir", str(ctx.exception))

    def _with(self, **kw):
        cfg = dict(self.valid_config)
        cfg["pipeline"] = dict(self.valid_config["pipeline"], **kw)
        return cfg

    def test_on_error_policy_is_loaded_per_stage(self):
        """6. Aşama başına on_error politikası yapılandırmadan okunur."""
        cfg = self._with(
            stages=[
                {"type": "parse", "on_error": "DEAD_LETTER", "params": {}},
                {"type": "filter", "on_error": "RETRY(3)", "params": {"field": "status", "op": ">=", "value": 400}},
                {"type": "project", "params": {"fields": ["status"]}},
            ],
            dead_letter={"type": "dead_letter_file", "params": {"path": "out/x.jsonl"}},
        )
        p = PipelineLoader.load_from_dict(cfg)
        self.assertEqual([str(x) for x in p.policies], ["DEAD_LETTER", "RETRY(3)", "FAIL_FAST"])
        self.assertIsNotNone(p.dead_letter)

    def test_invalid_policy_name(self):
        """7. Geçersiz politika adı ConfigurationError fırlatmalıdır."""
        cfg = self._with(stages=[{"type": "parse", "on_error": "IGNORE", "params": {}}])
        with self.assertRaises(ConfigurationError) as ctx:
            PipelineLoader.load_from_dict(cfg)
        self.assertIn("Geçersiz hata politikası", str(ctx.exception))

    def test_dead_letter_policy_requires_dead_letter_target(self):
        """8. DEAD_LETTER kullanan aşama varken dead_letter hedefi yoksa fail-fast (hiç satır işlenmeden)."""
        cfg = self._with(stages=[{"type": "parse", "on_error": "DEAD_LETTER", "params": {}}])
        with self.assertRaises(ConfigurationError) as ctx:
            PipelineLoader.load_from_dict(cfg)
        self.assertIn("dead_letter", str(ctx.exception))

    def test_validate_stage_from_config_and_bad_rule(self):
        """9. 'validate' aşaması kayıtlıdır; hatalı kural ConfigurationError verir."""
        ok = self._with(stages=[{"type": "validate", "params": {"ip_format": True, "ranges": {"bytes": {"min": 0}}}}])
        self.assertEqual(len(PipelineLoader.load_from_dict(ok).stages), 1)
        bad = self._with(stages=[{"type": "validate", "params": {"ranges": {"bytes": {"minimum": 0}}}}])
        with self.assertRaises(ConfigurationError):
            PipelineLoader.load_from_dict(bad)

    def test_shipped_configs_load(self):
        """10. Teslim edilen tüm YAML dosyaları yüklenebilir."""
        import glob
        files = glob.glob("configs/*.yaml")
        self.assertGreaterEqual(len(files), 4)
        for f in files:
            PipelineLoader.load_from_file(f)


if __name__ == '__main__':
    unittest.main()