import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
CLIENT_PATH = ROOT / "local-ai" / "lmstudio_client.py"


class LocalAiClientConfigTests(unittest.TestCase):
    def test_default_timeout_allows_a_slow_structured_completion(self):
        original_timeout = os.environ.pop("LMSTUDIO_TIMEOUT", None)
        try:
            spec = importlib.util.spec_from_file_location("test_lmstudio_client", CLIENT_PATH)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            sys.modules[spec.name] = module
            with patch("dotenv.load_dotenv"):
                spec.loader.exec_module(module)
        finally:
            sys.modules.pop("test_lmstudio_client", None)
            if original_timeout is not None:
                os.environ["LMSTUDIO_TIMEOUT"] = original_timeout

        self.assertEqual(module.TIMEOUT, 420.0)

    def test_incomplete_json_reports_configuration_guidance(self):
        spec = importlib.util.spec_from_file_location("test_lmstudio_client", CLIENT_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        try:
            with patch("dotenv.load_dotenv"):
                spec.loader.exec_module(module)
            module.client = SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(
                        create=lambda **_: SimpleNamespace(
                            choices=[SimpleNamespace(message=SimpleNamespace(content='{"field":"unfinished', reasoning_content=None))]
                        )
                    )
                )
            )
            with self.assertRaisesRegex(RuntimeError, "Increase LMSTUDIO_MAX_TOKENS"):
                module.generate_json("system", "user", {"type": "object"})
        finally:
            sys.modules.pop("test_lmstudio_client", None)


if __name__ == "__main__":
    unittest.main()