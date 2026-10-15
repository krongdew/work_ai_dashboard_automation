import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai_client
from output_language import require_supported_text, unsupported_text_paths


class OutputLanguageTests(unittest.TestCase):
    def test_allows_thai_english_and_preserves_source_references(self):
        require_supported_text({
            "dashboard_title": "สรุป Cost ปี 2569",
            "charts": [{"title": "Cost by department", "dimension": "部门", "formula": "SUM(金额)"}],
            "mappings": [{"field": "部门", "source": "研究", "target": "研究"}],
        })

    def test_detects_nested_display_text_and_other_scripts(self):
        self.assertEqual(unsupported_text_paths({
            "kpis": [{"name": "总 Cost"}], "display_labels": {"Cost": "成本"},
            "warnings": ["данные"], "insight_questions": ["ข้อมูลครบหรือไม่"],
        }), ["$.kpis[0].name", "$.display_labels.Cost", "$.warnings[0]"])

    def test_retries_language_failure_without_changing_original_request(self):
        with patch.object(ai_client, "provider_name", return_value="local"), patch(
            "lmstudio_client.generate_json", side_effect=[{"dashboard_title": "总览"}, {"dashboard_title": "ภาพรวม"}]
        ) as generate:
            self.assertEqual(ai_client.generate_json("system", "original request", {}), {"dashboard_title": "ภาพรวม"})
            self.assertIn("Thai or English ONLY", generate.call_args_list[0].args[0])
            self.assertIn("original request", generate.call_args_list[1].args[1])
            self.assertIn("$.dashboard_title", generate.call_args_list[1].args[1])

    def test_repeated_language_failure_is_rejected(self):
        with patch.object(ai_client, "provider_name", return_value="local"), patch(
            "lmstudio_client.generate_json", return_value={"dashboard_title": "总览"}
        ) as generate:
            with self.assertRaisesRegex(ValueError, "after three attempts"):
                ai_client.generate_json("system", "user", {})
            self.assertEqual(generate.call_count, 3)

    def test_cloud_provider_uses_the_same_language_policy(self):
        with patch.object(ai_client, "provider_name", return_value="groq"), patch(
            "cloud_ai_client.generate_json", return_value={"dashboard_title": "Overview"}
        ) as generate:
            self.assertEqual(ai_client.generate_json("system", "user", {}), {"dashboard_title": "Overview"})
            self.assertIn("Thai or English ONLY", generate.call_args.args[0])

    def test_saved_chinese_spec_is_rejected_before_build(self):
        with self.assertRaisesRegex(ValueError, "Regenerate or translate"):
            require_supported_text({"charts": [{"title": "总览"}]})


if __name__ == "__main__":
    unittest.main()
