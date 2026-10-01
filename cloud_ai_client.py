from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from groq import Groq

load_dotenv(Path(__file__).resolve().with_name(".env"))

MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "llama-3.3-70b-versatile")


def generate_json(system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is not configured. Add it to your environment or .env file; never put it in source code.")
    client = Groq(api_key=api_key)
    schema_instruction = json.dumps(schema, ensure_ascii=False)
    messages = [
        {
            "role": "system",
            "content": (
                f"{system_prompt}\n\nReturn exactly one JSON object, with no markdown or commentary. "
                "Its structure must conform to this JSON Schema. Field values are validated locally, so use only values supplied in the user request.\n"
                f"JSON SCHEMA:\n{schema_instruction}"
            ),
        },
        {"role": "user", "content": user_prompt},
    ]
    models = [MODEL] + ([FALLBACK_MODEL] if FALLBACK_MODEL != MODEL else [])
    last_error: Exception | None = None
    for model in models:
        for delay in (0, 1, 3):
            if delay:
                time.sleep(delay)
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.1,
                )
                return json.loads(response.choices[0].message.content or "{}")
            except Exception as exc:
                last_error = exc
                message = str(exc)
                if "400" in message or "404" in message or "429" in message or "503" in message:
                    break
                if "500" not in message:
                    raise
    raise RuntimeError(f"Groq models unavailable after retry: {last_error}") from last_error
