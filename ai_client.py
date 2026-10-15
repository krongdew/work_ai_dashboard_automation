from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from output_language import LANGUAGE_INSTRUCTION, unsupported_text_paths

ROOT = Path(__file__).resolve().parent
LOCAL_AI = ROOT / "local-ai"
load_dotenv(ROOT / ".env")

if str(LOCAL_AI) not in sys.path:
    sys.path.insert(0, str(LOCAL_AI))


def provider_name() -> str:
    from lan_service import CURRENT_STORE
    if CURRENT_STORE.get() is not None:
        return "worker"
    provider = os.getenv("AI_PROVIDER", "groq").strip().lower()
    if provider not in {"groq", "local"}:
        raise ValueError("AI_PROVIDER must be 'groq' or 'local'.")
    return provider


def generate_json(system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
    if provider_name() == "worker":
        from lan_service import remote_generate
        generate = remote_generate
    elif provider_name() == "local":
        from lmstudio_client import generate_json as local_generate_json
        generate = local_generate_json
    else:
        from cloud_ai_client import generate_json as groq_generate_json
        generate = groq_generate_json

    prompt = f"{system_prompt}\n\n{LANGUAGE_INSTRUCTION}"
    request = user_prompt
    for attempt in range(3):
        result = generate(prompt, request, schema)
        issues = unsupported_text_paths(result)
        if not issues:
            return result
        request = (
            f"{user_prompt}\n\nLANGUAGE VALIDATION FAILED at: {', '.join(issues[:12])}. "
            "Return a complete JSON response with those display values in Thai or English. "
            "Preserve exact field references, formulas, enum values and source/category values."
        )
    raise ValueError("AI returned display text outside Thai/English after three attempts. Please try again.")
