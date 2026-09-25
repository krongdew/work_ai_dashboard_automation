# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import re
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename
from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"
LOCAL_AI = ROOT / "local-ai"
DASHBOARD_SKILL = ROOT / "dashboard-automation" / "SKILL.md"
DATA_RULES = ROOT / "rules" / "data-rules.md"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(LOCAL_AI))

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
ALLOWED_UPLOAD_SUFFIXES = {".xlsx", ".xlsm", ".csv"}


def project_dir(name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("Project name must use letters, digits, hyphens, or underscores.")
    return PROJECTS / name


def read_json(path: Path, fallback: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_header(value: Any, index: int) -> str:
    text = str(value or "").strip().replace("\n", " ")
    return text or f"column_{index + 1}"


def scalar(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def load_sources(folder: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    sheets: list[dict[str, Any]] = []
    for path in sorted(folder.iterdir() if folder.exists() else []):
        if path.name.startswith("~$"):
            continue
        if path.suffix.lower() not in {".xlsx", ".xlsm", ".csv"}:
            continue
        if path.suffix.lower() == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as source:
                rows = list(csv.reader(source))
            groups = [("CSV", rows)]
        else:
            book = load_workbook(path, read_only=True, data_only=True)
            groups = [(sheet.title, list(sheet.iter_rows(values_only=True))) for sheet in book.worksheets]
            book.close()
        for sheet_name, rows in groups:
            if not rows:
                continue
            headers = [clean_header(value, index) for index, value in enumerate(rows[0])]
            sheet_rows = 0
            for row_number, values in enumerate(rows[1:], start=2):
                if not any(value not in (None, "") for value in values):
                    continue
                record = {headers[index]: scalar(values[index]) if index < len(values) else None for index in range(len(headers))}
                record["_source_file"] = path.name
                record["_source_sheet"] = sheet_name
                record["_source_row"] = row_number
                records.append(record)
                sheet_rows += 1
            sheets.append({"file": path.name, "sheet": sheet_name, "rows": sheet_rows, "columns": len(headers), "fields": headers})
    return records, sheets


def numeric(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("%", "")
        try:
            return float(text)
        except ValueError:
            return None
    return None


THAI_MONTHS = {
    "ม.ค.": (1, "ม.ค."), "ก.พ.": (2, "ก.พ."), "มี.ค.": (3, "มี.ค."), "เม.ย.": (4, "เม.ย."),
    "พ.ค.": (5, "พ.ค."), "มิ.ย.": (6, "มิ.ย."), "ก.ค.": (7, "ก.ค."), "ส.ค.": (8, "ส.ค."),
    "ก.ย.": (9, "ก.ย."), "ต.ค.": (10, "ต.ค."), "พ.ย.": (11, "พ.ย."), "ธ.ค.": (12, "ธ.ค."),
}
ENGLISH_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def parse_reporting_date(value: Any) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if not text or text in {"-", "n/a", "N/A", "ไม่ระบุ"}:
        return None
    normalized = text.replace(".", "/")
    thai_month = next((item for token, item in THAI_MONTHS.items() if token in text), None)
    english_month = next((month for token, month in ENGLISH_MONTHS.items() if token in text.lower()), None)
    numbers = [int(item) for item in re.findall(r"\d{1,4}", normalized)]
    if thai_month or english_month:
        month = thai_month[0] if thai_month else english_month
        year = next((item for item in numbers if item >= 60), None)
        if year is None:
            return None
        year = year + 2500 if year < 100 else (year + 543 if year < 2400 else year)
    elif len(numbers) == 1 and 60 <= numbers[0] <= 2700:
        year, month = numbers[0], 1
        year = year + 2500 if year < 100 else (year + 543 if year < 2400 else year)
    elif len(numbers) == 2 and any(60 <= item <= 2700 for item in numbers):
        year, month = next(item for item in numbers if item >= 60), 1
        year = year + 2500 if year < 100 else (year + 543 if year < 2400 else year)
    elif len(numbers) >= 3:
        first, second, third = numbers[:3]
        if first > 31:
            year, month = first, second
        elif third > 31:
            year, month = third, second
        else:
            return None
        year = year + 543 if year < 2400 else year
    else:
        return None
    if not 1 <= month <= 12 or not 2400 <= year <= 2700:
        return None
    return {"year_be": year, "month": month, "month_label": THAI_MONTHS[list(THAI_MONTHS)[month - 1]][1], "quarter": f"Q{(month - 1) // 3 + 1}"}


def field_role(name: str, values: list[Any], record_count: int) -> str:
    label = name.lower()
    distinct_ratio = len({str(value) for value in values}) / max(len(values), 1)
    numeric_ratio = sum(numeric(value) is not None for value in values) / max(len(values), 1)
    date_ratio = sum(parse_reporting_date(value) is not None for value in values) / max(len(values), 1)
    if re.search(r"id|หัส|code|เลขที่", label) or (numeric_ratio >= .8 and distinct_ratio >= .85):
        return "identifier"
    if re.search(r"date|วัน|เดือน|year|ปี", label) and (date_ratio >= .5 or numeric_ratio >= .7):
        return "date"
    if numeric_ratio >= .7 and distinct_ratio < .85:
        return "measure"
    return "category"


def profile_project(name: str) -> dict[str, Any]:
    directory = project_dir(name)
    records, sheets = load_sources(directory / "input")
    if not records:
        raise ValueError("No Excel or CSV files were found in the project's input folder.")
    all_fields = sorted({field for item in sheets for field in item["fields"]})
    fields = []
    date_quality: dict[str, Any] = {}
    for field in all_fields:
        values = [record.get(field) for record in records if record.get(field) not in (None, "")]
        numeric_count = sum(numeric(value) is not None for value in values)
        role = field_role(field, values, len(records))
        parsed_dates = [parse_reporting_date(value) for value in values]
        parsed_count = sum(value is not None for value in parsed_dates)
        field_type = "number" if role == "measure" else role
        examples = list(dict.fromkeys(str(value) for value in values))[:5]
        fields.append({"name": field, "type": field_type, "role": role, "non_null": len(values), "distinct": len({str(value) for value in values}), "numeric_ratio": round(numeric_count / max(len(values), 1), 3), "examples": examples})
        if role == "date":
            date_quality[field] = {"parsed": parsed_count, "unparsed": len(values) - parsed_count, "dominant_format": "normalized mixed date formats" if parsed_count else "unrecognized"}
    duplicates = len(records) - len({tuple(sorted((key, str(value)) for key, value in record.items() if not key.startswith("_"))) for record in records})
    profile = {
        "project": name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_files": sorted({sheet["file"] for sheet in sheets}),
        "records": len(records),
        "worksheets": sheets,
        "fields": fields,
        "quality": {"exact_duplicate_rows": duplicates, "missing_values": {field: sum(record.get(field) in (None, "") for record in records) for field in all_fields}, "date_parsing": date_quality},
    }
    write_json(directory / "output/metadata/dataset-profile.json", profile)
    return profile


def default_config(name: str, profile: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "category": "Uncategorized", "language": "th", "timezone": "Asia/Bangkok", "dashboard_type": "auto", "audience": "ผู้บริหารและผู้ปฏิบัติงาน", "show_insights": True, "show_data_table": True, "responsive": True, "theme": "mahidol-faculty", "source_files": profile["input_files"]}


DISPLAY_LABELS = {
    "_year_be": "ปีที่เกิดเหตุ (พ.ศ.)",
    "_academic_year_be": "ปีการศึกษา (พ.ศ.)",
    "_month_th": "เดือน",
    "_quarter": "ไตรมาส",
    "_source_file": "ไฟล์ต้นทาง",
    "record_count": "จำนวนรายการ",
    "unique_student_count": "จำนวนนักศึกษา",
}


def display_label(field: str, overrides: dict[str, Any] | None = None) -> str:
    if overrides and isinstance(overrides.get(field), str) and overrides[field].strip():
        return overrides[field].strip()
    return DISPLAY_LABELS.get(field, field.replace("_", " "))


def extract_label_overrides(instruction: str) -> dict[str, str]:
    aliases = {"year": "_year_be", "year_": "_year_be", "academic_year": "_academic_year_be", "month": "_month_th", "quarter": "_quarter"}
    overrides = {}
    for source, label in re.findall(r"(?:ฟิลเตอร์|filter|ข้อความบนฟิลเตอร์)\s*([A-Za-z_]+)\s*(?:เป็น|ว่า|ให้เป็น)\s*(?:คำว่า\s*)?['\"“]?([^'\"”\n,]+)", instruction, flags=re.IGNORECASE):
        field = aliases.get(source.lower(), source)
        overrides[field] = label.strip()
    return overrides


def student_analytics_spec(instruction: str, profile: dict[str, Any]) -> dict[str, Any] | None:
    fields = {field["name"] for field in profile["fields"]}
    if not {"จำนวนนักศึกษาในรุ่น", "จำนวนคนลาออก"}.issubset(fields):
        return None
    if not any(token in instruction for token in ("นักศึกษา", "ลาออก", "สำเร็จการศึกษา", "คณะ")):
        return None
    return {
        "dashboard_title": "ภาพรวมผลการศึกษาและการลาออกของนักศึกษา",
        "purpose": "ติดตามจำนวนนักศึกษา การลาออก และผลสำเร็จการศึกษาจากข้อมูลที่ผ่านการตรวจสอบ",
        "audience": "ผู้บริหารและผู้ปฏิบัติงานด้านการศึกษา",
        "kpis": [
            {"name": "จำนวนนักศึกษาทั้งหมด", "metric": "unique_student_count", "aggregation": "distinct-valid-student-id", "formula": "COUNT(DISTINCT รหัสนักศึกษา)"},
            {"name": "จำนวนนักศึกษาลาออก", "metric": "จำนวนคนลาออก", "aggregation": "sum"},
            {"name": "อัตราสำเร็จการศึกษาตามวงรอบ", "metric": "อัตราการจบตามวงรอบ", "aggregation": "average-percent"},
        ],
        "filters": ["_year_be", "_month_th", "_quarter", "คณะ_สาขา", "สถานะการจบตามวงรอบ"],
        "charts": [
            {"type": "pie", "title": "สัดส่วนนักศึกษาตามคณะ/สาขา", "dimension": "คณะ_สาขา", "metric": "unique_student_count", "formula": "COUNT(DISTINCT รหัสนักศึกษา) by คณะ_สาขา"},
            {"type": "bar", "title": "จำนวนนักศึกษาเปรียบเทียบตามปีการศึกษา", "dimension": "_academic_year_be", "metric": "unique_student_count", "formula": "COUNT(DISTINCT รหัสนักศึกษา) by ปีการศึกษาที่เข้า"},
            {"type": "line", "title": "จำนวนนักศึกษาลาออกตามเดือน", "dimension": "_month_th", "metric": "จำนวนคนลาออก"},
            {"type": "bar", "title": "จำนวนนักศึกษาลาออกตามปี", "dimension": "_year_be", "metric": "จำนวนคนลาออก"},
            {"type": "pie", "title": "สัดส่วนสาเหตุการลาออก", "dimension": "สาเหตุการลาออก", "metric": "จำนวนคนลาออก"},
            {"type": "bar", "title": "อัตราสำเร็จการศึกษาตามวงรอบ", "dimension": "_year_be", "metric": "อัตราการจบตามวงรอบ"},
            {"type": "pie", "title": "สัดส่วนสำเร็จและไม่สำเร็จการศึกษา", "dimension": "สถานะการจบตามวงรอบ", "metric": "record_count"},
        ],
        "insight_questions": ["จำนวนและสัดส่วนการลาออกเปลี่ยนแปลงตามช่วงเวลาอย่างไร", "คณะ/สาขาใดควรได้รับการติดตามเพิ่มเติม"],
        "calculation_notes": "จำนวนนักศึกษาใช้ COUNT(DISTINCT รหัสนักศึกษา) เท่านั้น ไม่รวมค่าจำนวนนักศึกษาในรุ่นที่ซ้ำในแต่ละแถว; อัตราจบแสดงร้อยละจาก source ที่ normalize เป็น 0-100 และไม่ใช้ผลรวมของอัตรา",
        "generated_by": "deterministic-requirement-planner",
        "last_instruction": instruction,
    }


def grounded_spec_errors(spec: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    """Reject a plan that cannot be rendered from the profiled dataset."""
    fields = {field["name"] for field in profile["fields"]}
    allowed_dimensions = fields | {"_year_be", "_academic_year_be", "_month_th", "_quarter", "_source_file"}
    allowed_metrics = fields | {"record_count", "unique_student_count"}
    errors = []
    charts = spec.get("charts")
    if not isinstance(charts, list) or not charts:
        return ["The specification must contain at least one chart."]
    for index, chart in enumerate(charts, start=1):
        if not isinstance(chart, dict):
            errors.append(f"Chart {index} is not an object.")
            continue
        dimension, metric = chart.get("dimension"), chart.get("metric")
        if dimension not in allowed_dimensions:
            errors.append(f"Chart {index} dimension {dimension!r} is not an available field.")
        if metric not in allowed_metrics:
            errors.append(f"Chart {index} metric {metric!r} is not an available field or supported derived metric.")
        for field in chart.get("source_fields", []):
            if field not in allowed_dimensions:
                errors.append(f"Chart {index} source field {field!r} is not an available field or supported derived dimension.")
        if chart.get("type") not in {"bar", "line", "pie"}:
            errors.append(f"Chart {index} type must be bar, line, or pie.")
    for index, kpi in enumerate(spec.get("kpis", []), start=1):
        if not isinstance(kpi, dict):
            errors.append(f"KPI {index} is not an object.")
            continue
        if kpi.get("metric") not in allowed_metrics:
            errors.append(f"KPI {index} metric {kpi.get('metric')!r} is not an available field or supported derived metric.")
        for field in kpi.get("source_fields", []):
            if field not in allowed_dimensions:
                errors.append(f"KPI {index} source field {field!r} is not an available field or supported derived dimension.")
    for field in spec.get("filters", []):
        if field not in allowed_dimensions:
            errors.append(f"Filter {field!r} is not an available field or supported derived dimension.")
    return errors


def requested_capability_errors(instruction: str, spec: dict[str, Any]) -> list[str]:
    """Validate universally-renderable requested features without relying on model prose."""
    normalized = instruction.lower()
    errors = []
    if any(token in normalized for token in ("ลูกศร", "arrow", "เปรียบเทียบข้อมูลกับปีล่าสุด", "latest year comparison")):
        comparisons = [item.get("comparison") for item in spec.get("kpis", []) if isinstance(item, dict)]
        if not any(isinstance(item, dict) and item.get("enabled") and item.get("period") == "latest_year_vs_previous_year" for item in comparisons):
            errors.append("Add a KPI with comparison.enabled=true and comparison.period=latest_year_vs_previous_year for the requested up/down arrow.")
    if any(token in normalized for token in ("เส้นเป้าหมาย", "target line")):
        if not any(isinstance(item, dict) and isinstance(item.get("target"), dict) for item in spec.get("charts", [])):
            errors.append("Add target.value and target.label to the requested chart for the target line.")
    return errors


def grounded_schema(profile: dict[str, Any]) -> dict[str, Any]:
    """Return a provider-compatible schema; field references are validated locally."""
    schema = read_json(LOCAL_AI / "schemas/dashboard-spec.schema.json", {})
    return schema


def cloud_safe_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Return only non-row-level metadata needed for Cloud dashboard planning."""
    pii_name = re.compile(r"name|surname|email|phone|address|ชื่อ|นามสกุล|อีเมล|โทร|ที่อยู่", re.IGNORECASE)
    fields = [
        {
            key: field[key]
            for key in ("name", "type", "role", "non_null", "distinct", "numeric_ratio")
            if key in field
        }
        for field in profile["fields"]
        if field.get("role") != "identifier" and not pii_name.search(field.get("name", ""))
    ]
    date_fields = {field["name"] for field in fields if field.get("role") == "date"}
    return {
        "records": profile.get("records", 0),
        "fields": fields,
        "date_parsing": {field: details for field, details in profile.get("quality", {}).get("date_parsing", {}).items() if field in date_fields},
        "derived_fields": ["_year_be", "_month_th", "_quarter"] if date_fields else [],
        "privacy": "This is metadata only. No source files, records, identifiers, or example values are included.",
    }


def planner_workflow_contract() -> str:
    """Load repository skills and provide Groq the enforceable planning subset."""
    if not DASHBOARD_SKILL.exists() or not DATA_RULES.exists():
        raise FileNotFoundError("Dashboard workflow skills are missing from the repository.")
    skill = DASHBOARD_SKILL.read_text(encoding="utf-8")
    data_rules = DATA_RULES.read_text(encoding="utf-8")
    skill_excerpt = skill[skill.index("## Rules"):skill.index("## Institutional theme")]
    data_excerpt = data_rules[data_rules.index("## Global data preparation skill"):data_rules.index("## Correction instruction skill")]
    return f"""REPOSITORY SKILL EXCERPTS (mandatory)
{skill_excerpt}

{data_excerpt}

PLANNER EXECUTION CONTRACT
You are the analytics planner in a local dashboard factory. Follow this order: discover/profile, quality review, analyze, define requirements, design, transform, build, QA, insights.
Raw input is read-only. Never fabricate values, silently delete rows, or mix projects. The application performs calculations and rendering locally; you must create a grounded plan only.
Treat field roles and quality metadata as evidence. Never use identifiers, codes, or near-unique numeric values as a sum, chart axis, filter, or KPI. For entities use COUNT(DISTINCT stable ID). Before SUM, require an additive row grain; repeated cohort/reference totals must not be summed. Rates and percentages are normalized to 0-100 then averaged only when comparable; never sum them. Ratios require a documented comparable non-zero denominator.
Use normalized BE year/month/quarter dimensions only when supplied. Do not mix fiscal and calendar periods. Every KPI/chart needs exact source fields, aggregation/formula, suitable dimension, limitation, and a business question. Prefer low-cardinality filters and readable chart groupings. Flag unsupported relationships, missing join keys, repeated totals, date parse gaps, and high-cardinality dimensions as limitations rather than guessing.
Design: KPI cards, trends for time, bars for comparisons/rankings, pie only for meaningful shares. Plan cross-filters, calculation provenance, and year-over-year comparison only when an equivalent prior period exists. The build/QA process independently verifies values; a numerical mismatch is not ready for publication."""


def uncovered_requirements(instruction: str, profile: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    """Use an independent structured review to check request coverage, not just field validity."""
    if not instruction:
        return []
    from cloud_ai_client import generate_json
    derived_fields = ["_year_be", "_month_th", "_quarter"] if any(field.get("role") == "date" for field in profile["fields"]) else []
    schema = {
        "type": "object", "additionalProperties": False, "required": ["requirements"],
        "properties": {"requirements": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["request", "status", "evidence"],
            "properties": {
                "request": {"type": "string"},
                "status": {"type": "string", "enum": ["covered", "unsupported", "missing"]},
                "evidence": {"type": "string"},
            },
        }}},
    }
    review = generate_json(
        "You are a strict dashboard requirements reviewer. Split every explicit user request into an atomic requirement. "
        "Mark covered only when a KPI or chart directly answers it. Mark unsupported when the profile cannot supply it. "
        "Mark missing for every other case. A request to rename a filter is covered when display_labels changes the label for its field. "
        "Derived fields are valid when listed below; a latest-year comparison can use _year_be. Return only JSON.",
        f"USER REQUEST:\n{instruction}\n\nDATA PROFILE:\n{json.dumps(cloud_safe_profile(profile), ensure_ascii=False)}\n\n"
        f"VALID DERIVED FIELDS:\n{json.dumps(derived_fields, ensure_ascii=False)}\n\nDASHBOARD PLAN:\n{json.dumps(spec, ensure_ascii=False)}",
        schema,
    )
    return [f"{item['request']}: {item['evidence']}" for item in review.get("requirements", []) if item.get("status") == "missing"]


def local_ai_spec(profile: dict[str, Any], instruction: str, current_spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ask the Cloud planner to create and repair a grounded dashboard plan."""
    from cloud_ai_client import generate_json
    schema = grounded_schema(profile)
    guidance = (LOCAL_AI / "prompts/dashboard-spec.md").read_text(encoding="utf-8")
    workflow = planner_workflow_contract()
    request_text = instruction or "Propose the most useful management dashboard supported by this dataset."
    available_fields = sorted(field["name"] for field in profile["fields"])
    allowed_references = available_fields + ["record_count", "unique_student_count", "_year_be", "_academic_year_be", "_month_th", "_quarter"]
    prompt = (
        f"{workflow}\n\n{guidance}\n\nUSER REQUEST:\n{request_text}\n\n"
        "DATA PROFILE (metadata only; field names must be copied exactly):\n"
        f"{json.dumps(cloud_safe_profile(profile), ensure_ascii=False)}\n\n"
        "Return each KPI as an object with name, metric, aggregation, formula, source_fields, limitations, and comparison. "
        "Use comparison.enabled=true and comparison.period=latest_year_vs_previous_year when the user requests an up/down KPI. "
        "Return each chart as an object with title, type (bar/line/pie), dimension, metric, aggregation, formula, source_fields, limitations, and optional target. "
        "When the user gives a chart target, set target.value, target.label, and target.year_be when supplied. "
        "Use filters to include only the filters requested or useful for the plan; omit a filter when the user asks to remove it. "
        "Use display_labels to rename a visible filter/axis label without changing its field name. "
        "Use only the exact field references in this allowlist for metric, dimension, source_fields, and filters. "
        "Never translate, shorten, or invent an alias for a field name.\n"
        f"ALLOWED FIELD REFERENCES:\n{json.dumps(allowed_references, ensure_ascii=False)}"
    )
    if current_spec:
        prompt += (
            "\n\nCURRENT SPEC TO REVISE:\n"
            f"{json.dumps(current_spec, ensure_ascii=False)}\n"
            "This is a revision, not a replacement. Preserve every valid chart, KPI, filter, and exact field reference unless the user explicitly asks to remove or replace it. "
            "The revised specification must contain at least one chart. Do not introduce a calculated metric such as a rate, count, share, or distribution unless the exact source field or a supported derived metric is in ALLOWED FIELD REFERENCES. "
            "When a requested calculation is unsupported, retain the valid current plan and state the limitation instead."
        )
    spec = generate_json("You are a careful cloud analytics planner. Return only grounded JSON.", prompt, schema)
    errors = grounded_spec_errors(spec, profile)
    if errors:
        repair_prompt = (
            f"{prompt}\n\nYOUR PREVIOUS SPECIFICATION FAILED VALIDATION:\n- "
            + "\n- ".join(errors)
            + "\nReplace every invalid alias with the semantically matching exact value from ALLOWED FIELD REFERENCES. "
            "Return a complete corrected JSON specification."
        )
        repaired = generate_json("You repair dashboard plans using only exact available fields. Return only grounded JSON.", repair_prompt, schema)
        errors = grounded_spec_errors(repaired, profile)
        if errors:
            raise ValueError("Local AI produced an unsupported dashboard plan: " + " ".join(errors))
        spec = repaired
    # A second model pass tends to replace exact field names with human-readable aliases.
    # Field grounding is enforced above; keep follow-up checks deterministic.
    missing = requested_capability_errors(instruction, spec)
    if not missing:
        return spec
    coverage_prompt = (
        f"{prompt}\n\nTHE REQUIREMENTS REVIEW FOUND THESE MISSING ITEMS:\n- "
        + "\n- ".join(missing)
        + "\nRevise the complete dashboard plan so every item is directly covered by a KPI or chart, or omit only items unsupported by the data profile."
    )
    covered_spec = generate_json("You repair dashboard plans so every explicit request is covered with grounded fields. Return only JSON.", coverage_prompt, schema)
    errors = grounded_spec_errors(covered_spec, profile)
    if errors:
        raise ValueError("Local AI produced an unsupported dashboard plan after requirement review: " + " ".join(errors))
    missing = requested_capability_errors(instruction, covered_spec)
    if missing:
        raise ValueError("Local AI plan does not yet cover the requested dashboard: " + " ".join(missing))
    return covered_spec


def suggest_spec(name: str, instruction: str = "") -> dict[str, Any]:
    directory = project_dir(name)
    profile = read_json(directory / "output/metadata/dataset-profile.json", None)
    if not profile:
        profile = profile_project(name)
    try:
        spec = local_ai_spec(profile, instruction.strip())
        source = "groq-ai"
    except Exception as exc:
        raise ValueError(f"Groq AI could not create the specification: {exc}") from exc
    spec["generated_by"] = source
    if instruction.strip():
        spec["last_instruction"] = instruction.strip()
    write_json(directory / "output/metadata/dashboard-spec.local-ai.json", spec)
    return spec


def improve_spec(name: str, instruction: str) -> dict[str, Any]:
    directory = project_dir(name)
    profile = read_json(directory / "output/metadata/dataset-profile.json", None)
    current_spec = read_json(directory / "output/metadata/dashboard-spec.local-ai.json", None)
    if not profile or not current_spec:
        raise ValueError("Create a data profile and Local AI specification before requesting an improvement.")
    instruction = instruction.strip()
    if not instruction:
        raise ValueError("Enter an improvement request.")
    try:
        spec = local_ai_spec(profile, instruction, current_spec)
    except Exception as exc:
        raise ValueError(f"Groq AI could not revise the specification: {exc}") from exc
    revisions = directory / "output/metadata/spec-revisions"
    revisions.mkdir(parents=True, exist_ok=True)
    revision = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_json(revisions / f"{revision}-before.json", current_spec)
    write_json(revisions / f"{revision}-request.json", {"instruction": instruction, "timestamp": datetime.now(timezone.utc).isoformat()})
    spec.setdefault("generated_by", "groq-ai")
    spec["last_instruction"] = instruction
    label_overrides = extract_label_overrides(instruction)
    if label_overrides:
        spec["display_labels"] = {**(spec.get("display_labels") if isinstance(spec.get("display_labels"), dict) else {}), **label_overrides}
    write_json(directory / "output/metadata/dashboard-spec.local-ai.json", spec)
    write_json(revisions / f"{revision}-after.json", spec)
    return spec


def render_dashboard_legacy(name: str, config: dict[str, Any], spec: dict[str, Any], records: list[dict[str, Any]]) -> str:
    fields = [key for record in records for key in record if not key.startswith("_")]
    fields = list(dict.fromkeys(fields))
    number_fields = [field for field in fields if sum(numeric(row.get(field)) is not None for row in records) / max(len(records), 1) >= .8]
    category_fields = [field for field in fields if field not in number_fields]
    kpis = [item for item in spec.get("kpis", []) if isinstance(item, dict)]
    charts = [item for item in spec.get("charts", []) if isinstance(item, dict)]
    metric = next((item.get("metric") for item in kpis if item.get("metric") in number_fields), "record_count")
    dimension = next(
        (
            item.get("dimension")
            or item.get("x_axis")
            or item.get("data_field")
            or next((field for field in item.get("fields", []) if field in category_fields), None)
            for item in charts
            if (
                (item.get("dimension") or item.get("x_axis") or item.get("data_field")) in category_fields
                or any(field in category_fields for field in item.get("fields", []))
            )
        ),
        category_fields[0] if category_fields else "_source_file",
    )
    data = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
    return f'''<!doctype html><html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{spec.get("dashboard_title", name)}</title><style>
:root{{--primary:#0B2B5E;--secondary:#263988;--gold:#FECD54;--bg:#F4F5F9;--surface:#fff;--border:#D9DEE8;--text:#1F2937;--muted:#6B7280}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:Georgia,"Noto Serif Thai",serif}}main{{max-width:1440px;margin:auto;padding:18px clamp(14px,3vw,44px) 44px}}header{{display:flex;justify-content:space-between;gap:18px;align-items:center;background:var(--surface);border:1px solid var(--gold);border-top:4px solid var(--gold);padding:18px 22px}}h1{{color:var(--primary);margin:0;font-size:clamp(1.4rem,3vw,2.25rem)}}p{{color:var(--muted)}}.badge{{padding:7px 10px;background:#fff9e8;color:var(--primary);font:700 .75rem ui-sans-serif,sans-serif}}.controls,.kpis,.grid{{display:grid;gap:14px;margin-top:18px}}.controls{{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}}select{{padding:10px;border:1px solid var(--border);background:#fff;color:var(--text)}}.kpis{{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}}.card,.panel{{background:var(--surface);border:1px solid var(--border);border-radius:6px}}.card{{border-top:3px solid var(--primary);padding:16px}}.card span{{font:700 .75rem ui-sans-serif,sans-serif;color:var(--muted)}}.card strong{{display:block;font-size:1.55rem;color:var(--primary);margin-top:8px}}.grid{{grid-template-columns:1.2fr .8fr}}.panel{{padding:18px}}h2{{margin:0 0 14px;color:var(--primary);font-size:1.05rem}}.bar-row{{display:grid;grid-template-columns:minmax(100px,1fr) 2fr auto;gap:10px;align-items:center;margin:11px 0;font:13px ui-sans-serif,sans-serif}}.track{{height:12px;background:var(--border)}}.bar{{height:100%;background:var(--secondary)}}table{{width:100%;border-collapse:collapse;font:12px ui-sans-serif,sans-serif}}th,td{{padding:9px;text-align:left;border-bottom:1px solid var(--border)}}th{{color:var(--primary);background:#f4f5f9}}.table{{overflow:auto;max-height:410px}}@media(max-width:760px){{header,.grid{{display:block}}.grid .panel{{margin-top:14px}}.bar-row{{grid-template-columns:105px 1fr}}.bar-row b{{grid-column:2}}}}
</style></head><body><main><header><div><p>Mahidol Faculty Dashboard</p><h1>{spec.get("dashboard_title", name)}</h1><p>{spec.get("purpose", "")}</p></div><div class="badge">THEME: {config.get("theme", "mahidol-faculty")}</div></header><section class="controls"><label>ตัวกรอง <select id="filter"><option value="">ทั้งหมด</option></select></label></section><section class="kpis" id="kpis"></section><section class="grid"><article class="panel"><h2>ภาพรวมตาม {dimension}</h2><div id="bars"></div></article><article class="panel"><h2>คำถามเชิงวิเคราะห์</h2><div id="questions"></div></article><article class="panel" style="grid-column:1/-1"><h2>รายละเอียดข้อมูล</h2><div class="table"><table id="table"></table></div></article></section></main><script>const rows={data};const metric={json.dumps(metric)};const dimension={json.dumps(dimension)};const fields={json.dumps(fields,ensure_ascii=False)};const fmt=new Intl.NumberFormat('th-TH',{{maximumFractionDigits:2}});const filter=document.querySelector('#filter');[...new Set(rows.map(r=>String(r[dimension]??'ไม่ระบุ'))) ].sort().forEach(value=>filter.add(new Option(value,value)));function value(row){{return metric==='record_count'?1:Number(String(row[metric]??0).replaceAll(',','').replace('%',''))||0}}function render(){{const selected=filter.value;const shown=rows.filter(row=>!selected||String(row[dimension]??'ไม่ระบุ')===selected);const total=shown.reduce((sum,row)=>sum+value(row),0);document.querySelector('#kpis').innerHTML=`<article class="card"><span>จำนวนรายการ</span><strong>${{fmt.format(shown.length)}}</strong></article><article class="card"><span>${{metric}}</span><strong>${{fmt.format(total)}}</strong></article><article class="card"><span>แหล่งข้อมูล</span><strong>${{fmt.format(new Set(shown.map(row=>row._source_file)).size)}}</strong></article>`;const groups={{}};shown.forEach(row=>{{const key=String(row[dimension]??'ไม่ระบุ');groups[key]=(groups[key]||0)+value(row)}});const items=Object.entries(groups).sort((a,b)=>b[1]-a[1]).slice(0,10);const max=Math.max(...items.map(item=>item[1]),1);document.querySelector('#bars').innerHTML=items.map(([label,amount])=>`<div class="bar-row"><span>${{label}}</span><div class="track"><div class="bar" style="width:${{amount/max*100}}%"></div></div><b>${{fmt.format(amount)}}</b></div>`).join('')||'<p>ไม่พบข้อมูล</p>';document.querySelector('#questions').innerHTML={json.dumps(spec.get("insight_questions", []),ensure_ascii=False)}.map(question=>`<p>• ${{question}}</p>`).join('');document.querySelector('#table').innerHTML=`<thead><tr>${{fields.map(field=>`<th>${{field}}</th>`).join('')}}</tr></thead><tbody>${{shown.slice(0,200).map(row=>`<tr>${{fields.map(field=>`<td>${{row[field]??''}}</td>`).join('')}}</tr>`).join('')}}</tbody>`}}filter.onchange=render;render();</script></body></html>'''


def render_dashboard(name: str, config: dict[str, Any], spec: dict[str, Any], records: list[dict[str, Any]]) -> str:
    fields = list(dict.fromkeys(key for row in records for key in row if not key.startswith("_")))
    numeric_fields = {field for field in fields if sum(numeric(row.get(field)) is not None for row in records) / max(len(records), 1) >= 0.8}
    chart_plans = []
    for index, chart in enumerate(item for item in spec.get("charts", []) if isinstance(item, dict)):
        candidates = [field for field in chart.get("fields", []) if field in fields]
        dimension = chart.get("dimension") if chart.get("dimension") in fields else next((field for field in candidates if field not in numeric_fields), candidates[0] if candidates else "_source_file")
        metric = chart.get("metric") if chart.get("metric") in numeric_fields else next((field for field in candidates if field in numeric_fields and field != dimension), "record_count")
        chart_plans.append({"id": f"chart-{index}", "title": chart.get("title", f"Chart {index + 1}"), "type": chart.get("type", "bar"), "dimension": dimension, "metric": metric})
    if not chart_plans:
        chart_plans = [{"id": "chart-0", "title": "จำนวนรายการตามแหล่งข้อมูล", "type": "bar", "dimension": "_source_file", "metric": "record_count"}]
    chart_cards = "".join(f'<article class="panel"><h2>{plan["title"]}</h2><div class="chart" id="{plan["id"]}"></div></article>' for plan in chart_plans)
    data = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
    return f'''<!doctype html><html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{spec.get("dashboard_title", name)}</title><style>
:root{{--primary:#0B2B5E;--secondary:#263988;--gold:#FECD54;--bg:#F4F5F9;--surface:#fff;--border:#D9DEE8;--text:#1F2937;--muted:#6B7280}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:Georgia,"Noto Serif Thai",serif}}main{{max-width:1440px;margin:auto;padding:18px clamp(14px,3vw,44px) 44px}}header,.panel,.card{{background:var(--surface);border:1px solid var(--border);border-radius:6px}}header{{display:flex;justify-content:space-between;gap:18px;align-items:center;border-top:4px solid var(--gold);padding:18px 22px}}h1,h2{{color:var(--primary);margin:0}}h1{{font-size:clamp(1.4rem,3vw,2.25rem)}}h2{{font-size:1.05rem;margin-bottom:14px}}p{{color:var(--muted)}}.badge{{padding:7px 10px;background:#fff9e8;color:var(--primary);font:700 .75rem ui-sans-serif,sans-serif}}.controls,.kpis,.grid{{display:grid;gap:14px;margin-top:18px}}.controls{{grid-template-columns:minmax(220px,360px)}}select{{padding:10px;border:1px solid var(--border);background:#fff}}.kpis{{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}}.card{{border-top:3px solid var(--primary);padding:16px}}.card span{{font:700 .75rem ui-sans-serif,sans-serif;color:var(--muted)}}.card strong{{display:block;font-size:1.55rem;color:var(--primary);margin-top:8px}}.grid{{grid-template-columns:repeat(auto-fit,minmax(330px,1fr))}}.panel{{padding:18px;overflow:hidden}}.chart{{display:grid;gap:10px}}.bar-row{{display:grid;grid-template-columns:minmax(95px,1fr) 2fr auto;gap:9px;align-items:center;font:12px ui-sans-serif,sans-serif}}.track{{height:12px;background:var(--border)}}.bar{{height:100%;background:var(--secondary)}}.line{{height:155px;display:flex;align-items:end;gap:7px;border-bottom:1px solid var(--border)}}.point{{flex:1;min-width:18px;background:var(--secondary);position:relative}}.point span{{position:absolute;bottom:calc(100% + 4px);font:10px ui-sans-serif,sans-serif;white-space:nowrap;transform:rotate(-35deg);transform-origin:left bottom}}table{{width:100%;border-collapse:collapse;font:12px ui-sans-serif,sans-serif}}th,td{{padding:9px;text-align:left;border-bottom:1px solid var(--border)}}th{{color:var(--primary);background:#F4F5F9}}.table{{overflow:auto;max-height:410px}}@media(max-width:760px){{header{{display:block}}.grid{{grid-template-columns:1fr}}.bar-row{{grid-template-columns:95px 1fr}}.bar-row b{{grid-column:2}}}}
</style></head><body><main><header><div><p>Mahidol Faculty Dashboard</p><h1>{spec.get("dashboard_title", name)}</h1><p>{spec.get("purpose", "")}</p></div><div class="badge">THEME: {config.get("theme", "mahidol-faculty")}</div></header><section class="controls"><label>ตัวกรอง <select id="filter"><option value="">ทั้งหมด</option></select></label></section><section class="kpis" id="kpis"></section><section class="grid">{chart_cards}<article class="panel"><h2>คำถามเชิงวิเคราะห์</h2><div id="questions"></div></article><article class="panel"><h2>รายละเอียดข้อมูล</h2><div class="table"><table id="table"></table></div></article></section></main><script>
const rows={data}, charts={json.dumps(chart_plans, ensure_ascii=False)}, fields={json.dumps(fields, ensure_ascii=False)}, questions={json.dumps(spec.get("insight_questions", []), ensure_ascii=False)};const fmt=new Intl.NumberFormat('th-TH',{{maximumFractionDigits:2}}),filter=document.querySelector('#filter');const options=[...new Set(rows.map(row=>row._source_file))].sort();options.forEach(value=>filter.add(new Option(value,value)));const amount=(row,metric)=>metric==='record_count'?1:Number(String(row[metric]??0).replaceAll(',','').replace('%',''))||0;function escape(value){{return String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;')}}function draw(plan,shown){{const groups={{}};shown.forEach(row=>{{const key=String(row[plan.dimension]??'ไม่ระบุ');groups[key]=(groups[key]||0)+amount(row,plan.metric)}});const items=Object.entries(groups).sort((a,b)=>plan.type==='line'?String(a[0]).localeCompare(String(b[0]),'th',{{numeric:true}}):b[1]-a[1]).slice(0,12),max=Math.max(...items.map(item=>item[1]),1),target=document.querySelector('#'+plan.id);if(plan.type==='line'){{target.innerHTML='<div class="line">'+items.map(([label,value])=>`<div class="point" style="height:${{Math.max(value/max*100,3)}}%"><span>${{escape(label)}} (${{fmt.format(value)}})</span></div>`).join('')+'</div>'}}else{{target.innerHTML=items.map(([label,value])=>`<div class="bar-row"><span>${{escape(label)}}</span><div class="track"><div class="bar" style="width:${{value/max*100}}%"></div></div><b>${{fmt.format(value)}}</b></div>`).join('')||'<p>ไม่พบข้อมูล</p>'}}}}function render(){{const shown=rows.filter(row=>!filter.value||row._source_file===filter.value);document.querySelector('#kpis').innerHTML=`<article class="card"><span>จำนวนรายการ</span><strong>${{fmt.format(shown.length)}}</strong></article><article class="card"><span>แหล่งข้อมูล</span><strong>${{fmt.format(new Set(shown.map(row=>row._source_file)).size)}}</strong></article><article class="card"><span>กราฟตาม Spec</span><strong>${{charts.length}}</strong></article>`;charts.forEach(plan=>draw(plan,shown));document.querySelector('#questions').innerHTML=questions.map(item=>`<p>• ${{escape(item)}}</p>`).join('');document.querySelector('#table').innerHTML=`<thead><tr>${{fields.map(field=>`<th>${{escape(field)}}</th>`).join('')}}</tr></thead><tbody>${{shown.slice(0,200).map(row=>`<tr>${{fields.map(field=>`<td>${{escape(row[field])}}</td>`).join('')}}</tr>`).join('')}}</tbody>`}}filter.onchange=render;render();
</script></body></html>'''


def render_dashboard_standard(name: str, config: dict[str, Any], spec: dict[str, Any], records: list[dict[str, Any]]) -> str:
    fields = list(dict.fromkeys(key for row in records for key in row if not key.startswith("_")))
    numeric_fields = [field for field in fields if sum(numeric(row.get(field)) is not None for row in records) / max(len(records), 1) >= 0.8]
    category_fields = [field for field in fields if field not in numeric_fields]
    charts = [item for item in spec.get("charts", []) if isinstance(item, dict)]
    plans = []
    for index, chart in enumerate(charts[:4]):
        dimension = chart.get("dimension") if chart.get("dimension") in fields else next((field for field in category_fields if field in chart.get("fields", [])), category_fields[0] if category_fields else "_source_file")
        metric = chart.get("metric") if chart.get("metric") in numeric_fields else (numeric_fields[0] if numeric_fields else "record_count")
        plans.append({"id": f"chart-{index}", "title": chart.get("title", f"ภาพรวมตาม {dimension}"), "dimension": dimension, "metric": metric})
    if not plans:
        plans.append({"id": "chart-0", "title": "จำนวนรายการตามแหล่งข้อมูล", "dimension": "_source_file", "metric": "record_count"})
    chart_html = "".join(f'<article class="panel"><h2>{plan["title"]}</h2><div class="chart" id="{plan["id"]}"></div></article>' for plan in plans)
    template = '''<!doctype html><html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title><style>
:root{--primary:#0B2B5E;--secondary:#263988;--gold:#FECD54;--bg:#F4F5F9;--surface:#fff;--border:#D9DEE8;--text:#1F2937;--muted:#6B7280;--success:#0F8F83;--danger:#C94A4A}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Georgia,"Noto Serif Thai",serif}main{max-width:1440px;margin:auto;padding:18px clamp(14px,3vw,44px) 44px}header,.panel,.card{background:var(--surface);border:1px solid var(--border);border-radius:6px}header{display:grid;grid-template-columns:minmax(240px,1fr) minmax(260px,1.25fr) auto;gap:18px;align-items:center;border-top:4px solid var(--gold);padding:16px 18px}.identity{display:flex;align-items:center;gap:12px;color:var(--primary);font:700 13px ui-sans-serif,sans-serif}.identity img{width:70px;height:70px;object-fit:contain}.title{text-align:center}.title p,.identity small{margin:0;color:var(--muted);font:12px ui-sans-serif,sans-serif}.title h1,h2{color:var(--primary);margin:4px 0 0}.title h1{font-size:clamp(1.4rem,3vw,2.25rem)}.badge{padding:8px 10px;background:#fff9e8;border:1px solid var(--gold);color:var(--primary);font:700 .75rem ui-sans-serif,sans-serif}.controls,.kpis,.grid{display:grid;gap:14px;margin-top:18px}.controls{grid-template-columns:repeat(auto-fit,minmax(180px,1fr));align-items:end}label{display:grid;gap:6px;color:var(--primary);font:700 12px ui-sans-serif,sans-serif}select,button{min-height:38px;padding:8px 10px;border:1px solid var(--border);background:#fff;color:var(--text);font:inherit}button{cursor:pointer}button:hover,button.active{border-color:var(--primary);background:#edf2fb}.kpis{grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}.card{border-top:3px solid var(--primary);padding:16px}.card span{font:700 .75rem ui-sans-serif,sans-serif;color:var(--muted)}.card strong{display:block;font-size:1.55rem;color:var(--primary);margin-top:8px}.delta{display:block;margin-top:7px;font:700 12px ui-sans-serif,sans-serif}.delta.good{color:var(--success)}.delta.bad{color:var(--danger)}.delta.neutral{color:var(--muted)}.grid{grid-template-columns:repeat(auto-fit,minmax(330px,1fr))}.panel{padding:18px;overflow:hidden}h2{font-size:1.05rem;margin:0 0 14px}.chart{display:grid;gap:7px}.bar-row{display:grid;grid-template-columns:minmax(85px,1fr) 2fr auto;gap:9px;align-items:center;font:12px ui-sans-serif,sans-serif}.bar-label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left;border:0;background:none;padding:0}.track{height:13px;background:var(--border);overflow:hidden}.bar{height:100%;background:var(--secondary);animation:grow .45s ease both}@keyframes grow{from{width:0!important}}table{width:100%;border-collapse:collapse;font:12px ui-sans-serif,sans-serif}th,td{padding:9px;text-align:left;border-bottom:1px solid var(--border)}th{color:var(--primary);background:#f4f5f9}.table{overflow:auto;max-height:360px}.empty{color:var(--muted);font:13px ui-sans-serif,sans-serif}@media(max-width:820px){header{grid-template-columns:1fr}.title{text-align:left}.badge{width:max-content}}@media(prefers-reduced-motion:reduce){.bar{animation:none}}</style></head><body><main><header><div class="identity"><img src="assets/logo.png" alt="ตรามหาวิทยาลัยมหิดล"><div>คณะศิลปศาสตร์ มหาวิทยาลัยมหิดล<br><small>Faculty of Liberal Arts, Mahidol University</small></div></div><div class="title"><p>การวิเคราะห์ผลการดำเนินงาน</p><h1>__TITLE__</h1><p>__PURPOSE__</p></div><div class="badge">THEME: __THEME__</div></header><section class="controls"><label>ปีรายงาน (พ.ศ.) <select id="year"><option value="">ทั้งหมด</option></select></label><label>แหล่งข้อมูล <select id="source"><option value="">ทั้งหมด</option></select></label><button id="clear" type="button">ล้างตัวกรองกราฟ</button></section><section class="kpis" id="kpis"></section><section class="grid">__CHARTS__<article class="panel"><h2>รายละเอียดข้อมูล</h2><div class="table"><table id="table"></table></div></article></section></main><script>
const rows=__ROWS__,plans=__PLANS__,fields=__FIELDS__,fmt=new Intl.NumberFormat('th-TH',{maximumFractionDigits:2});
const yearSelect=document.querySelector('#year'),sourceSelect=document.querySelector('#source'),clearButton=document.querySelector('#clear');let selected=null;
const amount=(row,metric)=>metric==='record_count'?1:Number(String(row[metric]??0).replaceAll(',','').replace('%',''))||0;
function reportingYear(row){for(const field of fields){const raw=row[field], label=String(field).toLowerCase();if(raw==null)continue;const text=String(raw);let match=(label.includes('ปี')||label.includes('year'))&&text.match(/(?:18|19|20|21|22|23|24|25|26)\d{2}/);if(!match&&(label.includes('date')||label.includes('วัน'))){match=text.match(/(?:18|19|20|21|22|23|24|25|26)\d{2}/)}if(match){const value=Number(match[0]);return value<2400?value+543:value}}return null}
function esc(value){return String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;')}
const years=[...new Set(rows.map(reportingYear).filter(Boolean))].sort((a,b)=>b-a);years.forEach(year=>yearSelect.add(new Option(year,year)));[...new Set(rows.map(row=>row._source_file))].sort().forEach(value=>sourceSelect.add(new Option(value,value)));
function shownRows(){return rows.filter(row=>{if(yearSelect.value&&String(reportingYear(row))!==yearSelect.value)return false;if(sourceSelect.value&&row._source_file!==sourceSelect.value)return false;return !selected||String(row[selected.field]??'ไม่ระบุ')===selected.value})}
function delta(current,prior,lowerBetter){if(prior===null||prior===0)return '<span class="delta neutral">ไม่มีฐานเปรียบเทียบ</span>';const change=current-prior,pct=change/Math.abs(prior)*100,good=lowerBetter?change<0:change>0,arrow=change>=0?'▲':'▼';return `<span class="delta ${good?'good':'bad'}">${arrow} ${fmt.format(Math.abs(pct))}% เทียบปีก่อน</span>`}
function renderKpis(data){const metric=plans[0].metric,year=yearSelect.value?Number(yearSelect.value):years[0],current=data.filter(row=>!year||reportingYear(row)===year).reduce((sum,row)=>sum+amount(row,metric),0);const priorRows=year?rows.filter(row=>reportingYear(row)===year-1&&(!sourceSelect.value||row._source_file===sourceSelect.value)&&(!selected||String(row[selected.field]??'ไม่ระบุ')===selected.value)):[];const prior=priorRows.length?priorRows.reduce((sum,row)=>sum+amount(row,metric),0):null;const lowerBetter=/cost|expense|ค่าใช้จ่าย|ต้นทุน/i.test(metric);document.querySelector('#kpis').innerHTML=`<article class="card"><span>${esc(metric)}</span><strong>${fmt.format(current)}</strong>${delta(current,prior,lowerBetter)}</article><article class="card"><span>จำนวนรายการ</span><strong>${fmt.format(data.length)}</strong>${delta(data.length,year?rows.filter(row=>reportingYear(row)===year-1).length:null,false)}</article><article class="card"><span>ปีเปรียบเทียบ</span><strong>${year?year+' / '+(year-1):'ไม่มีปี'}</strong><span class="delta neutral">${selected?'กรอง: '+esc(selected.value):'ข้อมูลทั้งหมด'}</span></article>`}
function draw(plan,data){const groups={};data.forEach(row=>{const key=String(row[plan.dimension]??'ไม่ระบุ');groups[key]=(groups[key]||0)+amount(row,plan.metric)});const items=Object.entries(groups).sort((a,b)=>b[1]-a[1]).slice(0,12),max=Math.max(...items.map(item=>item[1]),1),target=document.querySelector('#'+plan.id);target.innerHTML=items.length?items.map(([label,value])=>`<div class="bar-row"><button class="bar-label ${selected&&selected.field===plan.dimension&&selected.value===label?'active':''}" data-field="${esc(plan.dimension)}" data-value="${esc(label)}" title="กรองตาม ${esc(label)}">${esc(label)}</button><div class="track"><div class="bar" style="width:${Math.max(value/max*100,2)}%"></div></div><b>${fmt.format(value)}</b></div>`).join(''):'<p class="empty">ไม่พบข้อมูล</p>';target.querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>{selected={field:button.dataset.field,value:button.dataset.value};render()}))}
function renderTable(data){document.querySelector('#table').innerHTML='<thead><tr>'+fields.map(field=>`<th>${esc(field)}</th>`).join('')+'</tr></thead><tbody>'+data.slice(0,100).map(row=>'<tr>'+fields.map(field=>`<td>${esc(row[field])}</td>`).join('')+'</tr>').join('')+'</tbody>'}
function render(){const data=shownRows();renderKpis(data);plans.forEach(plan=>draw(plan,data));renderTable(data)}yearSelect.addEventListener('change',render);sourceSelect.addEventListener('change',render);clearButton.addEventListener('click',()=>{selected=null;render()});render();
</script></body></html>'''
    return (template.replace("__TITLE__", str(spec.get("dashboard_title", name)))
        .replace("__PURPOSE__", str(spec.get("purpose", "")))
        .replace("__THEME__", str(config.get("theme", "mahidol-faculty")))
        .replace("__CHARTS__", chart_html)
        .replace("__ROWS__", json.dumps(records, ensure_ascii=False, separators=(",", ":")))
        .replace("__PLANS__", json.dumps(plans, ensure_ascii=False))
        .replace("__FIELDS__", json.dumps(fields, ensure_ascii=False)))


def analytical_records(records: list[dict[str, Any]], profile: dict[str, Any]) -> list[dict[str, Any]]:
    date_fields = [field["name"] for field in profile["fields"] if field.get("role") == "date"]
    parse_counts = profile["quality"].get("date_parsing", {})
    primary_date = max(date_fields, key=lambda field: ("เดือน" in field or "วัน" in field or "date" in field.lower(), parse_counts.get(field, {}).get("parsed", 0)), default=None)
    prepared = []
    for record in records:
        item = dict(record)
        for field in ("คณะ_สาขา", "สถานะการจบตามวงรอบ", "สาเหตุการลาออก"):
            if item.get(field) is not None:
                text = str(item[field]).strip().lower()
                if field == "คณะ_สาขา":
                    item[field] = "วิศวกรรมศาสตร์" if "วิศว" in text or text == "eng" else ("บริหารธุรกิจ" if "บริหาร" in text else ("วิทยาศาสตร์" if "วิทย" in text else ("ศิลปศาสตร์" if "human" in text or "ศิลป" in text else str(item[field]).strip())))
                elif field == "สถานะการจบตามวงรอบ":
                    item[field] = "สำเร็จการศึกษา" if any(token in text for token in ("จบ", "pass")) and "ไม่จบ" not in text else ("ไม่สำเร็จการศึกษา" if any(token in text for token in ("ไม่จบ", "fail", "error")) else "ไม่ระบุ")
                elif field == "สาเหตุการลาออก":
                    item[field] = "ปัญหาการเงิน" if any(token in text for token in ("เงิน", "financial", "ค่าใช้จ่าย")) else ("ปัญหาสุขภาพ" if any(token in text for token in ("สุขภาพ", "ป่วย")) else ("ผลการเรียน" if any(token in text for token in ("เรียน", "เกรด", "academic")) else ("ครอบครัว/ส่วนตัว" if any(token in text for token in ("family", "ครอบครัว", "personal", "ภาระ")) else ("ย้าย/เปลี่ยนสาขา" if any(token in text for token in ("ย้าย", "เปลี่ยน")) else "ไม่ระบุ/อื่น ๆ"))))
        parsed = parse_reporting_date(record.get(primary_date)) if primary_date else None
        if parsed:
            item["_year_be"] = parsed["year_be"]
            item["_month_th"] = parsed["month_label"]
            item["_quarter"] = parsed["quarter"]
        academic_year = parse_reporting_date(record.get("ปีการศึกษาที่เข้า"))
        if academic_year:
            item["_academic_year_be"] = academic_year["year_be"]
        prepared.append(item)
    return prepared


def render_dashboard_qa(name: str, config: dict[str, Any], spec: dict[str, Any], profile: dict[str, Any], records: list[dict[str, Any]]) -> str:
    prepared = analytical_records(records, profile)
    roles = {field["name"]: field.get("role") for field in profile["fields"]}
    fields = [field["name"] for field in profile["fields"]]
    measures = [field for field in fields if roles[field] == "measure"]
    dimensions = [field for field in fields if roles[field] == "category"] + ["_year_be", "_academic_year_be", "_month_th", "_quarter"]
    plans = []
    issues = []
    for index, chart in enumerate(item for item in spec.get("charts", []) if isinstance(item, dict)):
        candidates = [field for field in chart.get("fields", []) if field in fields]
        date_candidate = next((field for field in candidates if roles.get(field) == "date"), None)
        normalized_date_dimension = "_month_th" if date_candidate and ("month" in chart.get("title", "").lower() or chart.get("type") == "line") else "_year_be"
        dimension = chart.get("dimension") if chart.get("dimension") in dimensions else (normalized_date_dimension if date_candidate else next((field for field in candidates if field in dimensions), None))
        if not dimension:
            issues.append(f"{chart.get('title', 'กราฟ')}: ไม่มีมิติข้อมูลที่เหมาะสม จึงไม่แสดง")
            continue
        distinct = len({str(row.get(dimension)) for row in prepared if row.get(dimension) not in (None, "")})
        if distinct > 20:
            issues.append(f"{chart.get('title', dimension)}: มี {distinct} กลุ่ม จึงต้องพิจารณาการจัดกลุ่มเพิ่ม")
            continue
        metric = chart.get("metric") if chart.get("metric") in measures or chart.get("metric") == "unique_student_count" else next((field for field in candidates if field in measures), "record_count")
        chart_type = chart.get("type", "bar").lower()
        if chart_type not in {"bar", "line", "pie"}:
            chart_type = "bar"
        formula = chart.get("formula") or ("COUNT(DISTINCT รหัสนักศึกษา)" if metric == "unique_student_count" else ("AVG(อัตราการจบตามวงรอบ) x 100" if "อัตรา" in metric else f"SUM({metric})"))
        target = chart.get("target") if isinstance(chart.get("target"), dict) else None
        plans.append({"id": f"chart-{index}", "title": chart.get("title", f"ภาพรวมตาม {dimension}"), "type": chart_type, "dimension": dimension, "metric": metric, "formula": formula, "target": target})
    if not plans:
        safe_dimension = next((field for field in dimensions if len({str(row.get(field)) for row in prepared if row.get(field) not in (None, "")}) <= 12), "_source_file")
        plans = [{"id": "chart-0", "title": f"จำนวนรายการตาม {safe_dimension}", "type": "bar", "dimension": safe_dimension, "metric": "record_count"}]
    requested_filters = [field for field in spec.get("filters", []) if field in dimensions]
    filter_fields = requested_filters or [field for field in dimensions if field.startswith("_") or len({str(row.get(field)) for row in prepared if row.get(field) not in (None, "")}) <= 20]
    label_overrides = spec.get("display_labels", {}) if isinstance(spec.get("display_labels"), dict) else {}
    filter_html = "".join(f'<label>{display_label(field, label_overrides)}<details class="multi"><summary id="filter-{index}-summary">ทั้งหมด</summary><div class="options" id="filter-{index}"></div></details></label>' for index, field in enumerate(filter_fields))
    chart_html = "".join(f'<article class="panel"><h2>{plan["title"]}</h2><div class="chart" id="{plan["id"]}"></div></article>' for plan in plans)
    warning_html = "".join(f"<li>{issue}</li>" for issue in issues) or "<li>ผ่านการตรวจความเหมาะสมของ field ก่อนสร้างกราฟ</li>"
    tracker_html = "".join(f"<li>{issue}</li>" for issue in issues) or "<li>ไม่พบประเด็นเชิงโครงสร้างจากการตรวจอัตโนมัติ</li>"
    template = '''<!doctype html><html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Prompt:wght@400;500;600;700&display=swap" rel="stylesheet"><title>__TITLE__</title><style>
:root{--navy:#0B2B5E;--blue:#263988;--gold:#FECD54;--bg:#F4F5F9;--line:#D9DEE8;--muted:#5f6b7c;--green:#0F8F83;--red:#C94A4A}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#1F2937;font-family:Prompt,"Noto Sans Thai",Tahoma,sans-serif}main{max-width:1440px;margin:auto;padding:20px clamp(16px,3vw,44px) 48px}header,.panel,.card{background:#fff;border:1px solid var(--line);border-radius:6px}header{display:grid;grid-template-columns:330px 1fr auto;gap:20px;align-items:center;border-top:4px solid var(--gold);padding:16px 22px}.identity{display:flex;align-items:center;gap:13px;color:var(--navy);font-weight:700}.identity img{width:72px;height:72px;object-fit:contain}.identity small,.title p{display:block;color:var(--muted);font-size:12px;font-weight:400}.title{text-align:center}.title p{margin:0}.title h1{margin:5px 0;color:var(--navy);font-family:Prompt,"Noto Serif Thai",serif;font-size:clamp(1.65rem,3vw,2.5rem)}.badge{border:1px solid var(--gold);padding:9px;font-size:12px;font-weight:700;color:var(--navy);white-space:nowrap}.filters,.kpis,.grid{display:grid;gap:14px;margin-top:18px}.filters{grid-template-columns:repeat(auto-fit,minmax(175px,1fr));align-items:end}label{display:grid;gap:6px;color:var(--navy);font-size:12px;font-weight:700}button,.multi{border:1px solid var(--line);background:#fff;border-radius:4px;padding:8px;color:#1F2937;font:inherit}.multi{position:relative;padding:0}.multi summary{padding:8px;cursor:pointer;list-style:none}.multi summary:after{content:'⌄';float:right}.options{position:absolute;z-index:3;top:calc(100% + 4px);left:0;right:0;max-height:220px;overflow:auto;background:#fff;border:1px solid var(--line);padding:6px;box-shadow:0 6px 16px #0b2b5e22}.options label{display:flex;align-items:center;gap:7px;padding:5px;color:#1F2937;font-weight:400}.options input{margin:0}button{min-height:38px;cursor:pointer}button:hover,.bar-label.active{border-color:var(--navy);background:#edf2fb}.kpis{grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}.card{border-top:3px solid var(--navy);padding:15px}.card span{font-size:12px;color:var(--muted);font-weight:700}.card strong{display:block;margin-top:7px;color:var(--navy);font-size:25px}.delta{margin-top:6px;font-size:12px;font-weight:700}.good{color:var(--green)}.bad{color:var(--red)}.neutral{color:var(--muted)}.grid{grid-template-columns:repeat(auto-fit,minmax(340px,1fr))}.panel{padding:18px}.panel h2{margin:0 0 12px;color:var(--navy);font:700 17px Prompt,"Noto Serif Thai",serif}.bar-row{display:grid;grid-template-columns:minmax(90px,1fr) 2fr auto;align-items:center;gap:9px;margin:9px 0;font-size:12px}.bar-label{text-align:left;border:0;padding:0;background:transparent;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.track{height:13px;background:#dce2ed}.bar{height:100%;background:var(--mark,var(--blue))}.line{display:flex;align-items:end;height:180px;gap:8px;border-bottom:1px solid var(--line)}.point{flex:1;min-width:18px;background:var(--mark,var(--blue));position:relative;border:0;padding:0}.point span{position:absolute;bottom:calc(100% + 4px);font-size:10px;transform:rotate(-35deg);transform-origin:left bottom;white-space:nowrap}.pie-wrap{display:flex;align-items:center;gap:18px}.pie{width:150px;height:150px;border-radius:50%;flex:none}.legend{font-size:12px;line-height:1.8}.notice{grid-column:1/-1;border-left:3px solid var(--gold);background:#fff9e8;padding:12px;color:#5d4d1d;font-size:13px}.notice ul{margin:5px 0 0;padding-left:20px}table{width:100%;border-collapse:collapse;font-size:12px}th,td{padding:8px;text-align:left;border-bottom:1px solid var(--line)}th{color:var(--navy)}.table{overflow:auto;max-height:340px}@media(max-width:860px){header{grid-template-columns:1fr}.title{text-align:left}.badge{width:max-content}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}</style></head><body><main><header><div class="identity"><img src="__LOGO__" alt="ตรามหาวิทยาลัยมหิดล"><div>คณะศิลปศาสตร์ มหาวิทยาลัยมหิดล<small>Faculty of Liberal Arts, Mahidol University</small></div></div><div class="title"><p>การวิเคราะห์ผลการดำเนินงาน</p><h1>__TITLE__</h1><p>__PURPOSE__</p></div><div class="badge">QA-AWARE DASHBOARD</div></header><section class="filters">__FILTERS__<button id="clear" type="button">ล้างตัวกรองทั้งหมด</button></section><section class="kpis" id="kpis"></section><section class="grid"><aside class="notice"><b>ข้อมูลที่ต้องพิจารณาเพิ่มเติม</b><ul>__ISSUES__</ul></aside>__CHARTS__<article class="panel"><h2>รายละเอียดข้อมูล</h2><div class="table"><table id="table"></table></div></article></section></main><script>
const rows=__ROWS__,plans=__PLANS__,fields=__FIELDS__,filterFields=__FILTER_FIELDS__,fmt=new Intl.NumberFormat('th-TH',{maximumFractionDigits:2});let chartFilter=null;
const esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');const numericValue=value=>{const match=String(value??'').replaceAll(',','').match(/-?\d+(?:\.\d+)?/);return match?Number(match[0]):0};function aggregate(data,metric){if(metric==='record_count')return data.length;if(metric==='unique_student_count')return new Set(data.map(row=>String(row['รหัสนักศึกษา']??'').trim()).filter(value=>value&&!/^[-\s]*$/.test(value))).size;const values=data.map(row=>numericValue(row[metric])).filter(value=>Number.isFinite(value));if(!values.length)return 0;if(/อัตรา|rate/i.test(metric)){const normalized=values.map(value=>value<=1?value*100:value);return normalized.reduce((sum,value)=>sum+value,0)/normalized.length}return values.reduce((sum,value)=>sum+value,0)}
filterFields.forEach((field,index)=>{const options=document.querySelector('#filter-'+index),summary=document.querySelector('#filter-'+index+'-summary');[...new Set(rows.map(row=>String(row[field]??'ไม่ระบุ'))) ].sort((a,b)=>a.localeCompare(b,'th',{numeric:true})).forEach((value,itemIndex)=>{const id=`f-${index}-${itemIndex}`;options.insertAdjacentHTML('beforeend',`<label for="${id}"><input id="${id}" type="checkbox" value="${esc(value)}">${esc(value)}</label>`)});options.addEventListener('change',()=>{const values=selectedValues(field,index);summary.textContent=values.size?`${values.size} รายการ`: 'ทั้งหมด';render()})});
function selectedValues(field,index){return new Set([...document.querySelectorAll('#filter-'+index+' input:checked')].map(input=>input.value))}function visible(){return rows.filter(row=>filterFields.every((field,index)=>{const picked=selectedValues(field,index);return !picked.size||picked.has(String(row[field]??'ไม่ระบุ'))})&&(!chartFilter||String(row[chartFilter.field]??'ไม่ระบุ')===chartFilter.value))}
function draw(plan,data){const buckets={};data.forEach(row=>{const key=String(row[plan.dimension]??'ไม่ระบุ');(buckets[key]??=[]).push(row)});const items=Object.entries(buckets).map(([label,group])=>[label,aggregate(group,plan.metric)]).sort((a,b)=>plan.type==='line'?a[0].localeCompare(b[0],'th',{numeric:true}):b[1]-a[1]).slice(0,12),max=Math.max(...items.map(item=>item[1]),1),total=items.reduce((sum,item)=>sum+item[1],0)||1,target=document.querySelector('#'+plan.id),colors=['#263988','#0F8F83','#FECD54','#C94A4A','#8094b8','#718c8e','#6B7280'],detail=`Field: ${plan.metric} | Group: ${plan.dimension} | Formula: ${plan.formula} | Source rows: ${data.length}`;if(plan.type==='pie'){let run=0;const parts=items.map(([label,value],index)=>{const start=run;run+=value/total*100;return `${colors[index%colors.length]} ${start}% ${run}%`});target.innerHTML=`<button class="calc" title="${esc(detail)}">วิธีคำนวณ</button><div class="pie-wrap"><div class="pie" style="background:conic-gradient(${parts.join(',')})"></div><div class="legend">${items.map(([label,value],index)=>`<div style="color:${colors[index%colors.length]}">■ <span style="color:#1F2937">${esc(label)}: ${fmt.format(value)} (${fmt.format(value/total*100)}%)</span></div>`).join('')}</div></div>`}else if(plan.type==='line'){target.innerHTML=`<button class="calc" title="${esc(detail)}">วิธีคำนวณ</button><div class="line">`+items.map(([label,value],index)=>`<button class="point" data-field="${esc(plan.dimension)}" data-value="${esc(label)}" style="--mark:${colors[index%colors.length]};height:${Math.max(value/max*100,3)}%" title="${esc(label)}: ${fmt.format(value)}"><span>${esc(label)} · ${fmt.format(value)}</span></button>`).join('')+'</div>'}else{target.innerHTML=`<button class="calc" title="${esc(detail)}">วิธีคำนวณ</button>`+items.map(([label,value],index)=>`<div class="bar-row"><button class="bar-label" data-field="${esc(plan.dimension)}" data-value="${esc(label)}" title="กรองตาม ${esc(label)}">${esc(label)}</button><div class="track"><div class="bar" style="--mark:${colors[index%colors.length]};width:${Math.max(value/max*100,2)}%"></div></div><b>${fmt.format(value)}</b></div>`).join('')||'<span class="neutral">ไม่พบข้อมูล</span>'}target.querySelectorAll('[data-field]').forEach(button=>button.onclick=()=>{chartFilter={field:button.dataset.field,value:button.dataset.value};render()})}
function render(){const data=visible(),metric=plans[0].metric,yearRows=data.filter(row=>row._year_be),year=Math.max(...yearRows.map(row=>Number(row._year_be)),0),current=aggregate(yearRows.filter(row=>Number(row._year_be)===year),metric),previous=aggregate(yearRows.filter(row=>Number(row._year_be)===year-1),metric),change=previous?((current-previous)/Math.abs(previous)*100):null;document.querySelector('#kpis').innerHTML=`<article class="card"><span>จำนวนนักศึกษาที่ระบุรหัส</span><strong>${fmt.format(aggregate(data,'unique_student_count'))}</strong><div class="delta neutral">COUNT(DISTINCT รหัสนักศึกษา)</div></article><article class="card"><span>จำนวนรายการ</span><strong>${fmt.format(data.length)}</strong><div class="delta neutral">${chartFilter?'กรองจากกราฟ: '+esc(chartFilter.value):'ข้อมูลตามตัวกรอง'}</div></article><article class="card"><span>อัตราจบเฉลี่ย</span><strong>${fmt.format(aggregate(data,'อัตราการจบตามวงรอบ'))}%</strong><div class="delta ${change===null?'neutral':change>=0?'good':'bad'}">${change===null?'ไม่มีฐานเปรียบเทียบ':`${change>=0?'▲':'▼'} ${fmt.format(Math.abs(change))}% เทียบปีก่อน`}</div></article>`;plans.forEach(plan=>draw(plan,data));document.querySelector('#table').innerHTML='<thead><tr>'+fields.map(field=>`<th>${esc(field)}</th>`).join('')+'</tr></thead><tbody>'+data.slice(0,100).map(row=>'<tr>'+fields.map(field=>`<td>${esc(row[field])}</td>`).join('')+'</tr>').join('')+'</tbody>'}document.querySelector('#clear').onclick=()=>{chartFilter=null;filterFields.forEach((field,index)=>{document.querySelectorAll('#filter-'+index+' input').forEach(input=>input.checked=false);document.querySelector('#filter-'+index+'-summary').textContent='ทั้งหมด'});render()};render();
</script></body></html>'''
    html = (template.replace("__TITLE__", str(spec.get("dashboard_title", name))).replace("__PURPOSE__", str(spec.get("purpose", ""))).replace("__LOGO__", f"/api/projects/{name}/dashboard/assets/logo.png").replace("__FILTERS__", filter_html).replace("__ISSUES__", warning_html).replace("__CHARTS__", chart_html).replace("__ROWS__", json.dumps(prepared, ensure_ascii=False, separators=(",", ":"))).replace("__PLANS__", json.dumps(plans, ensure_ascii=False)).replace("__FIELDS__", json.dumps(fields, ensure_ascii=False)).replace("__FILTER_FIELDS__", json.dumps(filter_fields, ensure_ascii=False)))
    enhancement = '''<style>
.chart{position:relative}.axis-label{color:#5f6b7c;font-size:11px;font-weight:600}.axis-y{margin:4px 0}.axis-x{text-align:center;margin-top:7px}.bar-scale{display:flex;justify-content:space-between;margin-left:32%;padding-top:4px;border-top:1px solid #b8c3d6;color:#5f6b7c;font-size:10px}.line{position:relative;align-items:end!important;background:repeating-linear-gradient(to top,transparent 0,transparent 24%,#d9dee8 24%,#d9dee8 25%);padding-bottom:26px}.target-line{position:absolute;left:0;right:0;border-top:2px dashed #C94A4A;pointer-events:none}.target-line span{position:absolute;right:0;bottom:3px;padding:1px 4px;background:#fff;color:#C94A4A;font-size:10px;font-weight:700}.target-marker{position:absolute;top:-3px;bottom:-3px;border-left:2px dashed #C94A4A;pointer-events:none}.target-marker span{position:absolute;top:-18px;left:-2px;white-space:nowrap;padding:1px 4px;background:#fff;color:#C94A4A;font-size:10px;font-weight:700}.point{overflow:visible!important}.point span{bottom:-24px!important;transform:none!important;left:50%;translate:-50% 0;max-width:54px;overflow:hidden;text-overflow:ellipsis;text-align:center}.point .point-value{position:absolute;bottom:calc(100% + 5px);left:50%;translate:-50% 0;color:#1F2937;font-size:10px;font-weight:700;white-space:nowrap}.calc{position:absolute;right:0;top:-38px;min-height:auto;padding:4px 7px;font-size:10px;color:#0B2B5E}.calc-detail{margin:0 0 10px;padding:8px 10px;background:#f4f5f9;border-left:3px solid #FECD54;color:#1F2937;font-size:11px;line-height:1.55}.review-tools{display:flex;justify-content:flex-end;margin:-4px 0 10px}.review-tools button{min-height:auto;padding:5px 8px;font-size:11px}.review-row{background:#fff8e8}.review-note{font-size:11px;color:#9a6700;font-weight:600}.tracker-panel{border-top:3px solid #FECD54}.tracker-panel ul{margin:0;padding-left:18px;font-size:12px;line-height:1.7}.tracker-panel p{font-size:12px;color:#5f6b7c}@media(min-width:1080px){.detail-panel{grid-column:span 2}.tracker-panel{grid-column:span 1}}@media(max-width:1079px){.detail-panel,.tracker-panel{grid-column:auto}}
</style><script>
(() => {
    let reviewOnly = false;
    const labels = __LABELS__;
    const plannedKpis = __KPIS__;
    const esc = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
    const problem = row => Object.entries(row).some(([field, value]) => !field.startsWith('_') && (value === null || value === '' || value === '-' || value === 'N/A' || value === '#VALUE!')) || !row._year_be || Number(String(row['จำนวนนักศึกษาในรุ่น'] ?? '').replace(/[^0-9.-]/g,'')) < 0;
    function decorate() {
        document.querySelectorAll('.chart').forEach(chart => {
            const plan = plans.find(item => item.id === chart.id);
            if (!plan) return;
            if (plan.type !== 'pie' && !chart.querySelector('.axis-y')) {
                const value = group => typeof aggregate === 'function' ? aggregate(group, plan.metric) : 0;
                const buckets = {};
                (typeof visible === 'function' ? visible() : rows).forEach(row => (buckets[String(row[plan.dimension] ?? 'ไม่ระบุ')] ??= []).push(row));
                const max = Math.max(...Object.values(buckets).map(value), 1);
                chart.insertAdjacentHTML('afterbegin', `<div class="axis-label axis-y">แกน Y: ${esc(labels[plan.dimension] || plan.dimension)}</div>`);
                chart.insertAdjacentHTML('beforeend', `<div class="bar-scale"><span>0</span><span>${fmt.format(max / 2)}</span><span>${fmt.format(max)}</span></div><div class="axis-label axis-x">แกน X: ${esc(labels[plan.metric] || plan.metric)}</div>`);
            }
            if (plan.type === 'line') chart.querySelectorAll('.point').forEach(point => {
                if (point.querySelector('.point-value')) return;
                const [label, value] = (point.title || '').split(': ');
                const text = point.querySelector('span');
                if (text) text.textContent = label || text.textContent;
                point.insertAdjacentHTML('afterbegin', `<b class="point-value">${esc(value || '')}</b>`);
            });
            if (plan.type === 'line' && plan.target && !chart.querySelector('.target-line')) {
                const values = rows.map(row => aggregate([row], plan.metric));
                const maximum = Math.max(...values, Number(plan.target.value), 1);
                const position = Math.min(Number(plan.target.value) / maximum * 100, 100);
                chart.querySelector('.line')?.insertAdjacentHTML('beforeend', `<div class="target-line" style="bottom:calc(26px + ${position}%)"><span>${esc(plan.target.label)}: ${fmt.format(plan.target.value)}</span></div>`);
            }
            if (plan.type === 'bar' && plan.target && !chart.querySelector('.target-marker')) {
                const rows = [...chart.querySelectorAll('.bar-row')];
                const values = rows.map(row => Number(row.querySelector('b')?.textContent.replaceAll(',', '')) || 0);
                const maximum = Math.max(...values, Number(plan.target.value), 1);
                const targetRow = rows.find(row => row.querySelector('.bar-label')?.dataset.value === String(plan.target.year_be));
                targetRow?.querySelector('.track')?.insertAdjacentHTML('beforeend', `<span class="target-marker" style="left:${Math.min(Number(plan.target.value) / maximum * 100, 100)}%"><span>${esc(plan.target.label)}: ${fmt.format(plan.target.value)}</span></span>`);
            }
            const calc = chart.querySelector('.calc');
            if (calc && calc.dataset.bound !== 'true') {
                calc.dataset.bound = 'true';
                calc.removeAttribute('title');
                calc.addEventListener('click', event => {
                    event.preventDefault();
                    const existing = chart.querySelector('.calc-detail');
                    if (existing) return existing.remove();
                    const shown = typeof visible === 'function' ? visible().length : rows.length;
                    chart.insertAdjacentHTML('afterbegin', `<div class="calc-detail"><b>วิธีคำนวณ</b><br>ข้อมูล: ${esc(labels[plan.metric] || plan.metric)} | จัดกลุ่ม: ${esc(labels[plan.dimension] || plan.dimension)}<br>สูตร: ${esc(plan.formula)}<br>แถวข้อมูลที่ใช้: ${shown} | ข้อจำกัด: ใช้เฉพาะข้อมูลตามตัวกรองปัจจุบัน</div>`);
                });
            }
        });
        const table = document.querySelector('#table');
        if (table && !document.querySelector('.review-tools')) {
            table.closest('.panel').classList.add('detail-panel');
            table.parentElement.insertAdjacentHTML('beforebegin', '<div class="review-tools"><button type="button" id="review-toggle">แสดงเฉพาะข้อมูลต้องตรวจสอบ</button></div>');
            document.querySelector('#review-toggle').addEventListener('click', () => { reviewOnly = !reviewOnly; applyReview(); });
        }
        const grid = document.querySelector('.grid');
        if (grid && !document.querySelector('.tracker-panel')) grid.insertAdjacentHTML('beforeend', '<article class="panel tracker-panel"><h2>ประเด็นที่ต้องติดตาม</h2><p>รายการที่ต้องตรวจสอบหรือยืนยันกับข้อมูลต้นทาง</p><ul>__TRACKER__</ul></article>');
        applyReview();
    }
    function applyReview() {
        const table = document.querySelector('#table');
        if (!table) return;
        const shown = typeof visible === 'function' ? visible() : rows;
        [...table.querySelectorAll('tbody tr')].forEach((row, index) => {
            const flagged = problem(shown[index] || {});
            row.classList.toggle('review-row', flagged);
            row.title = flagged ? 'ต้องตรวจสอบ: พบค่าว่าง/ค่าไม่ถูกต้อง/ค่าไม่ผ่านการจัดกลุ่ม' : '';
            row.style.display = reviewOnly && !flagged ? 'none' : '';
        });
        const button = document.querySelector('#review-toggle');
        if (button) button.textContent = reviewOnly ? 'แสดงข้อมูลทั้งหมด' : 'แสดงเฉพาะข้อมูลต้องตรวจสอบ';
    }
    document.addEventListener('click', event => {
        const mark = event.target.closest('[data-field]');
        if (!mark) return;
        event.stopImmediatePropagation();
        const next = {field: mark.dataset.field, value: mark.dataset.value};
        chartFilter = chartFilter && chartFilter.field === next.field && chartFilter.value === next.value ? null : next;
        render();
        queueMicrotask(decorate);
    }, true);
    document.addEventListener('change', () => queueMicrotask(decorate), true);
    document.addEventListener('click', event => {
        if (event.target.id === 'clear') queueMicrotask(decorate);
    }, true);
    const baseRender = render;
    render = function () {
        baseRender();
        plannedKpis.filter(item => item.comparison?.enabled).slice(0, 3).forEach((kpi, index) => {
            const card = document.querySelectorAll('#kpis .card')[index];
            if (!card) return;
            const yearly = rows.filter(row => row._year_be).map(row => Number(row._year_be));
            const latest = Math.max(...yearly, 0);
            const current = aggregate(rows.filter(row => Number(row._year_be) === latest), kpi.metric);
            const previous = aggregate(rows.filter(row => Number(row._year_be) === latest - 1), kpi.metric);
            const arrow = previous ? (current >= previous ? '▲' : '▼') : '—';
            card.querySelector('span').textContent = kpi.name;
            card.querySelector('strong').textContent = fmt.format(current);
            const delta = card.querySelector('.delta');
            if (delta) delta.textContent = previous ? `${arrow} ${fmt.format(Math.abs((current - previous) / previous * 100))}% เทียบปี ${latest - 1}` : 'ไม่มีฐานเปรียบเทียบ';
        });
        queueMicrotask(decorate);
    };
    render();
    decorate();
})();
</script>'''
    labels = {field: display_label(field, label_overrides) for field in set(fields) | {"_year_be", "_academic_year_be", "_month_th", "_quarter", "record_count", "unique_student_count"}}
    return html.replace("</body>", enhancement.replace("__LABELS__", json.dumps(labels, ensure_ascii=False)).replace("__KPIS__", json.dumps(spec.get("kpis", []), ensure_ascii=False)).replace("__TRACKER__", tracker_html) + "</body>")


def build_project(name: str) -> dict[str, Any]:
    directory = project_dir(name)
    profile = read_json(directory / "output/metadata/dataset-profile.json", None) or profile_project(name)
    config_path = directory / "config.json"
    config = read_json(config_path, default_config(name, profile))
    write_json(config_path, config)
    spec = read_json(directory / "output/metadata/dashboard-spec.local-ai.json", None) or suggest_spec(name)
    records, _ = load_sources(directory / "input")
    output = directory / "output"
    output.joinpath("data").mkdir(parents=True, exist_ok=True)
    write_json(output / "data/records.json", records)
    with (output / "data/records.csv").open("w", encoding="utf-8", newline="") as target:
        fields = sorted({key for row in records for key in row})
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader(); writer.writerows(records)
    output.joinpath("dashboard").mkdir(parents=True, exist_ok=True)
    assets = output / "dashboard/assets"
    assets.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "dashboard-automation/assets/logo.png", assets / "logo.png")
    (output / "dashboard/index.html").write_text(render_dashboard_qa(name, config, spec, profile, records), encoding="utf-8")
    missing = profile["quality"]["missing_values"]
    identifiers = [field["name"] for field in profile["fields"] if field.get("role") == "identifier"]
    date_issues = [f"{field}: parse ไม่ได้ {detail['unparsed']} ค่า" for field, detail in profile["quality"].get("date_parsing", {}).items() if detail["unparsed"]]
    checks = [{"name": "Input records", "status": "pass", "detail": f"{len(records)} records processed"}, {"name": "Identifier exclusion", "status": "pass", "detail": f"Excluded from metrics: {', '.join(identifiers) or 'None'}"}, {"name": "Duplicate rows", "status": "warning" if profile["quality"]["exact_duplicate_rows"] else "pass", "detail": str(profile["quality"]["exact_duplicate_rows"])}, {"name": "Missing values", "status": "warning" if any(missing.values()) else "pass", "detail": ", ".join(f"{key}: {value}" for key, value in missing.items() if value) or "None"}, {"name": "Date normalization", "status": "warning" if date_issues else "pass", "detail": ", ".join(date_issues) or "All recognized date values were normalized"}]
    qa = {"status": "warning" if any(check["status"] == "warning" for check in checks) else "pass", "checks": checks}
    write_json(output / "qa/qa-report.json", qa)
    (output / "reports").mkdir(parents=True, exist_ok=True)
    (output / "reports/data-quality-report.md").write_text("# Data Quality Report\n\n" + "\n".join(f"- {check['name']}: {check['detail']}" for check in checks) + "\n", encoding="utf-8")
    (output / "reports/insight-report.md").write_text("# Insight Questions\n\n" + "\n".join(f"- {item}" for item in spec.get("insight_questions", [])) + "\n", encoding="utf-8")
    write_json(output / "metadata/dashboard-spec.json", spec)
    write_json(output / "metadata/dashboard-requirements.json", {"audience": spec.get("audience"), "purpose": spec.get("purpose"), "questions": spec.get("insight_questions", []), "kpis": spec.get("kpis", []), "filters": spec.get("filters", [])})
    write_json(output / "metadata/run-manifest.json", {"project": name, "timestamp": datetime.now(timezone.utc).isoformat(), "stages": ["profile", "local-ai-spec", "build", "qa"], "status": qa["status"]})
    return {"qa": qa, "dashboard": f"/api/projects/{name}/dashboard", "records": len(records)}


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/projects")
def list_projects():
    result = []
    for directory in sorted(PROJECTS.iterdir()):
        if not directory.is_dir() or directory.name.startswith("_"):
            continue
        spec = read_json(directory / "output/metadata/dashboard-spec.local-ai.json", {})
        config = read_json(directory / "config.json", {})
        qa = read_json(directory / "output/qa/qa-report.json", {})
        result.append({"name": directory.name, "category": config.get("category", "Uncategorized"), "input_files": len(list((directory / "input").glob("*"))), "built": (directory / "output/dashboard/index.html").exists(), "title": spec.get("dashboard_title", directory.name), "qa_status": qa.get("status")})
    return jsonify(result)


@app.post("/api/projects")
def create_project():
    payload = request.get_json(force=True)
    name = payload.get("name", "")
    try:
        directory = project_dir(name)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if directory.exists():
        return jsonify({"error": "Project already exists."}), 409
    for folder in ("input", "output", "working"):
        (directory / folder).mkdir(parents=True, exist_ok=True)
    return jsonify({"name": name}), 201


@app.put("/api/projects/<name>/category")
def update_category(name: str):
    directory = project_dir(name)
    if not directory.exists():
        return jsonify({"error": "Project not found."}), 404
    category = str(request.get_json(force=True).get("category", "")).strip()
    if not category or len(category) > 60:
        return jsonify({"error": "Category must contain 1 to 60 characters."}), 400
    config_path = directory / "config.json"
    config = read_json(config_path, {"name": name})
    config["category"] = category
    write_json(config_path, config)
    return jsonify({"name": name, "category": category})


@app.get("/api/projects/<name>")
def project_details(name: str):
    directory = project_dir(name)
    if not directory.exists():
        return jsonify({"error": "Project not found."}), 404
    inputs = [{"name": item.name, "size": item.stat().st_size} for item in sorted((directory / "input").iterdir()) if item.is_file() and not item.name.startswith("~$")]
    return jsonify({
        "name": name,
        "inputs": inputs,
        "built": (directory / "output/dashboard/index.html").exists(),
        "profile": read_json(directory / "output/metadata/dataset-profile.json", None),
        "spec": read_json(directory / "output/metadata/dashboard-spec.local-ai.json", None),
        "qa": read_json(directory / "output/qa/qa-report.json", None),
    })


@app.post("/api/projects/<name>/uploads")
def upload_files(name: str):
    directory = project_dir(name)
    if not directory.exists():
        return jsonify({"error": "Project not found."}), 404
    files = request.files.getlist("files")
    saved = []
    for uploaded in files:
        filename = secure_filename(uploaded.filename or "")
        if not filename:
            continue
        if Path(filename).suffix.lower() not in ALLOWED_UPLOAD_SUFFIXES:
            return jsonify({"error": "Only .xlsx, .xlsm, and .csv files can be uploaded."}), 400
        uploaded.save(directory / "input" / filename)
        saved.append(filename)
    if not saved:
        return jsonify({"error": "Choose one or more files to upload."}), 400
    return jsonify({"files": saved}), 201


@app.post("/api/projects/<name>/profile")
def api_profile(name: str):
    try:
        profile = profile_project(name)
        config = default_config(name, profile)
        write_json(project_dir(name) / "config.json", config)
        return jsonify({"profile": profile, "config": config})
    except (ValueError, FileNotFoundError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/projects/<name>/suggest")
def api_suggest(name: str):
    try:
        payload = request.get_json(silent=True) or {}
        return jsonify(suggest_spec(name, payload.get("instruction", "")))
    except (ValueError, FileNotFoundError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/projects/<name>/improve")
def api_improve(name: str):
    try:
        return jsonify(improve_spec(name, request.get_json(force=True).get("instruction", "")))
    except (ValueError, FileNotFoundError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/projects/<name>/build")
def api_build(name: str):
    try:
        return jsonify(build_project(name))
    except (ValueError, FileNotFoundError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/projects/<name>/dashboard")
def dashboard(name: str):
    return send_from_directory(project_dir(name) / "output/dashboard", "index.html")


@app.get("/api/projects/<name>/dashboard/assets/<path:filename>")
def dashboard_assets(name: str, filename: str):
    return send_from_directory(project_dir(name) / "output/dashboard/assets", filename)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=True)