# Data Rules

- Raw input is read-only.
- Preserve source lineage.
- Do not invent missing data.
- Do not silently delete records.
- Document normalization, joins, filtering, and calculated fields.
- Keep project datasets isolated.

## Global data preparation skill

- Infer date fields from values and headers. Preserve the original source value
	and record the parsing rule and any invalid values in the quality report.
- Normalize equivalent category labels only with a documented mapping; retain
	the source label in analytical data.
- Create standard analytical date dimensions when a valid date, calendar year,
	or fiscal year is available: `year_be`, `year_ce`, `month`, `month_label`,
	`quarter`, and `fiscal_year_be` when it can be determined from the source.
- Interpret Thai Buddhist Era years as CE plus 543. Convert CE to BE by adding
	543. Store and display reporting years as BE; retain `year_ce` only for
	traceability and date parsing.
- Group dates consistently: calendar quarters are Jan-Mar, Apr-Jun, Jul-Sep,
	and Oct-Dec. Do not infer a different fiscal-year start without an explicit
	source field, configuration, or request.
- Use the same normalized dimension values in every filter, chart, KPI, and
	detail table so cross-filtering is reliable.

## Global calculation skill

- Define each calculated metric with formula, source fields, aggregation,
	period, and denominator in dashboard requirements and QA output.
- Before summing a numeric field, detect repeated values across rows and assess
	whether it is a repeated cohort/reference total. Never sum it unless the
	grouping key and grain prove every value is additive. For entity counts,
	prefer `COUNT(DISTINCT stable ID)` and report missing IDs.
- Normalize percentage inputs before aggregation: `0.85` and `85%` both mean
	`85`. Average comparable rates; never sum rate or percentage rows.
- Every KPI and chart must expose calculation provenance on hover or a visible
	details control: source field, dimension, aggregation/formula, rows used,
	active filters, and material limitations.
- Calculate rates and percentages as `(numerator / denominator) * 100` only
	when the denominator is non-zero and comparable. Show `ไม่มีฐานเปรียบเทียบ`
	for a missing or zero denominator.
- Calculate shares as `(category value / filtered total) * 100`; the filtered
	total must use the same period and active filters.
- Calculate absolute change as `current - prior` and percent change as
	`((current - prior) / abs(prior)) * 100` only when a prior period exists.
- Do not mix calendar and fiscal-year periods in a comparison. Compare the
	latest selected period with the immediately preceding equivalent period.

## Correction instruction skill

Treat a user correction as a structured override, not a vague preference. The
instruction may state: chart title, source column, dimension, metric, formula,
expected value, and reason. Store the instruction and resulting spec revision.
On build, validate the expected value when supplied; if it differs, show a QA
warning and do not claim the chart is correct.
