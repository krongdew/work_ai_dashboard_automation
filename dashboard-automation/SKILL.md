---
name: dashboard-automation
description: >
  Production-ready multi-project dashboard automation. Turns Excel/CSV files
  in a selected project's input folder into a validated dashboard. Use when
  the user asks to create, update, analyze, validate, or publish a dashboard.
---

# Dashboard Automation Skill

## Core goal

Turn project-specific Excel/CSV files into a usable dashboard while keeping
raw data unchanged and producing traceable analysis, requirements, QA, and
documentation.

## Project structure

Each dashboard is an independent project:

projects/<project-name>/
├── input/
├── output/
├── working/
├── config.json
└── dashboard-request.md   # optional

Never mix datasets between projects unless the user explicitly asks for it.

## Default workflow

DISCOVER
→ PROFILE
→ QUALITY
→ ANALYZE
→ REQUIREMENTS
→ DESIGN
→ TRANSFORM
→ BUILD
→ QA
→ INSIGHTS
→ DELIVER

## Rules

1. Never modify original files in `input/`.
2. Never fabricate data or KPI values.
3. Never silently delete records.
4. Every KPI needs a definition, formula, and source fields.
5. Every visualization must answer an analytical question.
6. Record important transformations.
7. Validate major KPI values independently.
8. If critical QA fails, status is NOT READY.
9. State assumptions and data limitations.
10. Do not publish sensitive raw data.

## Institutional theme

All generated dashboards must use the Mahidol Faculty institutional theme at:
`dashboard-automation/themes/mahidol-faculty.md`

Apply its color tokens, flat background, card treatment, and chart styling.
Do not introduce gradients, decorative backgrounds, unapproved primary colors,
neon colors, or 3D charts. Record the selected theme in each project config.
Copy `dashboard-automation/assets/logo.png` into each generated dashboard's
`assets/` directory and display it in the institutional header. Show readable
data labels for plotted values unless density would make labels misleading.

## Selecting a project

When the user says:
- "สร้าง dashboard ใหม่" → create a new project under `projects/`.
- "อัปเดต dashboard X" → use `projects/X/`.
- "วิเคราะห์ข้อมูล X" → use `projects/X/`.
- If a project name is ambiguous, inspect available projects and ask only if necessary.

Project names should be lowercase kebab-case, e.g.:
- sales
- student-analytics
- worktrack
- finance-2026

## Creating a new project

Create:

projects/<project-name>/
├── input/
├── output/
├── working/
└── config.json

Use this default config:

{
  "name": "<project-name>",
  "language": "th",
  "timezone": "Asia/Bangkok",
  "dashboard_type": "auto",
  "audience": "auto",
  "show_insights": true,
  "show_data_table": true,
  "responsive": true,
  "theme": "mahidol-faculty"
}

Do not ask for information that can reasonably be inferred from the data.

## Optional dashboard-request.md

If present, treat explicit requirements as higher priority than AI inference.

Example:

# Dashboard Request

Audience: ผู้บริหาร
Purpose: ติดตามผลการดำเนินงาน
Important metrics:
- revenue
- orders
- profit

## Input discovery

Inspect all `.csv`, `.xlsx`, and `.xls` files in the selected project's `input/`.

Identify:
- row/column counts
- sheets
- data types
- semantic field role: identifier, measure, category, or date
- date fields
- measures
- dimensions
- IDs
- relationships
- date coverage

Create:
`output/metadata/dataset-profile.json`

## AI semantic profile

After deterministic profiling, use the configured AI provider to create
`output/metadata/semantic-profile.local-ai.json` before proposing a dashboard
specification. This is an advisory layer, not a replacement for profiling or
calculation rules.

Send only privacy-reduced metadata: field names, detected roles and types,
non-null/distinct counts, numeric ratios, date parsing coverage, and derived
dimensions. Do not send source files, rows, example values, identifiers, or PII
fields to a cloud provider.

Use the AI result to suggest a field's likely business meaning, unit, and safe
aggregation guidance with confidence and limitations. Validate every suggestion
against the deterministic profile and data rules. AI must never create a field,
relationship, formula, KPI, or value not grounded in the source profile.
Regenerate the semantic profile whenever the deterministic profile changes.

