import importlib.util
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "factory-ui" / "app.py"
SPEC = importlib.util.spec_from_file_location("factory_app", APP_PATH)
factory_app = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(factory_app)


class AnalysisBundleTests(unittest.TestCase):
    def test_model_switch_invalidates_analysis_cache(self):
        profile = {"generated_at": "2026-10-15T00:00:00Z"}
        with patch.dict("os.environ", {"LMSTUDIO_MODEL": "model-a"}):
            first = factory_app.analysis_bundle_cache_key(profile, "same request", "local")
        with patch.dict("os.environ", {"LMSTUDIO_MODEL": "model-b"}):
            second = factory_app.analysis_bundle_cache_key(profile, "same request", "local")
        self.assertNotEqual(first, second)

    def test_requirement_template_uses_only_safe_profile_fields(self):
        profile = {
            "fields": [
                {"name": "Email", "role": "category", "distinct": 12},
                {"name": "Department", "role": "category", "distinct": 4},
                {"name": "FiscalYear", "role": "date", "distinct": 3},
                {"name": "Cost", "role": "measure", "distinct": 8},
            ]
        }
        instruction = factory_app.dashboard_requirement_template(profile, {"audience": "management", "language": "th"})

        self.assertIn("Cost", instruction)
        self.assertIn("Department", instruction)
        self.assertIn("FiscalYear", instruction)
        self.assertNotIn("ตาม Email", instruction)

    def test_analysis_bundle_is_ai_generated_and_cached(self):
        calls = []

        def generate_json(system_prompt, user_prompt, schema):
            calls.append((system_prompt, user_prompt, schema))
            return {
                "semantic": {
                    "dataset_summary": "Student summary",
                    "warnings": [],
                    "field_interpretations": [{
                        "field": "สถานะ",
                        "semantic_type": "category",
                        "unit": "",
                        "aggregation_guidance": "group_only",
                        "business_role": "student status",
                        "confidence": 0.9,
                        "limitations": "Metadata-only interpretation.",
                    }],
                },
                "normalization": {"mappings": [], "warnings": []},
                "calculations": {"requests": [{"name": "Records", "metric": "record_count", "aggregation": "count", "dimension": None, "filters": []}]},
            }

        fake_ai_client = types.ModuleType("ai_client")
        fake_ai_client.generate_json = generate_json
        fake_ai_client.provider_name = lambda: "local"
        profile = {
            "generated_at": "2026-10-01T00:00:00Z",
            "fields": [{"name": "สถานะ", "role": "category", "distinct": 2, "missing": 0}],
        }
        records = [{"สถานะ": "กำลังศึกษา"}, {"สถานะ": "สำเร็จการศึกษา"}]
        original_project_dir = factory_app.project_dir
        original_ai_client = sys.modules.get("ai_client")
        with tempfile.TemporaryDirectory() as temporary_directory:
            factory_app.project_dir = lambda _: Path(temporary_directory)
            sys.modules["ai_client"] = fake_ai_client
            try:
                first = factory_app.get_ai_analysis_bundle("test", profile, records, "สร้าง dashboard")
                second = factory_app.get_ai_analysis_bundle("test", profile, records, "สร้าง dashboard")
            finally:
                factory_app.project_dir = original_project_dir
                if original_ai_client is None:
                    del sys.modules["ai_client"]
                else:
                    sys.modules["ai_client"] = original_ai_client

        self.assertEqual(len(calls), 1)
        self.assertEqual(first, second)
        self.assertEqual(first[0]["generated_by"], "local-ai")
        self.assertEqual(first[2][0]["metric"], "record_count")


if __name__ == "__main__":
    unittest.main()
