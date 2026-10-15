# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
from contextvars import copy_context
import hashlib
from html import escape
from io import BytesIO
import json
import os
import re
import shutil
import sys
import zipfile
from uuid import uuid4
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from threading import BoundedSemaphore, Lock, Thread
from typing import Any, Callable

from flask import Flask, jsonify, request, send_file, send_from_directory, g
from werkzeug.utils import secure_filename
from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"
LOCAL_AI = ROOT / "local-ai"
DASHBOARD_SKILL = ROOT / "dashboard-automation" / "SKILL.md"
DATA_RULES = ROOT / "rules" / "data-rules.md"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(LOCAL_AI))

from output_language import POLICY_VERSION, require_supported_text
from lan_service import CURRENT_OWNER, install_lan, model_identity

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
ALLOWED_UPLOAD_SUFFIXES = {".xlsx", ".xlsm", ".csv"}
AI_JOBS: dict[str, dict[str, Any]] = {}
AI_JOBS_LOCK = Lock()
install_lan(app, ROOT)
PROJECT_WRITE_LOCKS: dict[tuple, Lock] = {}
LAN_AI_SLOTS = BoundedSemaphore(8)


@app.before_request
def protect_lan_project_writes():
    if not app.config.get("FACTORY_LAN") or not CURRENT_OWNER.get() or request.method in {"GET", "HEAD", "OPTIONS"}:
        return None
    if request.is_json:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="JSON body must be an object"), 400
        if "instruction" in payload and (not isinstance(payload["instruction"], str) or len(payload["instruction"]) > 12000):
            return jsonify(error="Instruction must be text of at most 12000 characters"), 400
    name = (request.view_args or {}).get("name")
    if name:
        with AI_JOBS_LOCK:
            if any(job.get("owner") == CURRENT_OWNER.get() and job["project"] == name and job["status"] == "running" for job in AI_JOBS.values()):
                return jsonify(error="AI is working on this project. Wait before making changes."), 409
            lock = PROJECT_WRITE_LOCKS.setdefault((CURRENT_OWNER.get(), name), Lock())
        if not lock.acquire(blocking=False):
            return jsonify(error="This project is busy. Please retry."), 409
        g.project_write_lock = lock
    if request.endpoint in {"api_suggest", "api_improve", "api_build"}:
        if not LAN_AI_SLOTS.acquire(blocking=False):
            return jsonify(error="AI capacity is full. Please retry later."), 429
        g.lan_ai_slot = True


@app.teardown_request
def release_project_write_lock(_error):
    if getattr(g, "lan_ai_slot", False):
        LAN_AI_SLOTS.release()
        del g.lan_ai_slot
    lock = getattr(g, "project_write_lock", None)
    if lock is not None:
        lock.release()
        del g.project_write_lock


def projects_root() -> Path:
    owner = CURRENT_OWNER.get()
    if owner is None:
        if app.config.get("FACTORY_LAN"):
            raise ValueError("LAN project access requires authentication")
        return PROJECTS
    return Path(app.config["FACTORY_LAN_PROJECTS"]) / owner


def project_dir(name: str) -> Path:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        raise ValueError("Project name must use letters, digits, hyphens, or underscores.")
    return projects_root() / name


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
    "มกราคม": (1, "ม.ค."), "กุมภาพันธ์": (2, "ก.พ."), "มีนาคม": (3, "มี.ค."), "เมษายน": (4, "เม.ย."),
    "พฤษภาคม": (5, "พ.ค."), "มิถุนายน": (6, "มิ.ย."), "กรกฎาคม": (7, "ก.ค."), "สิงหาคม": (8, "ส.ค."),
    "กันยายน": (9, "ก.ย."), "ตุลาคม": (10, "ต.ค."), "พฤศจิกายน": (11, "พ.ย."), "ธันวาคม": (12, "ธ.ค."),
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
    if date_ratio >= .5 and not (numeric_ratio >= .8 and distinct_ratio >= .85):
        return "date"
    if re.search(r"id|หัส|code|เลขที่", label) or (numeric_ratio >= .8 and distinct_ratio >= .85):
        return "identifier"
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


def default_calculation_rules() -> dict[str, Any]:
    return {
        "current_academic_year_be": datetime.now().year + 543,
        "student_id": {
            "field": "",
            "entry_year_digits": 2,
            "entry_year_base_be": 2500,
            "program_years": 4,
            "maximum_study_years": 8,
        },
        "risk": {"gpa_field": "", "gpa_below": 2.0},
        "calculation_instruction": "",
        "metric_contracts": [],
    }


def default_config(name: str, profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "category": "Uncategorized",
        "language": "th",
        "timezone": "Asia/Bangkok",
        "dashboard_type": "auto",
        "audience": "ผู้บริหารและผู้ปฏิบัติงาน",
        "show_insights": True,
        "show_data_table": True,
        "responsive": True,
        "theme": "mahidol-faculty",
        "source_files": profile["input_files"],
        "calculation_rules": default_calculation_rules(),
    }


def project_config(name: str, profile: dict[str, Any]) -> dict[str, Any]:
    path = project_dir(name) / "config.json"
    defaults = default_config(name, profile)
    current = read_json(path, {})
    config = {**defaults, **current}
    config["source_files"] = profile["input_files"]
    config["calculation_rules"] = {**defaults["calculation_rules"], **(current.get("calculation_rules") or {})}
    config["calculation_rules"]["student_id"] = {**defaults["calculation_rules"]["student_id"], **(config["calculation_rules"].get("student_id") or {})}
    config["calculation_rules"]["risk"] = {**defaults["calculation_rules"]["risk"], **(config["calculation_rules"].get("risk") or {})}
    return config


def dashboard_requirement_template(profile: dict[str, Any], config: dict[str, Any]) -> str:
    """Create a short, metadata-grounded starting brief without calling an AI model."""
    fields = profile.get("fields", [])
    excluded = re.compile(r"(^|[_\s])(id|email|e-mail|name|surname|document|number|code)([_\s]|$)|รหัส|อีเมล|ชื่อ|นามสกุล|เลข", re.IGNORECASE)
    safe_categories = [
        str(field["name"])
        for field in fields
        if field.get("role") == "category"
        and 2 <= int(field.get("distinct") or 0) <= 50
        and not str(field.get("name", "")).startswith("column_")
        and not excluded.search(str(field.get("name", "")))
    ]
    measures = [str(field["name"]) for field in fields if field.get("role") == "measure"]
    dates = [str(field["name"]) for field in fields if field.get("role") == "date"]
    audience = str(config.get("audience") or "ผู้บริหารและผู้ปฏิบัติงาน")
    lines = [
        f"สร้าง Dashboard สรุปสำหรับ{audience} โดยใช้เฉพาะฟิลด์ที่มีอยู่ในชุดข้อมูลนี้",
        "ห้ามแสดงชื่อ นามสกุล อีเมล รหัส เลขเอกสาร หรือข้อมูลระบุตัวบุคคลใน KPI กราฟ ตัวกรอง และตารางรายละเอียด",
        "ให้มี KPI จำนวนรายการทั้งหมด",
    ]
    for measure in measures[:2]:
        lines.append(f"เพิ่ม KPI ผลรวม {measure} โดยรวมเฉพาะค่าตัวเลข และไม่นับค่า '-' หรือค่าว่าง")
    if dates:
        lines.append(f"เพิ่มกราฟแนวโน้มจำนวนรายการตาม {dates[0]} เฉพาะค่าที่แปลงวันที่ได้")
    for category in safe_categories[:3]:
        is_high_cardinality = any(field.get("name") == category and int(field.get("distinct") or 0) > 10 for field in fields)
        lines.append(f"เพิ่มกราฟแท่งเปรียบเทียบจำนวนรายการตาม {category}" + (" (แสดง 10 อันดับแรก)" if is_high_cardinality else ""))
    filters = ([dates[0]] if dates else []) + safe_categories[:5]
    if filters:
        lines.append("เพิ่มตัวกรอง " + ", ".join(filters))
    lines.extend([
        "ให้เลือกตารางรายละเอียดเฉพาะฟิลด์ที่ไม่ใช่ข้อมูลระบุตัวบุคคล และใช้สำหรับตรวจสอบรายการเท่านั้น",
        "ระบุข้อจำกัดของข้อมูล เช่น ค่าว่าง ค่า '-' และวันที่หรือค่าตัวเลขที่แปลงไม่ได้ต้องไม่ถูกรวมในการคำนวณ",
    ])
    if config.get("language") == "th":
        lines.append("ใช้ป้ายกำกับภาษาไทย และแสดงปี พ.ศ. เมื่อฟิลด์วันที่รองรับ")
    return "\n".join(lines)


