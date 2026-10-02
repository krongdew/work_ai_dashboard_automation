"""Create the DataLink Bundle for the Executive Overview dashboard."""

from __future__ import annotations

import base64
import csv
import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_DIR / "output"
DATA_DIR = OUTPUT_DIR / "data"
QA_FILE = OUTPUT_DIR / "qa" / "qa-report.json"
SPEC_FILE = OUTPUT_DIR / "metadata" / "dashboard-spec.json"
HTML_FILE = OUTPUT_DIR / "dashboard" / "index.html"
LOGO_FILE = OUTPUT_DIR / "dashboard" / "assets" / "mahidol-logo.png"
BUNDLE_DIR = OUTPUT_DIR / "datalink-bundle"
BUNDLE_FILE = OUTPUT_DIR / "Executive-DataLink-Bundle.zip"

SOURCES = (
    ("education", "education-current", DATA_DIR / "education-summary.csv"),
    ("education", "education-graduate", DATA_DIR / "graduate-summary.csv"),
    ("mobility", "mobility", DATA_DIR / "mobility-summary.csv"),
    ("research", "research", DATA_DIR / "research-summary.csv"),
    ("personnel", "personnel-current", DATA_DIR / "personnel-summary.csv"),
    ("investment", "investment-monthly", DATA_DIR / "investment-monthly-summary.csv"),
)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_json(path: Path, payload: dict) -> bytes:
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    path.write_bytes(content)
    return content


