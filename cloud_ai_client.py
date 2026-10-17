from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from groq import Groq

load_dotenv(Path(__file__).resolve().with_name(".env"))

MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "llama-3.3-70b-versatile")
# Lighter, cheaper model for small structured tasks (semantic profile, normalization,
# requirement review). Falls back to the main model when not configured.
LIGHT_MODEL = os.getenv("GROQ_LIGHT_MODEL", "") or MODEL

# --- Proactive TPM pacing -------------------------------------------------
# The whole account shares one tokens-per-minute budget (both models). Instead
# of firing calls until one 429s and then waiting out a full minute, we track
# tokens spent in a rolling 60s window and PAUSE just enough before a call so we
# stay under the limit. This turns "burst then stall" into smooth spacing.
TPM_LIMIT = int(os.getenv("GROQ_TPM_LIMIT", "8000"))
_TPM_WINDOW = 60.0
_tpm_lock = threading.Lock()
_tpm_events: deque = deque()  # (timestamp, tokens)

# Optional status sink so the UI can show "waiting for AI quota (~Ns)".
pace_status = None  # set to a callable(message:str) by the caller if desired


def _tpm_used(now: float) -> int:
    while _tpm_events and now - _tpm_events[0][0] > _TPM_WINDOW:
        _tpm_events.popleft()
    return sum(t for _, t in _tpm_events)


def _tpm_record(tokens: int) -> None:
    with _tpm_lock:
        _tpm_events.append((time.time(), tokens))


def _tpm_wait(estimated: int) -> None:
    """Sleep (in small steps) until there is budget for `estimated` tokens."""
    # keep ~15% headroom so we rarely actually hit the hard 429
    ceiling = int(TPM_LIMIT * 0.85)
    for _ in range(120):  # cap total wait ~ a couple of windows
        with _tpm_lock:
            now = time.time()
            used = _tpm_used(now)
            if used + estimated <= ceiling or not _tpm_events:
                return
            oldest = _tpm_events[0][0]
        wait = max(1.0, _TPM_WINDOW - (time.time() - oldest) + 0.3)
        if callable(pace_status):
            try:
                pace_status(f"กำลังรอโควตา AI (~{int(wait)} วิ) เพื่อเลี่ยง rate limit")
            except Exception:
                pass
        time.sleep(min(wait, 5.0))


def generate_json(system_prompt: str, user_prompt: str, schema: dict[str, Any], light: bool = False) -> dict[str, Any]:
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
    # Estimate this call's token cost (prompt chars/3 + a response allowance) and
    # pace proactively so we spread calls under the window instead of bursting.
    est = int((len(messages[0]["content"]) + len(user_prompt)) / 3) + 1200
    _tpm_wait(est)
    # Light tasks lead with the small model; heavy tasks lead with the smart model.
    # The other model is kept as a fallback so a transient failure still recovers.
    primary = LIGHT_MODEL if light else MODEL
    secondary = MODEL if light else FALLBACK_MODEL
    models = [primary] + ([secondary] if secondary and secondary != primary else [])
    last_error: Exception | None = None
    import re as _re

    def _retry_after_seconds(msg: str) -> float:
        # Groq 429 messages embed e.g. "try again in 7.2s" or "Please try again in 1m2s".
        # Respect the FULL time the server asks (no cap) + a small cushion, so we stop
        # bursting a fresh request the instant a short cap expires.
        m = _re.search(r"try again in (\d+)m([0-9.]+)s", msg)
        if m:
            return int(m.group(1)) * 60 + float(m.group(2)) + 1.0
        m = _re.search(r"try again in ([0-9.]+)s", msg)
        if m:
            return float(m.group(1)) + 1.0
        return 0.0

    for model in models:
        # Per-model attempt budget: a few quick retries plus TPM-aware waits.
        for attempt in range(6):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.1,
                )
                usage = getattr(response, "usage", None)
                _tpm_record(getattr(usage, "total_tokens", None) or est)
                return json.loads(response.choices[0].message.content or "{}")
            except Exception as exc:
                last_error = exc
                message = str(exc)
                if "json_validate_failed" in message or "Failed to validate JSON" in message:
                    time.sleep(1)
                    continue
                if "429" in message or "rate_limit" in message:
                    # TPM is account-wide; falling back to the other model also 429s.
                    # Wait the FULL server-requested time (the whole minute if needed),
                    # then record a pseudo-spend so the pacer treats the window as full
                    # and future calls self-space instead of re-bursting.
                    wait = _retry_after_seconds(message) or min(60.0, 8 * (attempt + 1))
                    if callable(pace_status):
                        try:
                            pace_status(f"ชน rate limit — รอ {int(wait)} วิ แล้วลองใหม่ (ไม่ยิงซ้ำระหว่างรอ)")
                        except Exception:
                            pass
                    time.sleep(wait)
                    continue
                if "400" in message or "404" in message or "503" in message:
                    break
                if "500" not in message:
                    raise
                time.sleep(1 + attempt)
    raise RuntimeError(f"Groq models unavailable after retry: {last_error}") from last_error
