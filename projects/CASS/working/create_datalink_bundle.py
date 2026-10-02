"""Create a complete tabbed DataLink Bundle from QA-validated CASS datasets."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import zipfile
import base64
from datetime import datetime, timezone
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_DIR / "output"
DATA_DIR = OUTPUT_DIR / "data"
SOURCE_QA_FILE = OUTPUT_DIR / "qa" / "qa-report.json"
BUNDLE_DIR = OUTPUT_DIR / "datalink-bundle"
BUNDLE_FILE = OUTPUT_DIR / "CASS-DataLink-Bundle.zip"
HTML_FILE = OUTPUT_DIR / "dashboard" / "index.html"
LOGO_FILE = OUTPUT_DIR / "dashboard" / "assets" / "mahidol-logo.png"
PUBLISH_PACKAGE_FILE = OUTPUT_DIR / "CASS-Dashboard-Publish-Package.json"
SOURCES = (
    ("income", DATA_DIR / "service-excellence-records.csv"),
    ("community", DATA_DIR / "non-income-academic-services.csv"),
    ("budget", DATA_DIR / "budget-control-records.csv"),
)
INCOME_FIELDS = {
    "fiscal_year",
    "quarter",
    "project_type",
    "service_group",
    "project_name",
    "actual_participants",
    "revenue",
    "expense",
    "reported_profit",
    "satisfaction",
    "unit",
}
COMMUNITY_FIELDS = {"fiscal_year", "project_name", "format", "social_benefit", "budget", "expense", "participants", "satisfaction"}


def read_rows(section: str, path: Path, required_fields: set[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        fields = set(reader.fieldnames or [])
        missing_fields = sorted(required_fields - fields)
        if missing_fields:
            raise RuntimeError(f"{path.name} is missing required fields: {', '.join(missing_fields)}")
        rows = [{"dashboard_section": section, **{key: value or "" for key, value in row.items()}} for row in reader]
    if not rows:
        raise RuntimeError(f"{path.name} has no records.")
    return rows


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_json(path: Path, payload: dict) -> bytes:
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    path.write_bytes(content)
    return content


def write_csv(path: Path, rows: list[dict[str, str]]) -> bytes:
    fields = ["dashboard_section"]
    fields.extend(sorted({field for row in rows for field in row if field != "dashboard_section"}))
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    content = path.read_bytes()
    if not content or b"\0" in content:
        raise RuntimeError("The combined CSV is empty or invalid.")
    return content


def self_contained_dashboard_html() -> str:
    """Return the generated visual dashboard with its local logo embedded."""
    if not HTML_FILE.is_file() or not LOGO_FILE.is_file():
        raise RuntimeError("CASS dashboard HTML or Mahidol logo is missing.")
    dashboard_html = HTML_FILE.read_text(encoding="utf-8")
    logo_data_uri = "data:image/png;base64," + base64.b64encode(LOGO_FILE.read_bytes()).decode("ascii")
    updated_html = dashboard_html.replace('src="assets/mahidol-logo.png"', f'src="{logo_data_uri}"')
    if updated_html == dashboard_html:
        raise RuntimeError("Could not inline the Mahidol logo in the CASS dashboard HTML.")
    updated_html = updated_html.replace(
        "</head>",
        "<style>html,body{background:transparent!important;overflow:visible!important;height:auto!important}main{max-width:none!important;margin:0!important;padding:0 0 36px!important}</style><script>(()=>{const report=()=>parent.postMessage({type:'factory-dashboard-height',height:document.documentElement.scrollHeight},'*');new ResizeObserver(report).observe(document.documentElement);addEventListener('load',report);setTimeout(report,0)})()</script></head>",
        1,
    )
    return updated_html


def create_publish_package(dashboard_html: str) -> None:
    """Create a standalone package for existing Dashboard Library workflows."""
    package = {
        "package_version": 1,
        "qa_status": "warning",
        "dashboard_html": dashboard_html,
        "sha256": sha256(dashboard_html.encode("utf-8")),
    }
    write_json(PUBLISH_PACKAGE_FILE, package)


def main() -> None:
    source_qa = json.loads(SOURCE_QA_FILE.read_text(encoding="utf-8"))
    if source_qa.get("critical_errors"):
        raise RuntimeError("CASS has critical QA errors; a DataLink Bundle cannot be created.")

    income_rows = read_rows(*SOURCES[0], INCOME_FIELDS)
    community_rows = read_rows(*SOURCES[1], COMMUNITY_FIELDS)
    budget_rows = read_rows(*SOURCES[2], INCOME_FIELDS)
    rows = [*income_rows, *community_rows, *budget_rows]

    if BUNDLE_DIR.exists():
        shutil.rmtree(BUNDLE_DIR)
    BUNDLE_DIR.mkdir(parents=True)
    data = write_csv(BUNDLE_DIR / "data.csv", rows)
    dashboard_html = self_contained_dashboard_html()
    dashboard_html_data = dashboard_html.encode("utf-8")
    (BUNDLE_DIR / "dashboard.html").write_bytes(dashboard_html_data)

    spec = {
        "dashboard_title": "CASS Operational & Service Excellence",
        "renderer": "cass-operational-service-excellence",
        "purpose": "Monitor operational services, non-income academic services, and budget registers from the CASS source datasets.",
        "audience": "CASS executives and operational staff",
        "insight_questions": [
            "How do operational service outcomes change across fiscal years?",
            "How do non-income academic services support participants and social benefit?",
            "How do revenue, expense, and profit compare in the budget registers?",
        ],
        "display_labels": {
            "fiscal_year": "ปีงบประมาณ", "quarter": "ไตรมาส", "project_type": "ประเภทโครงการ", "service_group": "กลุ่มผู้รับบริการ", "unit": "สังกัด",
            "project_name": "โครงการ", "revenue": "รายได้", "expense": "รายจ่าย", "reported_profit": "กำไร", "actual_participants": "ผู้เข้าร่วมจริง",
            "satisfaction": "ความพึงพอใจ", "format": "รูปแบบ", "participants": "ผู้เข้าร่วม", "budget": "งบประมาณ", "social_benefit": "ประโยชน์ต่อสังคม",
        },
        "tabs": [
            {
                "key": "income", "label": "บริการมีรายได้", "fixed_filters": {"dashboard_section": ["income"]},
                "filters": ["fiscal_year", "quarter", "project_type", "service_group", "unit"],
                "kpis": [
                    {"name": "รายได้", "metric": "revenue", "aggregation": "sum", "formula": "SUM(revenue)", "source_fields": ["revenue"]},
                    {"name": "กำไรตามแหล่งข้อมูล", "metric": "reported_profit", "aggregation": "sum", "formula": "SUM(reported_profit)", "source_fields": ["reported_profit"]},
                    {"name": "รายจ่าย", "metric": "expense", "aggregation": "sum", "formula": "SUM(expense)", "source_fields": ["expense"]},
                    {"name": "ผู้เข้าร่วมจริง", "metric": "actual_participants", "aggregation": "sum", "formula": "SUM(actual_participants)", "source_fields": ["actual_participants"]},
                    {"name": "ความพึงพอใจเฉลี่ย", "metric": "satisfaction", "aggregation": "average", "formula": "AVG(satisfaction)", "source_fields": ["satisfaction"]},
                ],
                "charts": [
                    {"title": "แนวโน้มรายได้ตามปีงบประมาณ", "type": "line", "dimension": "fiscal_year", "metric": "revenue", "aggregation": "sum", "formula": "SUM(revenue)", "source_fields": ["fiscal_year", "revenue"]},
                    {"title": "แนวโน้มกำไรตามปีงบประมาณ", "type": "line", "dimension": "fiscal_year", "metric": "reported_profit", "aggregation": "sum", "formula": "SUM(reported_profit)", "source_fields": ["fiscal_year", "reported_profit"]},
                    {"title": "รายได้ตามประเภทโครงการ", "type": "bar", "dimension": "project_type", "metric": "revenue", "aggregation": "sum", "formula": "SUM(revenue)", "source_fields": ["project_type", "revenue"]},
                    {"title": "รายได้ตามกลุ่มบริการ", "type": "bar", "dimension": "service_group", "metric": "revenue", "aggregation": "sum", "formula": "SUM(revenue)", "source_fields": ["service_group", "revenue"]},
                ],
                "tables": [{"title": "รายละเอียดบริการมีรายได้", "fields": ["fiscal_year", "project_name", "project_type", "service_group", "revenue", "expense", "reported_profit", "actual_participants", "satisfaction"], "limit": 250}],
            },
            {
                "key": "community", "label": "บริการวิชาการแบบไม่ได้รายได้", "fixed_filters": {"dashboard_section": ["community"]}, "filters": ["fiscal_year"],
                "kpis": [
                    {"name": "กิจกรรม", "metric": "record_count", "aggregation": "count", "formula": "COUNT(*)"},
                    {"name": "ผู้เข้าร่วม", "metric": "participants", "aggregation": "sum", "formula": "SUM(participants)", "source_fields": ["participants"]},
                    {"name": "งบประมาณ", "metric": "budget", "aggregation": "sum", "formula": "SUM(budget)", "source_fields": ["budget"]},
                    {"name": "ค่าใช้จ่าย", "metric": "expense", "aggregation": "sum", "formula": "SUM(expense)", "source_fields": ["expense"]},
                    {"name": "ความพึงพอใจเฉลี่ย", "metric": "satisfaction", "aggregation": "average", "formula": "AVG(satisfaction)", "source_fields": ["satisfaction"]},
                ],
                "charts": [
                    {"title": "ผู้เข้าร่วมตามปีงบประมาณ", "type": "bar", "dimension": "fiscal_year", "metric": "participants", "aggregation": "sum", "formula": "SUM(participants)", "source_fields": ["fiscal_year", "participants"]},
                    {"title": "ผลกระทบทางสังคม", "type": "bar", "dimension": "social_benefit", "metric": "record_count", "aggregation": "count", "formula": "COUNT(*)", "source_fields": ["social_benefit"]},
                ],
                "tables": [{"title": "รายละเอียดกิจกรรม", "fields": ["fiscal_year", "project_name", "format", "participants", "budget", "expense", "social_benefit", "satisfaction"], "limit": 100}],
            },
            {
                "key": "budget", "label": "เปรียบเทียบงบประมาณ", "fixed_filters": {"dashboard_section": ["budget"]}, "filters": ["fiscal_year", "project_type"],
                "kpis": [
                    {"name": "รายการ", "metric": "record_count", "aggregation": "count", "formula": "COUNT(*)"},
                    {"name": "รายได้", "metric": "revenue", "aggregation": "sum", "formula": "SUM(revenue)", "source_fields": ["revenue"]},
                    {"name": "รายจ่าย", "metric": "expense", "aggregation": "sum", "formula": "SUM(expense)", "source_fields": ["expense"]},
                    {"name": "กำไร", "metric": "reported_profit", "aggregation": "sum", "formula": "SUM(reported_profit)", "source_fields": ["reported_profit"]},
                    {"name": "ผู้เข้าร่วม", "metric": "actual_participants", "aggregation": "sum", "formula": "SUM(actual_participants)", "source_fields": ["actual_participants"]},
                ],
                "charts": [
                    {"title": "รายได้ตามปีงบประมาณ", "type": "bar", "dimension": "fiscal_year", "metric": "revenue", "aggregation": "sum", "formula": "SUM(revenue)", "source_fields": ["fiscal_year", "revenue"]},
                    {"title": "รายได้ตามประเภทบริการ", "type": "bar", "dimension": "project_type", "metric": "revenue", "aggregation": "sum", "formula": "SUM(revenue)", "source_fields": ["project_type", "revenue"]},
                ],
                "tables": [{"title": "รายละเอียดทะเบียนคุมงบ", "fields": ["fiscal_year", "project_name", "project_type", "source_sheet", "revenue", "expense", "reported_profit", "actual_participants", "satisfaction"], "limit": 100}],
            },
        ],
    }
    spec_data = write_json(BUNDLE_DIR / "dashboard-spec.json", spec)

    qa = {
        "status": "warning",
        "source_qa_status": source_qa.get("status"),
        "critical_errors": [],
        "warnings": [
            "Fiscal year 2569 may be partial or include activities spanning fiscal years.",
            "The three CASS views use different source grains and are isolated by dashboard_section in one managed Dataset.",
        ],
        "checks": [
            {"check": "income records", "expected": 1130, "actual": len(income_rows), "result": "PASS" if len(income_rows) == 1130 else "WARNING"},
            {"check": "non-income records", "expected": 12, "actual": len(community_rows), "result": "PASS" if len(community_rows) == 12 else "WARNING"},
            {"check": "budget register records", "expected": 83, "actual": len(budget_rows), "result": "PASS" if len(budget_rows) == 83 else "WARNING"},
            {"check": "combined record count", "expected": 1225, "actual": len(rows), "result": "PASS" if len(rows) == 1225 else "WARNING"},
            {"check": "source QA critical errors", "expected": 0, "actual": 0, "result": "PASS"},
        ],
    }
    qa_data = write_json(BUNDLE_DIR / "qa-report.json", qa)

    manifest = {
        "bundle_version": 1,
        "project": "CASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "qa_status": qa["status"],
        "files": {
            "data.csv": {"sha256": sha256(data), "bytes": len(data)},
            "dashboard-spec.json": {"sha256": sha256(spec_data), "bytes": len(spec_data)},
            "qa-report.json": {"sha256": sha256(qa_data), "bytes": len(qa_data)},
            "dashboard.html": {"sha256": sha256(dashboard_html_data), "bytes": len(dashboard_html_data)},
        },
    }
    write_json(BUNDLE_DIR / "manifest.json", manifest)

    with zipfile.ZipFile(BUNDLE_FILE, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("manifest.json", "dashboard-spec.json", "qa-report.json", "data.csv", "dashboard.html"):
            archive.write(BUNDLE_DIR / name, arcname=name)

    create_publish_package(dashboard_html)

    print(f"Created {BUNDLE_FILE}")
    print(f"Created {PUBLISH_PACKAGE_FILE}")
    print(f"Tab rows: income={len(income_rows)}, community={len(community_rows)}, budget={len(budget_rows)}")


if __name__ == "__main__":
    main()