def validate_calculation_rules(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Calculation rules must be an object.")
    defaults = default_calculation_rules()
    rules = {**defaults, **value}
    rules["student_id"] = {**defaults["student_id"], **(value.get("student_id") or {})}
    rules["risk"] = {**defaults["risk"], **(value.get("risk") or {})}
    year = rules.get("current_academic_year_be")
    if not isinstance(year, int) or not 2400 <= year <= 2700:
        raise ValueError("Current academic year must be a Buddhist Era year between 2400 and 2700.")
    student = rules["student_id"]
    if not isinstance(student.get("field"), str) or not isinstance(student.get("entry_year_digits"), int) or student["entry_year_digits"] not in {2, 4}:
        raise ValueError("Student ID rule must specify a field and two or four entry-year digits.")
    for key in ("entry_year_base_be", "program_years", "maximum_study_years"):
        if not isinstance(student.get(key), int) or student[key] < 1:
            raise ValueError(f"Student ID rule {key} must be a positive integer.")
    risk = rules["risk"]
    if not isinstance(risk.get("gpa_field"), str) or not isinstance(risk.get("gpa_below"), (int, float)) or not 0 <= float(risk["gpa_below"]) <= 4:
        raise ValueError("Risk rule must contain a GPA field and threshold from 0 to 4.")
    if not isinstance(rules.get("calculation_instruction"), str) or len(rules["calculation_instruction"]) > 5000:
        raise ValueError("Calculation instruction must be text with at most 5000 characters.")
    contracts = rules.get("metric_contracts")
    if not isinstance(contracts, list) or len(contracts) > 30:
        raise ValueError("Metric contracts must be a list containing at most 30 items.")
    contract_ids: set[str] = set()
    validated_contracts = []
    required_fields = {
        "completion_rate": ("numerator_field", "denominator_field"),
        "profit": ("revenue_field", "expense_field"),
        "ratio": ("numerator_field", "denominator_field"),
        "category_share": ("category_field", "category_value"),
    }
    for contract in contracts:
        if not isinstance(contract, dict):
            raise ValueError("Each metric contract must be an object.")
        contract_id = str(contract.get("id", "")).strip()
        contract_type = str(contract.get("type", "")).strip()
        status = str(contract.get("status", "draft")).strip()
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", contract_id) or contract_id in contract_ids:
            raise ValueError("Each metric contract needs a unique lowercase id.")
        if contract_type not in required_fields or status not in {"draft", "approved"}:
            raise ValueError("Metric contract type or status is invalid.")
        if not isinstance(contract.get("name"), str) or not contract["name"].strip() or len(contract["name"]) > 120:
            raise ValueError("Each metric contract needs a name up to 120 characters.")
        for field in required_fields[contract_type]:
            if not isinstance(contract.get(field), str) or not contract[field].strip() or len(contract[field]) > 160:
                raise ValueError(f"Metric contract {contract_id} needs {field}.")
        scale = contract.get("scale", 100)
        if not isinstance(scale, (int, float)) or not 0 < float(scale) <= 100000:
            raise ValueError("Metric contract scale must be greater than zero.")
        version = contract.get("version", 1)
        if not isinstance(version, int) or version < 1:
            raise ValueError("Metric contract version must be a positive integer.")
        validated_contracts.append({
            **contract,
            "id": contract_id,
            "type": contract_type,
            "name": contract["name"].strip(),
            "status": status,
            "scale": float(scale),
            "version": version,
        })
        contract_ids.add(contract_id)
    rules["metric_contracts"] = validated_contracts
    return rules


METRIC_CONTRACT_TEMPLATES = [
    {"id": "education-completion-rate", "name": "อัตราสำเร็จการศึกษา", "type": "completion_rate", "description": "ผลรวมตัวตั้ง ÷ ผลรวมตัวหาร × 100", "fields": ["numerator_field", "denominator_field"]},
    {"id": "finance-profit", "name": "กำไร", "type": "profit", "description": "ผลรวมรายรับ - ผลรวมค่าใช้จ่าย", "fields": ["revenue_field", "expense_field"]},
    {"id": "general-ratio", "name": "อัตราส่วน", "type": "ratio", "description": "ผลรวมตัวตั้ง ÷ ผลรวมตัวหาร × scale", "fields": ["numerator_field", "denominator_field"]},
    {"id": "general-category-share", "name": "สัดส่วนหมวดหมู่", "type": "category_share", "description": "จำนวนรายการในค่าหมวดหมู่ ÷ จำนวนรายการทั้งหมด × 100", "fields": ["category_field", "category_value"]},
]


def approved_metric_contracts(rules: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in rules.get("metric_contracts", []) if item.get("status") == "approved"}


def validate_metric_contract_fields(rules: dict[str, Any], profile: dict[str, Any]) -> None:
    available = {field["name"] for field in profile.get("fields", [])}
    fields_by_type = {
        "completion_rate": ("numerator_field", "denominator_field"),
        "profit": ("revenue_field", "expense_field"),
        "ratio": ("numerator_field", "denominator_field"),
        "category_share": ("category_field",),
    }
    for contract in rules["metric_contracts"]:
        missing = [field for field in fields_by_type[contract["type"]] if contract[field] not in available]
        if missing:
            raise ValueError(f"Metric contract {contract['id']} refers to unavailable field(s): {', '.join(missing)}.")


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


def grounded_spec_errors(spec: dict[str, Any], profile: dict[str, Any], rules: dict[str, Any] | None = None) -> list[str]:
    """Reject a plan that cannot be rendered from the profiled dataset."""
    fields = {field["name"] for field in profile["fields"]}
    allowed_dimensions = fields | {"_year_be", "_academic_year_be", "_month_th", "_quarter", "_source_file"}
    allowed_metrics = fields | {"record_count", "unique_student_count"} | {f"contract:{contract_id}" for contract_id in approved_metric_contracts(rules or default_calculation_rules())}
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


def semantic_profile_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["field_interpretations", "dataset_summary", "warnings"],
        "properties": {
            "dataset_summary": {"type": "string"},
            "warnings": {"type": "array", "items": {"type": "string"}},
            "field_interpretations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["field", "semantic_type", "unit", "aggregation_guidance", "business_role", "confidence", "limitations"],
                    "properties": {
                        "field": {"type": "string"},
                        "semantic_type": {"type": "string", "enum": ["identifier", "date", "currency", "count", "percentage", "rate", "quantity", "category", "text", "unknown"]},
                        "unit": {"type": "string"},
                        "aggregation_guidance": {"type": "string", "enum": ["do_not_aggregate", "count_distinct", "sum_when_additive", "average_when_comparable", "group_only", "unknown"]},
                        "business_role": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "limitations": {"type": "string"},
                    },
                },
            },
        },
    }


def semantic_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Use AI to interpret profiled fields without exposing source rows or examples."""
    from ai_client import generate_json, provider_name

    safe_profile = cloud_safe_profile(profile)
    available_fields = {field["name"] for field in safe_profile["fields"]}
    result = generate_json(
        "You are a careful data governance analyst. Interpret field meaning only from the supplied metadata. "
        "Do not invent business facts, relationships, formulas, or values. Treat every conclusion as a suggestion, "
        "not a calculation. Identify aggregation risks, especially repeated totals and percentages.",
        "Create a semantic profile for this dataset. Use only exact field names from the metadata. "
        "For each included field, state its likely semantic type, unit when evident, aggregation guidance, business role, "
        "confidence, and limitations. Omit fields whose meaning cannot be inferred safely.\n\n"
        f"METADATA ONLY:\n{json.dumps(safe_profile, ensure_ascii=False)}",
        semantic_profile_schema(),
    )
    interpretations = [
        item for item in result.get("field_interpretations", [])
        if isinstance(item, dict) and item.get("field") in available_fields
    ]
    return {
        "generated_by": f"{provider_name()}-ai",
        "source": "metadata_only",
        "profile_generated_at": profile.get("generated_at"),
        "dataset_summary": str(result.get("dataset_summary", "")),
        "warnings": [str(item) for item in result.get("warnings", [])],
        "field_interpretations": interpretations,
    }


def get_semantic_profile(name: str, profile: dict[str, Any]) -> dict[str, Any]:
    path = project_dir(name) / "output/metadata/semantic-profile.local-ai.json"
    current = read_json(path, None)
    if isinstance(current, dict) and current.get("profile_generated_at") == profile.get("generated_at"):
        return current
    result = semantic_profile(profile)
    write_json(path, result)
    return result


def normalization_context(profile: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    pii_name = re.compile(r"name|surname|email|phone|address|ชื่อ|นามสกุล|อีเมล|โทร|ที่อยู่", re.IGNORECASE)
    fields = []
    for field in profile["fields"]:
        name, role = field["name"], field.get("role")
        if role not in {"category", "date"} or pii_name.search(name) or field.get("distinct", 0) > 80:
            continue
        counts = Counter(str(record.get(name)).strip() for record in records if record.get(name) not in (None, ""))
        if not counts:
            continue
        fields.append({"field": name, "role": role, "values": [{"value": value, "count": count} for value, count in counts.most_common(50)]})
    return {"profile_generated_at": profile.get("generated_at"), "fields": fields, "requirement": "Map equivalent category values only. All date output must use Buddhist Era years."}


def normalization_plan_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["mappings", "warnings"],
        "properties": {
            "warnings": {"type": "array", "items": {"type": "string"}},
            "mappings": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["field", "source", "target", "reason", "confidence"], "properties": {"field": {"type": "string"}, "source": {"type": "string"}, "target": {"type": "string"}, "reason": {"type": "string"}, "confidence": {"type": "number", "minimum": 0, "maximum": 1}}}},
        },
    }


def get_normalization_plan(name: str, profile: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    path = project_dir(name) / "output/metadata/normalization-plan.ai.json"
    current = read_json(path, None)
    if isinstance(current, dict) and current.get("profile_generated_at") == profile.get("generated_at"):
        return current
    from ai_client import generate_json, provider_name

    context = normalization_context(profile, records)
    result = generate_json(
        "You are a cautious data-normalization analyst. Propose only exact-value category mappings that are clearly equivalent. "
        "Never map distinct business categories together. Do not infer or alter identifiers, names, free text, or numeric measures. "
        "For date fields, identify ambiguity in warnings; Python will normalize valid dates to Buddhist Era dimensions.",
        f"NORMALIZATION CANDIDATES:\n{json.dumps(context, ensure_ascii=False)}",
        normalization_plan_schema(),
    )
    allowed = {item["field"]: {value["value"] for value in item["values"]} for item in context["fields"]}
    mappings = [
        {key: item[key] for key in ("field", "source", "target", "reason", "confidence")}
        for item in result.get("mappings", [])
        if isinstance(item, dict) and item.get("field") in allowed and item.get("source") in allowed[item["field"]] and isinstance(item.get("target"), str) and item["target"].strip() and float(item.get("confidence", 0)) >= 0.75
    ]
    plan = {"generated_by": f"{provider_name()}-ai", "profile_generated_at": profile.get("generated_at"), "mappings": mappings, "warnings": [str(item) for item in result.get("warnings", [])]}
    write_json(path, plan)
    return plan


def planner_workflow_contract(compact: bool = False) -> str:
    """Return the enforceable workflow contract; compact form protects Groq TPM budget."""
    if compact:
        return """PLANNER EXECUTION CONTRACT
