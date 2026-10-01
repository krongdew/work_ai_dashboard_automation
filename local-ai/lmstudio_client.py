from __future__ import annotations
import os, json
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
MODEL = os.getenv("LMSTUDIO_MODEL", "openai/gpt-oss-20b")
API_KEY = os.getenv("LMSTUDIO_API_KEY", "lm-studio")
# Local models can take several minutes to complete a 1,024-token JSON response.
TIMEOUT = float(os.getenv("LMSTUDIO_TIMEOUT", "420"))
MAX_TOKENS = int(os.getenv("LMSTUDIO_MAX_TOKENS", "1024"))
client = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=TIMEOUT)


def qwen3_json_kwargs() -> dict[str, Any]:
    if "qwen3" not in MODEL.lower():
        return {}
    return {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}

def list_models() -> list[str]:
    return [m.id for m in client.models.list().data]

def chat(messages: list[dict[str, Any]], temperature: float = 0.2, max_tokens: int | None = None) -> str:
    kwargs: dict[str, Any] = {"model": MODEL, "messages": messages, "temperature": temperature}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    r = client.chat.completions.create(**kwargs)
    return r.choices[0].message.content or ""

def generate_json(system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
    no_think = "\n/no_think" if "qwen3" in MODEL.lower() else ""
    base_messages = [{"role": "system", "content": system_prompt + no_think}, {"role": "user", "content": user_prompt + no_think}]
    response_format = {"type": "json_schema", "json_schema": {"name": "dashboard_spec", "strict": True, "schema": schema}}
    last_json_error: json.JSONDecodeError | None = None
    for attempt in range(3):
        messages = base_messages if attempt == 0 else base_messages + [{
            "role": "user",
            "content": "Return a complete valid JSON object matching the schema. Do not include reasoning, markdown fences, or trailing text.",
        }]
        payload = {
            "model": MODEL,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": MAX_TOKENS,
            "response_format": response_format,
        }
        payload.update(qwen3_json_kwargs())
        try:
            response = client.chat.completions.create(**payload)
        except TypeError as exc:
            if "extra_body" not in str(exc):
                raise
            payload.pop("extra_body", None)
            response = client.chat.completions.create(**payload)
        message = response.choices[0].message
        content = message.content or "{}"
        if not message.content and getattr(message, "reasoning_content", None):
            raise RuntimeError("Local model returned reasoning instead of the required JSON response.")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            last_json_error = exc
            if attempt == 2:
                break
    raise RuntimeError(
        "Local model returned incomplete JSON after three attempts. "
        "Increase LMSTUDIO_MAX_TOKENS and LMSTUDIO_TIMEOUT, then restart Factory UI."
    ) from last_json_error