## AI-assisted normalization

Create a normalization plan from low-cardinality category and date values after
profiling. The configured AI provider may propose an exact-value mapping only
when values are clearly equivalent. Validate that the field and source value
exist in the profile before applying a mapping. Never map identifiers, names,
free-text fields, high-cardinality values, or numeric measures automatically.

Apply accepted mappings only to analytical output; never edit raw input. Record
every source-to-target change, its reason, affected-row count, and all AI
warnings in `output/reports/transformation-report.md`. A warning is required
when a value is ambiguous or cannot be normalized safely.

Detect date fields from values as well as headers. Parse valid Thai Buddhist
Era, Gregorian, ISO datetime, Thai month-name, and English month-name values
into normalized dashboard dimensions. All dashboard year summaries, filters,
and labels must display Buddhist Era years. Retain raw date values only for
traceability; do not group charts on mixed raw date strings.

## Data quality

Check:
- missing values
- duplicates
- invalid dates
- inconsistent categories
- suspicious numeric values
- unexpected ranges
- coverage gaps

Create:
`output/reports/data-quality-report.md`

Do not silently repair data.

## Business analysis

Identify supported:
- KPIs
- trends
- rankings
- comparisons
- segments
- anomalies

For every KPI record:
- name
- definition
- formula
- source fields
- aggregation
- limitations

## Dashboard requirements

Determine:
- audience
- purpose
- primary questions
- KPIs
- filters
- charts
- alerts
- detail views

Create:
`output/metadata/dashboard-requirements.json`

## Dashboard design

Preferred visualization:
- KPI → KPI card
- trend → line
- category comparison → bar
- ranking → sorted horizontal bar
- exact records → table
- relationship → scatter
- 2D pattern → heatmap

Avoid decorative and misleading charts.

Never use identifiers (student IDs, document IDs, codes, or near-unique
numbers) as a KPI metric, aggregation, chart axis, or filter. If a field has
too many distinct category values for a readable chart, do not chart it; report
that grouping or source-data review is required instead.

For each date field, parse the dominant valid format first, normalize compatible
formats into BE year, Thai abbreviated month, and quarter, and report values
that cannot be parsed. Never show raw mixed-format dates as separate chart
categories. A date-based chart must use a normalized year/month/quarter
dimension.

Generate filters from suitable low-cardinality dimensions. Filters must allow
multiple selected values; no selected values means all values. When date data
supports it, include multi-select year, month, and quarter filters. Explicit
user requirements may add filters only when their fields pass these checks.

## Global Language And Layout Standard

Never expose internal field names such as `_year_be` or `_academic_year_be` in
the user interface. Use concise context-appropriate Thai labels, for example
`ปีที่เกิดเหตุ (พ.ศ.)`, `ปีการศึกษา (พ.ศ.)`, `เดือน`, and `ไตรมาส`.
Users may override displayed filter text without changing data logic by a Local
AI instruction such as `แก้ไขข้อความบนฟิลเตอร์ year_ เป็นคำว่า ปีงบประมาณ`.

On desktop, the detail area must use a stable 3-column layout: the data table
spans 2 columns and the issue-tracking panel occupies 1 column. On narrower
screens, stack these panels. The tracker panel is mandatory even when it only
states that no structural issue was found.

Bar charts must show the category axis, metric axis, and a visible numeric
scale from zero to the filtered maximum; never rely solely on in-bar lengths.
For trend columns, category labels belong below the X-axis and values belong
above the marks, with horizontal grid lines for comparison.

## Requirement-to-calculation contract

When a user requests a dashboard in natural language, translate each requested
visual into a structured plan before building: `title`, `chart type`,
`dimension`, `metric`, `aggregation`, `formula`, and `data limitations`.
Reject or flag a request when one of these cannot be grounded in source fields.

For a student dataset, interpret common requests consistently:
- total students: documented cohort total; de-duplicate by student ID and
  reporting year when the data represents individual students
- students by faculty/program: pie share or sorted bar using the cohort total
- students by year: annual comparison bar
- dropouts by month/year/faculty: sum the dropout count at the requested grain
- dropout reasons and completion status: proportions with an explicit total
- completion rate: average only when source values are comparable percentages;
  otherwise calculate from a documented numerator and denominator