def read_rows(section: str, record_type: str, path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise RuntimeError(f"Missing dashboard data file: {path.name}")
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames:
            raise RuntimeError(f"Dashboard data file has no header: {path.name}")
        return [
            {
                "dashboard_section": section,
                "record_type": record_type,
                **{key: value or "" for key, value in row.items()},
            }
            for row in reader
        ]


def write_csv(path: Path, rows: list[dict[str, str]]) -> bytes:
    if not rows:
        raise RuntimeError("The combined dashboard CSV has no records.")
    fields = ["dashboard_section", "record_type"]
    fields.extend(sorted({field for row in rows for field in row} - set(fields)))
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    content = path.read_bytes()
    if b"\0" in content:
        raise RuntimeError("The combined dashboard CSV is invalid.")
    return content


def self_contained_dashboard_html() -> bytes:
    if not HTML_FILE.is_file() or not LOGO_FILE.is_file():
        raise RuntimeError("Executive dashboard HTML or logo is missing.")
    html = HTML_FILE.read_text(encoding="utf-8")
    logo_uri = "data:image/png;base64," + base64.b64encode(LOGO_FILE.read_bytes()).decode("ascii")
    html = html.replace('src="assets/mahidol-logo.png"', f'src="{logo_uri}"')
    if 'src="assets/mahidol-logo.png"' in html:
        raise RuntimeError("Could not inline the Executive dashboard logo.")
    html = html.replace(
        "</head>",
        "<style>html,body{background:transparent!important;overflow:visible!important;height:auto!important}</style>"
        "<script>(()=>{const report=()=>parent.postMessage({type:'factory-dashboard-height',height:document.documentElement.scrollHeight},'*');new ResizeObserver(report).observe(document.documentElement);addEventListener('load',report);setTimeout(report,0)})()</script></head>",
        1,
    )
    content = html.encode("utf-8")
    if len(content) > 2_000_000:
        raise RuntimeError("The self-contained dashboard exceeds the 2 MB import limit.")
    return content


def build_spec(factory_spec: dict) -> dict:
    labels = {
        "dashboard_section": "มุมมอง", "record_type": "ประเภทระเบียน", "education_level": "ระดับการศึกษา",
        "program": "หลักสูตร", "entry_year": "ปีที่เข้าศึกษา", "entry_month": "เดือนที่เข้าศึกษา",
        "entry_fiscal_year": "ปีงบประมาณที่เข้า", "study_year": "ชั้นปี", "student_status": "สถานภาพนักศึกษา",
        "direction": "ทิศทาง", "academic_year": "ปีการศึกษา", "country": "ประเทศ", "university": "มหาวิทยาลัยคู่ความร่วมมือ",
        "year": "ปี", "type": "ประเภทผลงาน", "journal": "วารสาร", "status": "สถานะบุคลากร",
        "position": "ตำแหน่ง", "work_line": "สายงาน", "report_date": "วันที่รายงาน",
        "net_asset_value": "มูลค่าทรัพย์สินสุทธิ", "period_return": "ผลตอบแทนช่วงรายงาน",
    }
    return {
        "dashboard_title": factory_spec.get("title", "Executive Overview Dashboard"),
        "renderer": "executive-overview",
        "purpose": "ติดตามภาพรวมการศึกษา วิเทศน์ วิจัย บุคลากร และการลงทุนจากข้อมูลที่ผ่านการตรวจสอบแล้ว",
        "audience": "ผู้บริหารคณะ",
        "display_labels": labels,
        "tabs": [
            {
                "key": "education", "label": "การศึกษา", "fixed_filters": {"dashboard_section": ["education"]},
                "filters": ["record_type", "education_level", "entry_year", "entry_month", "entry_fiscal_year", "study_year"],
                "kpis": [{"name": "จำนวนระเบียนการศึกษา", "metric": "record_count", "aggregation": "count", "formula": "COUNT(*)"}],
                "charts": [{"title": "ระเบียนตามระดับการศึกษา", "type": "bar", "dimension": "education_level", "metric": "record_count", "aggregation": "count", "formula": "COUNT(*)"}],
            },
            {
                "key": "mobility", "label": "วิเทศน์", "fixed_filters": {"dashboard_section": ["mobility"]},
                "filters": ["academic_year", "month", "direction", "country"],
                "kpis": [{"name": "จำนวนระเบียน mobility", "metric": "record_count", "aggregation": "count", "formula": "COUNT(*)"}],
                "charts": [{"title": "Mobility ตามประเทศ", "type": "bar", "dimension": "country", "metric": "record_count", "aggregation": "count", "formula": "COUNT(*)"}],
            },
            {
                "key": "research", "label": "วิจัย", "fixed_filters": {"dashboard_section": ["research"]},
                "filters": ["year", "type", "journal"],
                "kpis": [{"name": "ผลงานวิจัย", "metric": "record_count", "aggregation": "count", "formula": "COUNT(*)"}],
                "charts": [{"title": "ผลงานตามประเภท", "type": "bar", "dimension": "type", "metric": "record_count", "aggregation": "count", "formula": "COUNT(*)"}],
            },
            {
                "key": "personnel", "label": "บุคลากร", "fixed_filters": {"dashboard_section": ["personnel"]},
                "filters": ["status", "work_line", "position"],
                "kpis": [{"name": "จำนวนบุคลากร", "metric": "record_count", "aggregation": "count", "formula": "COUNT(*)"}],
                "charts": [{"title": "บุคลากรตามสายงาน", "type": "bar", "dimension": "work_line", "metric": "record_count", "aggregation": "count", "formula": "COUNT(*)"}],
            },
            {
                "key": "investment", "label": "การลงทุน", "fixed_filters": {"dashboard_section": ["investment"]},
                "filters": ["year", "month"],
                "kpis": [{"name": "มูลค่าทรัพย์สินสุทธิ", "metric": "net_asset_value", "aggregation": "sum", "formula": "SUM(net_asset_value)"}],
                "charts": [{"title": "มูลค่าทรัพย์สินสุทธิตามช่วงรายงาน", "type": "line", "dimension": "report_date", "metric": "net_asset_value", "aggregation": "sum", "formula": "SUM(net_asset_value)"}],
            },
        ],
    }


def main() -> None:
    qa = json.loads(QA_FILE.read_text(encoding="utf-8"))
    if qa.get("critical_errors"):
        raise RuntimeError("Executive dashboard has critical QA errors; cannot create a DataLink Bundle.")
    factory_spec = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    all_rows = [row for section, record_type, path in SOURCES for row in read_rows(section, record_type, path)]

    if BUNDLE_DIR.exists():
        shutil.rmtree(BUNDLE_DIR)
    BUNDLE_DIR.mkdir(parents=True)

    data = write_csv(BUNDLE_DIR / "data.csv", all_rows)
    spec_data = write_json(BUNDLE_DIR / "dashboard-spec.json", build_spec(factory_spec))
    qa_data = write_json(BUNDLE_DIR / "qa-report.json", {
        "status": "warning" if qa.get("warnings") else "pass",
        "source_qa_status": qa.get("status"),
        "critical_errors": [],
        "warnings": qa.get("warnings", []),
        "checks": qa.get("checks", []),
    })
    dashboard_html = self_contained_dashboard_html()
    (BUNDLE_DIR / "dashboard.html").write_bytes(dashboard_html)

    manifest = {
        "bundle_version": 1,
        "project": "Executive",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "qa_status": "warning" if qa.get("warnings") else "pass",
        "files": {
            "data.csv": {"sha256": sha256(data), "bytes": len(data)},
            "dashboard-spec.json": {"sha256": sha256(spec_data), "bytes": len(spec_data)},
            "qa-report.json": {"sha256": sha256(qa_data), "bytes": len(qa_data)},
            "dashboard.html": {"sha256": sha256(dashboard_html), "bytes": len(dashboard_html)},
        },
    }
    write_json(BUNDLE_DIR / "manifest.json", manifest)

    with zipfile.ZipFile(BUNDLE_FILE, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename in ("manifest.json", "dashboard-spec.json", "qa-report.json", "data.csv", "dashboard.html"):
            archive.write(BUNDLE_DIR / filename, arcname=filename)
    print(f"Created {BUNDLE_FILE}")
    print(f"Managed data rows: {len(all_rows)}")


if __name__ == "__main__":
    main()