"""Language policy for AI-authored presentation text, never source data."""
from __future__ import annotations

import unicodedata
from typing import Any

POLICY_VERSION = "th-en-v1"
LANGUAGE_INSTRUCTION = (
    "Write all generated human-readable text in Thai or English ONLY. Prefer Thai; "
    "use English when uncertain. This includes dashboard titles, KPI names, chart titles, "
    "labels, summaries, units, warnings, explanations and limitations. Never write Chinese "
    "or other languages in generated display text. Preserve JSON keys, enum values, exact "
    "source field references, source/category values and calculation formulas unchanged."
)
TEXT_KEYS = {
    "dashboard_title", "purpose", "audience", "name", "title", "label",
    "description", "dataset_summary", "unit", "business_role", "limitations",
    "reason", "warning", "warnings", "insight_questions", "explanation",
}


def unsupported_text_paths(value: Any, path: str = "$", display: bool = False) -> list[str]:
    """Inspect display values only; allow original references and raw category values."""
    if isinstance(value, dict):
        return [
            issue
            for key, item in value.items()
            for issue in unsupported_text_paths(
                item, f"{path}.{key}", key in TEXT_KEYS or key == "display_labels" or path.endswith(".display_labels")
            )
        ]
    if isinstance(value, list):
        return [issue for index, item in enumerate(value)
                for issue in unsupported_text_paths(item, f"{path}[{index}]", display)]
    if display and isinstance(value, str):
        for char in value:
            if unicodedata.category(char)[0] in {"L", "M"}:
                script = unicodedata.name(char, "")
                if "THAI" not in script and "LATIN" not in script:
                    return [path]
    return []


def require_supported_text(value: Any) -> None:
    issues = unsupported_text_paths(value)
    if issues:
        raise ValueError(
            "Dashboard text must use Thai or English only. Regenerate or translate "
            "the display text before building. Invalid fields: " + ", ".join(issues[:12])
        )