Create a grounded dashboard plan only. Raw input is read-only and Python calculates every number locally.
Use exact supplied field names only. Never invent fields, values, relationships, or formulas. Never use identifiers or near-unique values as a sum, axis, filter, or KPI. Use COUNT(DISTINCT stable ID) for entities.
SUM only additive row-grain measures. Average comparable rates after normalizing them to 0-100; never sum rates. Ratios need a stated non-zero denominator. Use normalized BE date dimensions when available.
Each KPI/chart requires exact source fields, aggregation/formula, an appropriate dimension, and limitations. Prefer low-cardinality filters and readable groupings. State unsupported requirements as limitations. The local build independently validates calculations and rejects mismatches."""
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
    from ai_client import generate_json
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


def local_ai_spec(profile: dict[str, Any], rules: dict[str, Any], instruction: str, current_spec: dict[str, Any] | None = None, semantic: dict[str, Any] | None = None, calculation_results: list[dict[str, Any]] | None = None, normalization_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ask the configured AI provider to create and repair a grounded dashboard plan."""
    from ai_client import generate_json, provider_name
    schema = grounded_schema(profile)
    guidance = (LOCAL_AI / "prompts/dashboard-spec.md").read_text(encoding="utf-8")
    provider = provider_name()
    workflow = planner_workflow_contract(compact=provider == "groq")
    request_text = instruction or "Propose the most useful management dashboard supported by this dataset."
    available_fields = sorted(field["name"] for field in profile["fields"])
    contract_metrics = [f"contract:{contract_id}" for contract_id in approved_metric_contracts(rules)]
    allowed_references = available_fields + ["record_count", "unique_student_count", "_year_be", "_academic_year_be", "_month_th", "_quarter"] + contract_metrics
    prompt = (
        f"{workflow}\n\n{guidance}\n\nUSER REQUEST:\n{request_text}\n\n"
        "DATA PROFILE (metadata only; field names must be copied exactly):\n"
        f"{json.dumps(cloud_safe_profile(profile), ensure_ascii=False)}\n\n"
        "SEMANTIC PROFILE (metadata-only suggestions; do not treat as facts or use it to invent fields, values, or formulas):\n"
        f"{json.dumps(semantic or {}, ensure_ascii=False)}\n\n"
        "NORMALIZATION PLAN (validated category mappings that the local build applies; use canonical target values in filters and describe ambiguities as limitations):\n"
        f"{json.dumps(normalization_plan or {}, ensure_ascii=False)}\n\n"
        "LOCAL CALCULATION TOOL RESULTS (computed by Python from the actual project data; use these values as evidence, but only use fields from the allowlist):\n"
        f"{json.dumps(calculation_results or [], ensure_ascii=False)}\n\n"
        "APPROVED METRIC CONTRACTS (optional deterministic metrics; use contract:<id> exactly as the metric and preserve the listed formula):\n"
        f"{json.dumps(list(approved_metric_contracts(rules).values()), ensure_ascii=False)}\n\n"
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
    errors = grounded_spec_errors(spec, profile, rules)
    if errors:
        repair_prompt = (
            f"{prompt}\n\nYOUR PREVIOUS SPECIFICATION FAILED VALIDATION:\n- "
            + "\n- ".join(errors)
            + "\nReplace every invalid alias with the semantically matching exact value from ALLOWED FIELD REFERENCES. "
            "Return a complete corrected JSON specification."
        )
        repaired = generate_json("You repair dashboard plans using only exact available fields. Return only grounded JSON.", repair_prompt, schema)
        errors = grounded_spec_errors(repaired, profile, rules)
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
    errors = grounded_spec_errors(covered_spec, profile, rules)
    if errors:
        raise ValueError("Local AI produced an unsupported dashboard plan after requirement review: " + " ".join(errors))
    missing = requested_capability_errors(instruction, covered_spec)
    if missing:
        raise ValueError("Local AI plan does not yet cover the requested dashboard: " + " ".join(missing))
    return covered_spec


def suggest_spec(name: str, instruction: str = "", progress: Callable[[int, str], None] | None = None) -> dict[str, Any]:
    from ai_client import provider_name

    directory = project_dir(name)
    profile = read_json(directory / "output/metadata/dataset-profile.json", None)
    if not profile:
        profile = profile_project(name)
    def update(percent: int, stage: str) -> None:
        if progress:
            progress(percent, stage)

    try:
        update(5, "กำลังตรวจ Data Profile และกฎการคำนวณ")
        config = project_config(name, profile)
        rules = validate_calculation_rules(config["calculation_rules"])
        records, _ = load_sources(directory / "input")
        update(15, "AI กำลังวิเคราะห์ semantic, normalization และผลคำนวณที่ต้องตรวจสอบ")
        planning_instruction = f"{instruction.strip()}\n\nPROJECT CALCULATION RULES:\n{rules['calculation_instruction']}".strip()
        semantic, normalization_plan, calculation_requests = get_ai_analysis_bundle(name, profile, records, planning_instruction)
        update(55, "กำลังเตรียมข้อมูลวิเคราะห์ในเครื่อง")
        prepared, _ = prepare_analytical_records(records, profile, rules, normalization_plan)
        update(70, "กำลังคำนวณผลที่ AI ร้องขอในเครื่อง")
        calculations = []
        for calculation_request in calculation_requests:
            try:
                calculations.append(execute_calculation_tool(prepared, calculation_request, profile, rules))
            except ValueError:
                continue
        write_json(directory / "output/metadata/ai-tool-results.json", {"instruction": instruction.strip(), "requests": calculation_requests, "results": calculations})
        update(85, "AI กำลังออกแบบ KPI, filters และ charts")
        spec = local_ai_spec(profile, rules, planning_instruction, semantic=semantic, calculation_results=calculations, normalization_plan=normalization_plan)
        source = f"{provider_name()}-ai"
    except Exception as exc:
        raise ValueError(f"Configured AI provider could not create the specification: {exc}") from exc
    spec["generated_by"] = source
    if instruction.strip():
        spec["last_instruction"] = instruction.strip()
    write_json(directory / "output/metadata/dashboard-spec.local-ai.json", spec)
    update(100, "สร้าง specification สำเร็จ")
    return spec


def improve_spec(name: str, instruction: str) -> dict[str, Any]:
    from ai_client import provider_name

    directory = project_dir(name)
    profile = read_json(directory / "output/metadata/dataset-profile.json", None)
    current_spec = read_json(directory / "output/metadata/dashboard-spec.local-ai.json", None)
    if not profile or not current_spec:
        raise ValueError("Create a data profile and Local AI specification before requesting an improvement.")
    instruction = instruction.strip()
    if not instruction:
        raise ValueError("Enter an improvement request.")
    try:
        config = project_config(name, profile)
        rules = validate_calculation_rules(config["calculation_rules"])
        records, _ = load_sources(directory / "input")
        planning_instruction = f"{instruction}\n\nPROJECT CALCULATION RULES:\n{rules['calculation_instruction']}".strip()
        semantic, normalization_plan, calculation_requests = get_ai_analysis_bundle(name, profile, records, planning_instruction)
        prepared, _ = prepare_analytical_records(records, profile, rules, normalization_plan)
        calculations = []
        for calculation_request in calculation_requests:
            try:
                calculations.append(execute_calculation_tool(prepared, calculation_request, profile, rules))
            except ValueError:
                continue
        write_json(directory / "output/metadata/ai-tool-results.json", {"instruction": instruction, "requests": calculation_requests, "results": calculations})
        spec = local_ai_spec(profile, rules, planning_instruction, current_spec, semantic, calculations, normalization_plan)
    except Exception as exc:
        raise ValueError(f"Configured AI provider could not revise the specification: {exc}") from exc
    revisions = directory / "output/metadata/spec-revisions"
    revisions.mkdir(parents=True, exist_ok=True)
    revision = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_json(revisions / f"{revision}-before.json", current_spec)
    write_json(revisions / f"{revision}-request.json", {"instruction": instruction, "timestamp": datetime.now(timezone.utc).isoformat()})
    spec["generated_by"] = f"{provider_name()}-ai"
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


def normalize_category(field: str, value: Any) -> tuple[Any, str | None]:
    if not isinstance(value, str):
        return value, None
    compact = re.sub(r"\s+", " ", value).strip()
    key = compact.lower().replace(" ", "")
    label = field.lower()
    if re.search(r"gender|เพศ", label):
        if key in {"ชาย", "ช", "male", "m"}:
            return "ชาย", None if compact == "ชาย" else "รวมค่ารูปแบบเพศเป็น 'ชาย'"
        if key in {"หญิง", "ญ", "female", "f"}:
            return "หญิง", None if compact == "หญิง" else "รวมค่ารูปแบบเพศเป็น 'หญิง'"
    if re.search(r"status|สถานะ", label):
        if key in {"ลาออก", "withdraw", "withdrawn", "dropout"}:
            return "ลาออก", None if compact == "ลาออก" else "รวมค่ารูปแบบสถานะเป็น 'ลาออก'"
        if key in {"กำลังศึกษา", "กำลังเรียน", "studying", "active"}:
            return "กำลังศึกษา", None if compact == "กำลังศึกษา" else "รวมค่ารูปแบบสถานะเป็น 'กำลังศึกษา'"
        if key in {"จบการศึกษา", "สำเร็จการศึกษา", "graduated", "complete"}:
            return "สำเร็จการศึกษา", None if compact == "สำเร็จการศึกษา" else "รวมค่ารูปแบบสถานะเป็น 'สำเร็จการศึกษา'"
    return compact, "ตัดช่องว่างหรือจัดรูปแบบข้อความ" if compact != value else None


def prepare_analytical_records(records: list[dict[str, Any]], profile: dict[str, Any], rules: dict[str, Any], normalization_plan: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    date_fields = [field["name"] for field in profile["fields"] if field.get("role") == "date"]
    parse_counts = profile["quality"].get("date_parsing", {})
    primary_date = max(date_fields, key=lambda field: ("เดือน" in field or "วัน" in field or "date" in field.lower(), parse_counts.get(field, {}).get("parsed", 0)), default=None)
    prepared = []
    notices: Counter[str] = Counter()
    mappings = {(item["field"], item["source"].strip()): item for item in (normalization_plan or {}).get("mappings", []) if isinstance(item, dict) and all(key in item for key in ("field", "source", "target", "reason"))}
    for record in records:
        item = dict(record)
        for field, value in list(item.items()):
            if field.startswith("_"):
                continue
            mapping = mappings.get((field, str(value).strip()))
            if mapping:
                item[field] = mapping["target"].strip()
                notices[f"{field}: {mapping['source']} -> {mapping['target']} ({mapping['reason']})"] += 1
            normalized, notice = normalize_category(field, item[field] if mapping else value)
            item[field] = item[field] if mapping else normalized
            if notice:
                notices[f"{field}: {notice}"] += 1
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
        student_rule = rules["student_id"]
        student_field = student_rule["field"]
        if student_field and item.get(student_field) not in (None, ""):
            match = re.search(rf"(?:[A-Za-z]+)?\s*(\d{{{student_rule['entry_year_digits']}}})\d+", str(item[student_field]))
            if match:
                entry_year = student_rule["entry_year_base_be"] + int(match.group(1)) if student_rule["entry_year_digits"] == 2 else int(match.group(1))
                study_year = rules["current_academic_year_be"] - entry_year + 1
                if 1 <= study_year <= student_rule["maximum_study_years"]:
                    item["_student_entry_year_be"] = entry_year
                    item["_student_year"] = study_year
                else:
                    notices[f"{student_field}: ไม่สามารถระบุชั้นปีจากรหัสนักศึกษาได้"] += 1
        risk_rule = rules["risk"]
        if risk_rule["gpa_field"] and numeric(item.get(risk_rule["gpa_field"])) is not None:
            item["_academic_risk"] = "เสี่ยง" if numeric(item[risk_rule["gpa_field"]]) < float(risk_rule["gpa_below"]) else "ปกติ"
        prepared.append(item)
    notices.update({f"AI normalization warning: {warning}": 0 for warning in (normalization_plan or {}).get("warnings", [])})
    return prepared, [{"notice": text, "affected_records": count} for text, count in notices.most_common()]


def analytical_records(records: list[dict[str, Any]], profile: dict[str, Any], rules: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return prepare_analytical_records(records, profile, validate_calculation_rules(rules or default_calculation_rules()))[0]


def aggregate_rows(records: list[dict[str, Any]], metric: str, aggregation: str, rules: dict[str, Any]) -> float | int:
    if metric.startswith("contract:"):
        contract = approved_metric_contracts(rules).get(metric.removeprefix("contract:"))
        if not contract:
            raise ValueError("Metric contract is not approved.")
        if contract["type"] == "profit":
            revenue = aggregate_rows(records, contract["revenue_field"], "sum", rules)
            expense = aggregate_rows(records, contract["expense_field"], "sum", rules)
            return revenue - expense
        if contract["type"] == "category_share":
            if not records:
                return 0
            matches = sum(str(record.get(contract["category_field"], "")).strip() == contract["category_value"] for record in records)
            return matches / len(records) * contract["scale"]
        numerator = aggregate_rows(records, contract["numerator_field"], "sum", rules)
        denominator = aggregate_rows(records, contract["denominator_field"], "sum", rules)
        return numerator / denominator * contract["scale"] if denominator else 0
    if metric == "record_count":
        return len(records)
    if metric == "unique_student_count":
        field = rules["student_id"]["field"]
        return len({str(record.get(field, "")).strip() for record in records if field and str(record.get(field, "")).strip()})
    values = [numeric(record.get(metric)) for record in records]
    numbers = [value for value in values if value is not None]
    if aggregation == "count":
        return len(numbers)
    if not numbers:
        return 0
    if aggregation == "average":
        return sum(numbers) / len(numbers)
    if aggregation == "minimum":
        return min(numbers)
    if aggregation == "maximum":
        return max(numbers)
    return sum(numbers)


def apply_tool_filters(records: list[dict[str, Any]], filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered = records
    for item in filters:
        if not isinstance(item, dict):
            continue
        field, value = item.get("field"), item.get("equals")
        if isinstance(field, str) and isinstance(value, str):
            filtered = [record for record in filtered if str(record.get(field, "")).strip() == value]
    return filtered


def execute_calculation_tool(records: list[dict[str, Any]], request_item: dict[str, Any], profile: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    derived_fields = {"_year_be", "_academic_year_be", "_month_th", "_quarter", "_student_entry_year_be", "_student_year", "_academic_risk"}
    contract_metrics = {f"contract:{contract_id}" for contract_id in approved_metric_contracts(rules)}
    available = {field["name"] for field in profile["fields"]} | derived_fields | {"record_count", "unique_student_count"} | contract_metrics
    metric = str(request_item.get("metric", "record_count"))
    aggregation = str(request_item.get("aggregation", "count"))
    dimension = request_item.get("dimension")
    if metric not in available or aggregation not in {"count", "distinct", "sum", "average", "minimum", "maximum", "contract"}:
        raise ValueError("Calculation tool request contains an unsupported metric or aggregation.")
    if dimension is not None and dimension not in available:
        raise ValueError("Calculation tool request contains an unsupported dimension.")
    selected = apply_tool_filters(records, request_item.get("filters", []))
    normalized_aggregation = "count" if aggregation == "distinct" and metric == "record_count" else aggregation
    if metric.startswith("contract:"):
        normalized_aggregation = "contract"
    if aggregation == "distinct":
        value = len({str(record.get(metric, "")).strip() for record in selected if str(record.get(metric, "")).strip()})
    elif dimension:
        groups: dict[str, list[dict[str, Any]]] = {}
        for record in selected:
            groups.setdefault(str(record.get(dimension, "ไม่ระบุ")), []).append(record)
        value = [
            {"label": label, "value": aggregate_rows(group, metric, normalized_aggregation, rules), "rows": len(group)}
            for label, group in sorted(groups.items(), key=lambda entry: str(entry[0]))[:50]
        ]
    else:
        value = aggregate_rows(selected, metric, normalized_aggregation, rules)
    return {
        "name": str(request_item.get("name") or f"{aggregation} {metric}"),
        "metric": metric,
        "aggregation": aggregation,
        "dimension": dimension,
        "filters": request_item.get("filters", []),
        "rows": len(selected),
        "value": value,
    }


def analysis_request_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["requests"],
        "properties": {
            "requests": {
                "type": "array",
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "metric", "aggregation", "dimension", "filters"],
                    "properties": {
                        "name": {"type": "string"},
                        "metric": {"type": "string"},
                        "aggregation": {"type": "string", "enum": ["count", "distinct", "sum", "average", "minimum", "maximum"]},
                        "dimension": {"type": ["string", "null"]},
                        "filters": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["field", "equals"], "properties": {"field": {"type": "string"}, "equals": {"type": "string"}}}},
                    },
                },
            },
        },
    }