The dashboard must visibly state limitations when repeated cohort rows, missing
faculty values, mixed date formats, or incompatible percentages prevent an
exact calculation.

Every generated chart and KPI must include an accessible calculation detail:
source field, grouping dimension, formula/aggregation, input-row count, active
filters, and limitations. A user may correct a chart by naming the chart,
source column, formula, and expected value; retain that correction in the spec
revision and validate it before publishing.

Create:
`output/metadata/dashboard-spec.json`

## Local AI dashboard specification

When LM Studio is configured, use the local model to propose the dashboard
specification from the completed dataset profile. This uses the OpenAI-compatible
LM Studio endpoint configured in the root `.env`; it does not call a cloud AI
provider.

From the repository root, run:

```bash
python local-ai/generate_dashboard_spec.py \
  --profile projects/<project>/output/metadata/dataset-profile.json \
  --output projects/<project>/output/metadata/dashboard-spec.local-ai.json
```

Review the generated proposal against the data-quality report and dashboard
rules before using it to create or update `dashboard-spec.json`. The local model
must not override explicit `dashboard-request.md` requirements or cause
unsupported KPIs, charts, or values to be added.

## Data transformation

Create analytical data under:
`output/data/`

Never overwrite raw input.

Document important transformations.

Read and apply `rules/data-rules.md` as a mandatory global skill. In
particular, normalize documented categories, create compatible year/month/
quarter dimensions, display reporting years as Buddhist Era (BE), and preserve
source values for traceability. Apply its calculation rules for every rate,
percentage, share, and comparison.

## Dashboard build

If an existing dashboard implementation exists in the project, update it rather
than replacing it unnecessarily.

If none exists, build a simple responsive local web dashboard that can be opened
from the generated project.

Recommended sections:
1. Header + filters
2. KPI cards
3. Main trend
4. Comparisons
5. Rankings
6. Insights/alerts
7. Detail table where useful

## Interaction and comparison standard

For every dashboard run, read this skill before discovery and follow the full
workflow. A generated dashboard should include the following when its data
supports them:

- A brief, non-looping load animation for chart marks that respects
  `prefers-reduced-motion`.
- Cross-filtering: clicking a chart category applies that category as a filter
  to KPI cards, charts, and detail tables; provide a visible way to clear it.
- Year-over-year KPI comparisons when a fiscal or calendar year dimension is
  available. When one or more years are selected, compare the latest selected
  year with the immediately preceding year using the same remaining filters.
- A green upward indicator only when higher is favorable, and a red downward
  indicator only when lower is unfavorable. Reverse this meaning for metrics
  such as cost where lower is favorable.
- If the prior period is absent or not comparable, show `ไม่มีฐานเปรียบเทียบ`
  rather than calculating or fabricating a percentage.

Record supported interaction and comparison behavior in the dashboard spec and
QA report.

## QA

Validate:
- major KPI values
- identifiers are excluded from metrics and chart axes
- row counts
- nulls
- duplicates
- date ranges
- date parse coverage and normalized date groups
- categories
- high-cardinality categories and unsupported chart plans
- charts
- labels
- layout
- responsiveness
- filters and sorting

Create:
`output/qa/qa-report.json`

Critical numerical mismatch => NOT READY.

## Insights

Create:
`output/reports/insight-report.md`

Every major insight must include evidence and limitations.

## Run manifest

Create:
`output/metadata/run-manifest.json`

Include:
- project
- run_id
- input files
- stages
- status
- warnings
- critical errors
- timestamp

## Completion response

After running, report:
- project
- files analyzed
- dashboard location
- QA status
- important warnings
- how to open the dashboard

Do not claim production-ready if critical QA failed.

## Commands understood

The agent should understand these natural-language commands:

### New
"สร้าง dashboard ใหม่จาก sales.xlsx"

### Run
"รัน dashboard ของ sales"

### Update
"อัปเดต dashboard sales จากไฟล์ใหม่"

### Analyze
"วิเคราะห์ข้อมูล student"

### QA
"ตรวจสอบ dashboard sales"

### Publish preparation
"เตรียม dashboard sales สำหรับ publish"

### List
"แสดง dashboard ทั้งหมด"

When possible, execute the requested command without asking redundant questions.
