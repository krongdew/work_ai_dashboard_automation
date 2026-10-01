import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-ai"))

import lmstudio_client


class Qwen3JsonGenerationTests(unittest.TestCase):
    def test_qwen3_disables_thinking_and_returns_json(self):
        captured = {}

        class FakeMessage:
            content = '{"status":"ok"}'

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return FakeResponse()

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            chat = FakeChat()

        original_client = lmstudio_client.client
        lmstudio_client.client = FakeClient()
        try:
            result = lmstudio_client.generate_json(
                "system",
                "user",
                {"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]},
            )
        finally:
            lmstudio_client.client = original_client

        self.assertEqual(result, {"status": "ok"})
        self.assertIn("extra_body", captured)
        extra_body = captured["extra_body"]
        self.assertIn("chat_template_kwargs", extra_body)
        self.assertFalse(extra_body["chat_template_kwargs"].get("enable_thinking"))


if __name__ == "__main__":
    unittest.main()