def request_local_calculations(profile: dict[str, Any], semantic: dict[str, Any], instruction: str, records: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    """Let the configured AI select bounded aggregate tools, then execute locally."""
    from ai_client import generate_json

    allowed = sorted({field["name"] for field in profile["fields"]} | {"record_count", "unique_student_count"})
    plan = generate_json(
        "You are a dashboard analyst. Choose up to ten local aggregate calculations that will verify the user's request. "
        "You may only request the supplied fields and fixed aggregation types. Never request raw records, examples, SQL, formulas, or unbounded filters.",
        f"USER REQUEST:\n{instruction or 'Create a useful management dashboard.'}\n\n"
        f"AVAILABLE FIELDS:\n{json.dumps(allowed, ensure_ascii=False)}\n\n"
        f"SEMANTIC PROFILE:\n{json.dumps(semantic, ensure_ascii=False)}",
        analysis_request_schema(),
    )
    results = []
    for item in plan.get("requests", []):
        try:
            results.append(execute_calculation_tool(records, item, profile, rules))
        except ValueError:
            continue
    return results


def analysis_bundle_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["semantic", "normalization", "calculations"],
        "properties": {
            "semantic": semantic_profile_schema(),
            "normalization": normalization_plan_schema(),
            "calculations": analysis_request_schema(),
        },
    }


