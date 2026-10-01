from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
LOCAL_AI = ROOT / "local-ai"
load_dotenv(ROOT / ".env")

if str(LOCAL_AI) not in sys.path:
    sys.path.insert(0, str(LOCAL_AI))


def provider_name() -> str:
    provider = os.getenv("AI_PROVIDER", "groq").strip().lower()
    if provider not in {"groq", "local"}:
        raise ValueError("AI_PROVIDER must be 'groq' or 'local'.")
    return provider


def generate_json(system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
    if provider_name() == "local":
        from lmstudio_client import generate_json as local_generate_json

        return local_generate_json(system_prompt, user_prompt, schema)

    from cloud_ai_client import generate_json as groq_generate_json

    return groq_generate_json(system_prompt, user_prompt, schema)