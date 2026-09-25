# QA Rules

Critical KPI mismatches block release.

Validate:
- source vs dashboard KPI values
- identifier fields are never aggregated, charted, or used as filters
- row counts
- nulls
- duplicates
- date coverage
- date parse coverage; show unparsed values as a warning requiring review
- category cardinality; do not render a chart with more than 20 raw groups
- chart rendering
- chart axis labels, data labels, and calculation-details control
- filters
- toggle-to-clear chart filters and the table's `ต้องตรวจสอบ` data-quality view
- layout
- responsiveness

Critical failure => NOT READY.

Warnings must be visible in the QA report and dashboard when the available data
cannot support a reliable grouping, period, or comparison. Do not substitute an
unrelated numeric field just to complete a chart.