def analysis_bundle_cache_key(profile: dict[str, Any], instruction: str, provider: str) -> str:
    payload = {"profile_generated_at": profile.get("generated_at"), "instruction": instruction, "provider": provider,
               "language_policy": POLICY_VERSION,
               "model": model_identity() or (os.getenv("LMSTUDIO_MODEL", "openai/gpt-oss-20b") if provider == "local" else os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"))}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def get_ai_analysis_bundle(name: str, profile: dict[str, Any], records: list[dict[str, Any]], instruction: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Run the metadata-only AI analysis once, then reuse it until the input changes."""
    from ai_client import generate_json, provider_name

    provider = provider_name()
    cache_path = project_dir(name) / "output/metadata/ai-analysis-plan.json"
    cache_key = analysis_bundle_cache_key(profile, instruction, provider)
    cached = read_json(cache_path, None)
    if isinstance(cached, dict) and cached.get("cache_key") == cache_key:
        semantic = cached.get("semantic")
        normalization = cached.get("normalization")
        requests = cached.get("calculation_requests")
        if isinstance(semantic, dict) and isinstance(normalization, dict) and isinstance(requests, list):
            return semantic, normalization, [item for item in requests if isinstance(item, dict)]

    safe_profile = cloud_safe_profile(profile)
    normalization = normalization_context(profile, records)
    allowed_fields = {field["name"] for field in safe_profile["fields"]}
    tool_fields = sorted(allowed_fields | {"record_count", "unique_student_count"})
    result = generate_json(
        "You are a careful data-governance and dashboard-analysis planner. Work only from supplied metadata and bounded category counts. "
        "Never invent facts, fields, values, formulas, relationships, or raw-data examples. Identify aggregation risks. "
        "Propose only clearly equivalent category mappings; never map identifiers, names, free text, or numeric measures. "
        "Choose no more than ten bounded aggregate requests using exact allowed fields and equality filters only.",
        f"USER REQUEST:\n{instruction or 'Create a useful management dashboard.'}\n\n"
        f"DATA PROFILE (metadata only):\n{json.dumps(safe_profile, ensure_ascii=False)}\n\n"
        f"NORMALIZATION CANDIDATES:\n{json.dumps(normalization, ensure_ascii=False)}\n\n"
        f"AVAILABLE AGGREGATE FIELDS:\n{json.dumps(tool_fields, ensure_ascii=False)}\n\n"
        "Return semantic interpretations, normalization mappings, and calculation requests in the requested JSON object.",
        analysis_bundle_schema(),
    )
    semantic_result = result.get("semantic") if isinstance(result.get("semantic"), dict) else {}
    semantic = {
        "generated_by": f"{provider}-ai",
        "source": "metadata_only",
        "profile_generated_at": profile.get("generated_at"),
        "dataset_summary": str(semantic_result.get("dataset_summary", "")),
        "warnings": [str(item) for item in semantic_result.get("warnings", [])],
        "field_interpretations": [
            item for item in semantic_result.get("field_interpretations", [])
            if isinstance(item, dict) and item.get("field") in allowed_fields
        ],
    }
    allowed_values = {item["field"]: {value["value"] for value in item["values"]} for item in normalization["fields"]}
    normalization_result = result.get("normalization") if isinstance(result.get("normalization"), dict) else {}
    normalization_plan = {
        "generated_by": f"{provider}-ai",
        "profile_generated_at": profile.get("generated_at"),
        "mappings": [
            {key: item[key] for key in ("field", "source", "target", "reason", "confidence")}
            for item in normalization_result.get("mappings", [])
            if isinstance(item, dict) and item.get("field") in allowed_values and item.get("source") in allowed_values[item["field"]]
            and isinstance(item.get("target"), str) and item["target"].strip() and float(item.get("confidence", 0)) >= 0.75
        ],
        "warnings": [str(item) for item in normalization_result.get("warnings", [])],
    }
    calculation_result = result.get("calculations") if isinstance(result.get("calculations"), dict) else {}
    calculation_requests = [item for item in calculation_result.get("requests", []) if isinstance(item, dict)]
    write_json(project_dir(name) / "output/metadata/semantic-profile.local-ai.json", semantic)
    write_json(project_dir(name) / "output/metadata/normalization-plan.ai.json", normalization_plan)
    write_json(cache_path, {"cache_key": cache_key, "semantic": semantic, "normalization": normalization_plan, "calculation_requests": calculation_requests})
    return semantic, normalization_plan, calculation_requests


def calculation_request_from_spec(item: dict[str, Any]) -> dict[str, Any]:
    formula = str(item.get("formula", ""))
    metric = str(item.get("metric", "record_count"))
    aggregation = str(item.get("aggregation", "count")).lower()
    match = re.search(r"\b(count\s*\(\s*distinct|count|sum|avg|average|min|max)\s*\(\s*([^\)]+)\s*\)", formula, flags=re.IGNORECASE)
    if match:
        token = match.group(1).lower().replace(" ", "")
        matched_metric = match.group(2).strip()
        metric = "record_count" if matched_metric == "*" else matched_metric
        aggregation = {"count(distinct": "distinct", "count": "count", "sum": "sum", "avg": "average", "average": "average", "min": "minimum", "max": "maximum"}.get(token, aggregation)
    if "distinct" in aggregation:
        aggregation = "distinct"
    elif metric.startswith("contract:"):
        aggregation = "contract"
    elif aggregation in {"avg", "average-percent"}:
        aggregation = "average"
    elif aggregation not in {"count", "sum", "average", "minimum", "maximum", "contract"}:
        aggregation = "count" if metric == "record_count" else "sum"
    filters = []
    where = re.search(r"\bwhere\s+(.+)$", formula, flags=re.IGNORECASE)
    if where:
        for field, value in re.findall(r"([^=\s]+)\s*=\s*['\"]([^'\"]+)['\"]", where.group(1)):
            filters.append({"field": field.strip(), "equals": value.strip()})
    return {"name": str(item.get("name") or item.get("title") or metric), "metric": metric, "aggregation": aggregation, "dimension": item.get("dimension"), "filters": filters}


def calculate_spec_results(records: list[dict[str, Any]], spec: dict[str, Any], profile: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    results: dict[str, Any] = {"kpis": [], "charts": [], "errors": []}
    for section, key in (("kpis", "kpis"), ("charts", "charts")):
        for item in spec.get(section, []):
            if not isinstance(item, dict):
                continue
            try:
                results[key].append(execute_calculation_tool(records, calculation_request_from_spec(item), profile, rules))
            except ValueError as exc:
                results["errors"].append(f"{item.get('name') or item.get('title') or section}: {exc}")
    return results


def render_dashboard_qa(name: str, config: dict[str, Any], spec: dict[str, Any], profile: dict[str, Any], records: list[dict[str, Any]], calculations: dict[str, Any] | None = None) -> str:
    # Build passes the one analytical copy already prepared with this project's rules.
    prepared = records
    roles = {field["name"]: field.get("role") for field in profile["fields"]}
    fields = [field["name"] for field in profile["fields"]]
    contracts = approved_metric_contracts(config.get("calculation_rules", default_calculation_rules()))
    measures = [field for field in fields if roles[field] == "measure"] + [f"contract:{contract_id}" for contract_id in contracts]
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
        formula = chart.get("formula") or (f"CONTRACT({metric.removeprefix('contract:')})" if metric.startswith("contract:") else ("COUNT(DISTINCT รหัสนักศึกษา)" if metric == "unique_student_count" else ("AVG(อัตราการจบตามวงรอบ) x 100" if "อัตรา" in metric else f"SUM({metric})")))
        target = chart.get("target") if isinstance(chart.get("target"), dict) else None
        plans.append({"id": f"chart-{index}", "title": chart.get("title", f"ภาพรวมตาม {dimension}"), "type": chart_type, "dimension": dimension, "metric": metric, "aggregation": chart.get("aggregation", ""), "formula": formula, "target": target})
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
    const verifiedCalculations = __CALCULATIONS__;
    const metricContracts = __CONTRACTS__;
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
    function formulaPlan(plan) {
        const formula = String(plan.formula || '');
        const match = formula.match(/\b(count\s*\(\s*distinct|count|sum|avg|average|min|max)\s*\(\s*([^\)]+)\s*\)/i);
        const token = match ? match[1].toLowerCase().replaceAll(' ', '') : String(plan.aggregation || '').toLowerCase();
        const metric = match ? (match[2].trim() === '*' ? 'record_count' : match[2].trim()) : plan.metric;
        const aggregation = token.includes('distinct') ? 'distinct' : token === 'avg' || token === 'average' || token.includes('percent') ? 'average' : token === 'min' ? 'minimum' : token === 'max' ? 'maximum' : token === 'count' ? 'count' : 'sum';
        const filters = [...formula.matchAll(/([^=\s]+)\s*=\s*['\"]([^'\"]+)['\"]/g)].map(match => ({field: match[1].trim(), value: match[2].trim()}));
        return {metric, aggregation, filters};
    }
    function planRows(data, plan) { const info = formulaPlan(plan); return data.filter(row => info.filters.every(filter => String(row[filter.field] ?? '').trim() === filter.value)); }
    function planAggregate(data, plan) {
        const info = formulaPlan(plan);
        if (info.metric.startsWith('contract:')) {
            const contract = metricContracts[info.metric.slice(9)];
            if (!contract) return 0;
            const sum = field => data.reduce((total, row) => total + numericValue(row[field]), 0);
            if (contract.type === 'profit') return sum(contract.revenue_field) - sum(contract.expense_field);
            if (contract.type === 'category_share') return data.length ? data.filter(row => String(row[contract.category_field] ?? '').trim() === contract.category_value).length / data.length * Number(contract.scale) : 0;
            const denominator = sum(contract.denominator_field);
            return denominator ? sum(contract.numerator_field) / denominator * Number(contract.scale) : 0;
        }
        if (info.metric === 'record_count') return data.length;
        if (info.aggregation === 'distinct') return new Set(data.map(row => String(row[info.metric] ?? '').trim()).filter(Boolean)).size;
        const values = data.map(row => numericValue(row[info.metric])).filter(Number.isFinite);
        if (!values.length) return 0;
        if (info.aggregation === 'count') return values.length;
        if (info.aggregation === 'average') return values.reduce((sum, value) => sum + value, 0) / values.length;
        if (info.aggregation === 'minimum') return Math.min(...values);
        if (info.aggregation === 'maximum') return Math.max(...values);
        return values.reduce((sum, value) => sum + value, 0);
    }
    const baseDraw = draw;
    draw = function (plan, data) {
        const constrained = planRows(data, plan);
        const buckets = {};
        constrained.forEach(row => (buckets[String(row[plan.dimension] ?? 'ไม่ระบุ')] ??= []).push(row));
        const items = Object.entries(buckets).map(([label, group]) => [label, planAggregate(group, plan)]).sort((left, right) => plan.type === 'line' ? String(left[0]).localeCompare(String(right[0]), 'th', {numeric: true}) : right[1] - left[1]).slice(0, 12);
        const max = Math.max(...items.map(item => item[1]), 1), total = items.reduce((sum, item) => sum + item[1], 0) || 1;
        const target = document.querySelector('#' + plan.id), colors = ['#263988','#0F8F83','#FECD54','#C94A4A','#8094b8','#718c8e','#6B7280'];
        const detail = `Field: ${formulaPlan(plan).metric} | Group: ${plan.dimension} | Formula: ${plan.formula} | Source rows: ${constrained.length}`;
        if (plan.type === 'pie') { let run = 0; const parts = items.map(([label, value], index) => { const start = run; run += value / total * 100; return `${colors[index % colors.length]} ${start}% ${run}%`; }); target.innerHTML = `<button class="calc" title="${esc(detail)}">วิธีคำนวณ</button><div class="pie-wrap"><div class="pie" style="background:conic-gradient(${parts.join(',')})"></div><div class="legend">${items.map(([label, value], index) => `<div style="color:${colors[index % colors.length]}">■ <span style="color:#1F2937">${esc(label)}: ${fmt.format(value)} (${fmt.format(value / total * 100)}%)</span></div>`).join('')}</div></div>`; }
        else if (plan.type === 'line') target.innerHTML = `<button class="calc" title="${esc(detail)}">วิธีคำนวณ</button><div class="line">` + items.map(([label, value], index) => `<button class="point" data-field="${esc(plan.dimension)}" data-value="${esc(label)}" style="--mark:${colors[index % colors.length]};height:${Math.max(value / max * 100, 3)}%" title="${esc(label)}: ${fmt.format(value)}"><span>${esc(label)} · ${fmt.format(value)}</span></button>`).join('') + '</div>';
        else target.innerHTML = `<button class="calc" title="${esc(detail)}">วิธีคำนวณ</button>` + items.map(([label, value], index) => `<div class="bar-row"><button class="bar-label" data-field="${esc(plan.dimension)}" data-value="${esc(label)}" title="กรองตาม ${esc(label)}">${esc(label)}</button><div class="track"><div class="bar" style="width:${Math.max(value / max * 100, 2)}%;background:${colors[index % colors.length]}"></div></div><b>${fmt.format(value)}</b></div>`).join('') || '<p class="empty">ไม่พบข้อมูล</p>';
    };
    const baseRender = render;
    render = function () {
        baseRender();
        const filtered = visible();
        document.querySelector('#kpis').innerHTML = plannedKpis.slice(0, 6).map(kpi => {
            const rowsForKpi = planRows(filtered, kpi), verified = !filterFields.some((field, index) => selectedValues(field, index).size) && !chartFilter ? verifiedCalculations.kpis.find(item => item.name === kpi.name) : null;
            const value = verified && typeof verified.value === 'number' ? verified.value : planAggregate(rowsForKpi, kpi);
            return `<article class="card"><span>${esc(kpi.name)}</span><strong>${fmt.format(value)}</strong><div class="delta neutral">${esc(kpi.formula || '')} | ${fmt.format(rowsForKpi.length)} แถว</div></article>`;
        }).join('') || '<article class="card"><span>ไม่พบ KPI ที่ผ่านการตรวจ</span></article>';
        queueMicrotask(decorate);
    };
    render();
    decorate();
})();
</script>'''
    labels = {field: display_label(field, label_overrides) for field in set(fields) | {"_year_be", "_academic_year_be", "_month_th", "_quarter", "record_count", "unique_student_count"}}
    return html.replace("</body>", enhancement.replace("__LABELS__", json.dumps(labels, ensure_ascii=False)).replace("__KPIS__", json.dumps(spec.get("kpis", []), ensure_ascii=False)).replace("__CALCULATIONS__", json.dumps(calculations or {"kpis": [], "charts": []}, ensure_ascii=False)).replace("__CONTRACTS__", json.dumps(contracts, ensure_ascii=False)).replace("__TRACKER__", tracker_html) + "</body>")


def build_project(name: str) -> dict[str, Any]:
    directory = project_dir(name)
    profile = read_json(directory / "output/metadata/dataset-profile.json", None) or profile_project(name)
    config = project_config(name, profile)
    rules = validate_calculation_rules(config["calculation_rules"])
    config["calculation_rules"] = rules
    write_json(directory / "config.json", config)
    spec = read_json(directory / "output/metadata/dashboard-spec.local-ai.json", None) or suggest_spec(name)
    require_supported_text(spec)
    records, _ = load_sources(directory / "input")
    # The bundle data contract includes the supported derived dimensions used by the spec.
    normalization_plan = get_normalization_plan(name, profile, records)
    require_supported_text(normalization_plan)
    records, transformation_notices = prepare_analytical_records(records, profile, rules, normalization_plan)
    calculations = calculate_spec_results(records, spec, profile, rules)
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
    (output / "dashboard/index.html").write_text(render_dashboard_qa(name, config, spec, profile, records, calculations), encoding="utf-8")
    missing = profile["quality"]["missing_values"]
    identifiers = [field["name"] for field in profile["fields"] if field.get("role") == "identifier"]
    date_issues = [f"{field}: parse ไม่ได้ {detail['unparsed']} ค่า" for field, detail in profile["quality"].get("date_parsing", {}).items() if detail["unparsed"]]
    checks = [{"name": "Input records", "status": "pass", "detail": f"{len(records)} records processed"}, {"name": "Identifier exclusion", "status": "pass", "detail": f"Excluded from metrics: {', '.join(identifiers) or 'None'}"}, {"name": "Duplicate rows", "status": "warning" if profile["quality"]["exact_duplicate_rows"] else "pass", "detail": str(profile["quality"]["exact_duplicate_rows"])}, {"name": "Missing values", "status": "warning" if any(missing.values()) else "pass", "detail": ", ".join(f"{key}: {value}" for key, value in missing.items() if value) or "None"}, {"name": "Date normalization", "status": "warning" if date_issues else "pass", "detail": ", ".join(date_issues) or "All recognized date values were normalized"}, {"name": "Calculation results", "status": "warning" if calculations["errors"] else "pass", "detail": "; ".join(calculations["errors"]) or f"Verified {len(calculations['kpis'])} KPI and {len(calculations['charts'])} chart calculations"}, {"name": "Data normalization", "status": "warning" if transformation_notices else "pass", "detail": "; ".join(f"{item['notice']} ({item['affected_records']} records)" for item in transformation_notices) or "No normalization was required"}]
    qa = {"status": "warning" if any(check["status"] == "warning" for check in checks) else "pass", "checks": checks}
    write_json(output / "qa/qa-report.json", qa)
    (output / "reports").mkdir(parents=True, exist_ok=True)
    (output / "reports/data-quality-report.md").write_text("# Data Quality Report\n\n" + "\n".join(f"- {check['name']}: {check['detail']}" for check in checks) + "\n", encoding="utf-8")
    (output / "reports/transformation-report.md").write_text("# Transformation Report\n\n" + ("\n".join(f"- {item['notice']}: {item['affected_records']} records" for item in transformation_notices) if transformation_notices else "- No category normalization was required.") + "\n", encoding="utf-8")
    (output / "reports/insight-report.md").write_text("# Insight Questions\n\n" + "\n".join(f"- {item}" for item in spec.get("insight_questions", [])) + "\n", encoding="utf-8")
    write_json(output / "metadata/dashboard-spec.json", spec)
    write_json(output / "metadata/calculation-results.json", calculations)
    write_json(output / "metadata/dashboard-requirements.json", {"audience": spec.get("audience"), "purpose": spec.get("purpose"), "questions": spec.get("insight_questions", []), "kpis": spec.get("kpis", []), "filters": spec.get("filters", [])})
    write_json(output / "metadata/run-manifest.json", {"project": name, "timestamp": datetime.now(timezone.utc).isoformat(), "stages": ["profile", "semantic-profile", "ai-calculation-tools", "local-ai-spec", "build", "qa"], "status": qa["status"]})
    return {"qa": qa, "dashboard": f"/api/projects/{name}/dashboard", "records": len(records)}


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    return jsonify({"service": "dashboard-factory", "status": "ok", "local_only": not app.config.get("FACTORY_LAN"), "mode": "lan" if app.config.get("FACTORY_LAN") else "local"})


@app.get("/api/projects")
def list_projects():
    result = []
    directory_root = projects_root()
    directory_root.mkdir(parents=True, exist_ok=True)
    for directory in sorted(directory_root.iterdir()):
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


@app.get("/api/projects/<name>/calculation-rules")
def get_calculation_rules(name: str):
    directory = project_dir(name)
    if not directory.exists():
        return jsonify({"error": "Project not found."}), 404
    profile = read_json(directory / "output/metadata/dataset-profile.json", None)
    if not profile:
        return jsonify({"error": "Create a Data Profile before editing calculation rules."}), 400
    config = project_config(name, profile)
    return jsonify({"rules": validate_calculation_rules(config["calculation_rules"]), "fields": [field["name"] for field in profile["fields"]], "templates": METRIC_CONTRACT_TEMPLATES})


@app.get("/api/calculation-rule-templates")
def calculation_rule_templates():
    return jsonify({"templates": METRIC_CONTRACT_TEMPLATES})


@app.put("/api/projects/<name>/calculation-rules")
def update_calculation_rules(name: str):
    directory = project_dir(name)
    if not directory.exists():
        return jsonify({"error": "Project not found."}), 404
    profile = read_json(directory / "output/metadata/dataset-profile.json", None)
    if not profile:
        return jsonify({"error": "Create a Data Profile before editing calculation rules."}), 400
    try:
        config = project_config(name, profile)
        payload_rules = (request.get_json(force=True) or {}).get("rules")
        if not isinstance(payload_rules, dict):
            raise ValueError("Calculation rules must be an object.")
        if "metric_contracts" not in payload_rules:
            payload_rules = {**payload_rules, "metric_contracts": config["calculation_rules"].get("metric_contracts", [])}
        rules = validate_calculation_rules(payload_rules)
        validate_metric_contract_fields(rules, profile)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    config["calculation_rules"] = rules
    write_json(directory / "config.json", config)
    return jsonify({"rules": rules})


@app.post("/api/projects/<name>/calculation-rules/contracts")
def save_metric_contract(name: str):
    directory = project_dir(name)
    profile = read_json(directory / "output/metadata/dataset-profile.json", None)
    if not directory.exists():
        return jsonify({"error": "Project not found."}), 404
    if not profile:
        return jsonify({"error": "Create a Data Profile before adding a metric contract."}), 400
    try:
        payload = request.get_json(force=True) or {}
        candidate = payload.get("contract")
        if not isinstance(candidate, dict):
            raise ValueError("Metric contract must be an object.")
        config = project_config(name, profile)
        existing = validate_calculation_rules(config["calculation_rules"])
        contract_id = str(candidate.get("id", "")).strip()
        previous = next((item for item in existing["metric_contracts"] if item["id"] == contract_id), None)
        if previous and previous["status"] == "approved":
            raise ValueError("Approved metric contracts cannot be edited; create a new contract id.")
        draft = {**candidate, "status": "draft", "version": (previous or {}).get("version", 0) + 1}
        contracts = [item for item in existing["metric_contracts"] if item["id"] != contract_id] + [draft]
        rules = validate_calculation_rules({**existing, "metric_contracts": contracts})
        validate_metric_contract_fields(rules, profile)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    config["calculation_rules"] = rules
    write_json(directory / "config.json", config)
    return jsonify({"rules": rules, "contract": next(item for item in rules["metric_contracts"] if item["id"] == contract_id)}), 201


@app.post("/api/projects/<name>/calculation-rules/contracts/<contract_id>/approve")
def approve_metric_contract(name: str, contract_id: str):
    directory = project_dir(name)
    profile = read_json(directory / "output/metadata/dataset-profile.json", None)
    if not directory.exists():
        return jsonify({"error": "Project not found."}), 404
    if not profile:
        return jsonify({"error": "Create a Data Profile before approving a metric contract."}), 400
    reviewer = str((request.get_json(force=True) or {}).get("approved_by", "")).strip()
    if not reviewer or len(reviewer) > 120:
        return jsonify({"error": "Enter an approver name of at most 120 characters."}), 400
    try:
        config = project_config(name, profile)
        rules = validate_calculation_rules(config["calculation_rules"])
        contract = next((item for item in rules["metric_contracts"] if item["id"] == contract_id), None)
        if not contract:
            raise ValueError("Metric contract not found.")
        if contract["status"] == "approved":
            raise ValueError("Metric contract is already approved.")
        validate_metric_contract_fields(rules, profile)
        approved_at = datetime.now(timezone.utc).isoformat()
        contract.update({"status": "approved", "approved_by": reviewer, "approved_at": approved_at})
        rules = validate_calculation_rules(rules)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    config["calculation_rules"] = rules
    write_json(directory / "config.json", config)
    history = directory / "output/metadata/calculation-rule-versions"
    history.mkdir(parents=True, exist_ok=True)
    write_json(history / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{contract_id}-v{contract['version']}.json", {"project": name, "approved_at": approved_at, "approved_by": reviewer, "contract": contract, "calculation_rules": rules})
    return jsonify({"rules": rules, "contract": contract})


@app.get("/api/projects/<name>")
def project_details(name: str):
    directory = project_dir(name)
    if not directory.exists():
        return jsonify({"error": "Project not found."}), 404
    input_directory = directory / "input"
    inputs = [
        {"name": item.name, "size": item.stat().st_size}
        for item in sorted(input_directory.iterdir())
        if item.is_file() and not item.name.startswith("~$")
    ] if input_directory.exists() else []
    profile = read_json(directory / "output/metadata/dataset-profile.json", None)
    config = project_config(name, profile) if profile else read_json(directory / "config.json", {})
    return jsonify({
        "name": name,
        "inputs": inputs,
        "built": (directory / "output/dashboard/index.html").exists(),
        "profile": profile,
        "spec": read_json(directory / "output/metadata/dashboard-spec.local-ai.json", None),
        "qa": read_json(directory / "output/qa/qa-report.json", None),
        "calculation_rules": config.get("calculation_rules"),
    })


@app.post("/api/projects/<name>/uploads")
def upload_files(name: str):
    directory = project_dir(name)
    if not directory.exists():
        return jsonify({"error": "Project not found."}), 404
    input_directory = directory / "input"
    input_directory.mkdir(exist_ok=True)
    files = request.files.getlist("files")
    saved = []
    for uploaded in files:
        original_name = uploaded.filename or ""
        suffix = Path(original_name).suffix.lower()
        if suffix not in ALLOWED_UPLOAD_SUFFIXES:
            return jsonify({"error": "Only .xlsx, .xlsm, and .csv files can be uploaded."}), 400
        stem = secure_filename(Path(original_name).stem).strip("._")
        filename = f"{stem or 'upload'}-{uuid4().hex[:8]}{suffix}"
        if not original_name:
            continue
        uploaded.save(input_directory / filename)
        saved.append(filename)
    if not saved:
        return jsonify({"error": "Choose one or more files to upload."}), 400
    return jsonify({"files": saved}), 201


@app.post("/api/projects/<name>/profile")
def api_profile(name: str):
    try:
        profile = profile_project(name)
        config = project_config(name, profile)
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


@app.post("/api/projects/<name>/requirement-template")
def api_requirement_template(name: str):
    directory = project_dir(name)
    if not directory.exists():
        return jsonify({"error": "Project not found."}), 404
    profile = read_json(directory / "output/metadata/dataset-profile.json", None)
    if not profile:
        return jsonify({"error": "Create a Data Profile before generating a requirement template."}), 400
    return jsonify({"instruction": dashboard_requirement_template(profile, project_config(name, profile))})


@app.post("/api/projects/<name>/suggest-jobs")
def start_suggest_job(name: str):
    if not project_dir(name).exists():
        return jsonify({"error": "Project not found."}), 404
    instruction = str((request.get_json(silent=True) or {}).get("instruction", ""))
    job_id = uuid4().hex
    with AI_JOBS_LOCK:
        owner = CURRENT_OWNER.get()
        if app.config.get("FACTORY_LAN") and sum(job["status"] == "running" for job in AI_JOBS.values()) >= 8:
            return jsonify({"error": "AI queue is busy. Please try again later."}), 429
        if any(job.get("owner") == owner and job["project"] == name and job["status"] == "running" for job in AI_JOBS.values()):
            return jsonify({"error": "AI is already working on this project."}), 409
        if app.config.get("FACTORY_LAN") and not LAN_AI_SLOTS.acquire(blocking=False):
            return jsonify({"error": "AI capacity is full. Please retry later."}), 429
        # Keep recent progress without accumulating every completed spec indefinitely.
        for old_id in list(AI_JOBS):
            if len(AI_JOBS) > 100 and AI_JOBS[old_id]["status"] != "running":
                del AI_JOBS[old_id]
        AI_JOBS[job_id] = {"owner": owner, "project": name, "status": "running", "percent": 0, "stage": "กำลังเริ่มงาน AI", "result": None, "error": None}

    def update(percent: int, stage: str) -> None:
        with AI_JOBS_LOCK:
            if job_id in AI_JOBS:
                AI_JOBS[job_id].update({"percent": percent, "stage": stage})

    def run() -> None:
        try:
            result = suggest_spec(name, instruction, update)
            with AI_JOBS_LOCK:
                AI_JOBS[job_id].update({"status": "completed", "percent": 100, "result": result})
        except Exception as exc:
            with AI_JOBS_LOCK:
                AI_JOBS[job_id].update({"status": "failed", "error": str(exc), "stage": "สร้าง specification ไม่สำเร็จ"})
        finally:
            if app.config.get("FACTORY_LAN"):
                LAN_AI_SLOTS.release()

    context = copy_context()
    Thread(target=lambda: context.run(run), name=f"factory-suggest-{job_id[:8]}", daemon=True).start()
    return jsonify({"job_id": job_id, "status": "running", "percent": 0}), 202


@app.get("/api/ai-jobs/<job_id>")
def get_ai_job(job_id: str):
    with AI_JOBS_LOCK:
        job = AI_JOBS.get(job_id)
        if not job or job.get("owner") != CURRENT_OWNER.get():
            return jsonify({"error": "AI job not found or Factory was restarted."}), 404
        return jsonify(job)


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


@app.get("/api/projects/<name>/publish-package")
def publish_package(name: str):
    """Export review metadata and a no-row-data HTML summary for DataLink publishing."""
    directory = project_dir(name)
    spec = read_json(directory / "output/metadata/dashboard-spec.json", None)
    qa = read_json(directory / "output/qa/qa-report.json", None)
    manifest = read_json(directory / "output/metadata/run-manifest.json", None)
    if not spec or not qa or not manifest:
        return jsonify({"error": "Build and QA must finish before preparing a publish package."}), 400
    if qa.get("status") not in {"pass", "warning"}:
        return jsonify({"error": "QA status is not eligible for review."}), 400
    title = escape(str(spec.get("dashboard_title", name)))
    purpose = escape(str(spec.get("purpose", "")))
    html = f'<!doctype html><html lang="th"><head><meta charset="utf-8"><title>{title}</title></head><body><main><h1>{title}</h1><p>{purpose}</p><p>Dashboard นี้จัดการสิทธิ์และสถานะการเผยแพร่โดย DataLink</p></main></body></html>'
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
    return jsonify({"package_version": 1, "project": name, "generated_at": manifest.get("timestamp"), "qa_status": qa.get("status"), "dashboard_html": html, "sha256": digest, "spec": spec, "run_manifest": manifest})


@app.get("/api/projects/<name>/datalink-bundle")
def datalink_bundle(name: str):
    """Create a portable, credential-free Dataset import bundle for DataLink."""
    directory = project_dir(name)
    spec = read_json(directory / "output/metadata/dashboard-spec.json", None)
    qa = read_json(directory / "output/qa/qa-report.json", None)
    run_manifest = read_json(directory / "output/metadata/run-manifest.json", None)
    data_path = directory / "output/data/records.csv"
    if not spec or not qa or not run_manifest or not data_path.exists():
        return jsonify({"error": "Build and QA must finish before preparing a DataLink Bundle."}), 400
    if qa.get("status") not in {"pass", "warning"}:
        return jsonify({"error": "QA status is not eligible for import."}), 400

    data = data_path.read_bytes()
    spec_data = json.dumps(spec, ensure_ascii=False, indent=2).encode("utf-8")
    qa_data = json.dumps(qa, ensure_ascii=False, indent=2).encode("utf-8")
    bundle_manifest = {
        "bundle_version": 1,
        "project": name,
        "generated_at": run_manifest.get("timestamp"),
        "qa_status": qa.get("status"),
        "files": {
            "data.csv": {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)},
            "dashboard-spec.json": {"sha256": hashlib.sha256(spec_data).hexdigest(), "size_bytes": len(spec_data)},
            "qa-report.json": {"sha256": hashlib.sha256(qa_data).hexdigest(), "size_bytes": len(qa_data)},
        },
    }
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(bundle_manifest, ensure_ascii=False, indent=2))
        bundle.writestr("dashboard-spec.json", spec_data)
        bundle.writestr("qa-report.json", qa_data)
        bundle.writestr("data.csv", data)
    archive.seek(0)
    return send_file(archive, mimetype="application/zip", as_attachment=True, download_name=f"{name}-datalink-bundle.zip")


if __name__ == "__main__":
    if app.config.get("FACTORY_LAN"):
        raise SystemExit("Use lan/serve.py for LAN mode; the debug server is local-development only.")
    app.run(host="127.0.0.1", port=5050, debug=True)
