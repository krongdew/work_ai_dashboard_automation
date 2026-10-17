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


def resolve_provider(light: bool) -> str:
    """Pick the provider for this task. A LAN worker store always wins. Otherwise
    split by task weight when configured:
      LIGHT_PROVIDER  — semantic/normalization/enrich (small, frequent)
      HEAVY_PROVIDER  — dashboard planning/repair (big, must be fast)
    Both default to AI_PROVIDER, so a single-provider setup keeps working."""
    from lan_service import CURRENT_STORE
    if CURRENT_STORE.get() is not None:
        return "worker"
    base = os.getenv("AI_PROVIDER", "groq").strip().lower()
    key = "LIGHT_PROVIDER" if light else "HEAVY_PROVIDER"
    chosen = (os.getenv(key, "") or base).strip().lower()
    if chosen not in {"groq", "local"}:
        chosen = base
    return chosen


def generate_json(system_prompt: str, user_prompt: str, schema: dict[str, Any], light: bool = False) -> dict[str, Any]:
    provider = resolve_provider(light)
    if provider == "worker":
        from lan_service import remote_generate
        generate = remote_generate
        light_supported = False
    elif provider == "local":
        from lmstudio_client import generate_json as local_generate_json
        generate = local_generate_json
        light_supported = False
    else:
        from cloud_ai_client import generate_json as groq_generate_json
        generate = groq_generate_json
        light_supported = True

    prompt = f"{system_prompt}\n\n{LANGUAGE_INSTRUCTION}"
    request = user_prompt

    def call(req):
        # Only the Groq backend supports model-tiering; others ignore the flag.
        return generate(prompt, req, schema, light=light) if light_supported else generate(prompt, req, schema)

    for attempt in range(3):
        result = call(request)
        issues = unsupported_text_paths(result)
        if not issues:
            return result
        request = (
            f"{user_prompt}\n\nLANGUAGE VALIDATION FAILED at: {', '.join(issues[:12])}. "
            "Return a complete JSON response with those display values in Thai or English. "
            "Preserve exact field references, formulas, enum values and source/category values."
        )
    raise ValueError("AI returned display text outside Thai/English after three attempts. Please try again.")
