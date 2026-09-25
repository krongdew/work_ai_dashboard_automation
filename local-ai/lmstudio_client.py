from __future__ import annotations
import os, json
from typing import Any
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
MODEL = os.getenv("LMSTUDIO_MODEL", "openai/gpt-oss-20b")
API_KEY = os.getenv("LMSTUDIO_API_KEY", "lm-studio")
TIMEOUT = float(os.getenv("LMSTUDIO_TIMEOUT", "300"))
client = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=TIMEOUT)

def list_models() -> list[str]:
    return [m.id for m in client.models.list().data]

def chat(messages: list[dict[str, Any]], temperature: float = 0.2, max_tokens: int | None = None) -> str:
    kwargs: dict[str, Any] = {"model": MODEL, "messages": messages, "temperature": temperature}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    r = client.chat.completions.create(**kwargs)
    return r.choices[0].message.content or ""

def generate_json(system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    response_format = {"type": "json_schema", "json_schema": {"name": "dashboard_spec", "strict": True, "schema": schema}}
    for attempt in range(2):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.1,
            max_tokens=4096,
            response_format=response_format,
        )
        content = response.choices[0].message.content or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            if attempt:
                raise
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": "Your previous JSON was incomplete or invalid. Return the complete JSON object only, matching the required schema."})
    raise RuntimeError("Local AI did not return JSON.")
