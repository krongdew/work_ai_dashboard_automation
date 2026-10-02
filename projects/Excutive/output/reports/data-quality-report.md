# Data Quality Report: Executive

## Input coverage
- `1.Current Students _ Admissions .xlsx`: 824 non-header rows across 2 worksheets.
- `2.Current Graduate Student.xlsx`: 157 non-header rows across 4 worksheets.
- `3.Mobility Overview.xlsx`: 145 non-header rows across 2 worksheets.
- `4.Research Publication Performance.xlsx`: 360 non-header rows across 4 worksheets.
- `5.Workforce _ Personnel Overview .xlsx`: 5103 non-header rows across 8 worksheets.
- `การลงทุน_ฐานใหม่.xlsx`: 736 non-header rows across 7 worksheets.

## Findings

- Direct identifiers and contact details were excluded from all output/data files and dashboard payloads.
- Personnel history contains `#REF!` in the work-line source field for some records; these remain as source limitations.
- Mobility duration is a free-text field and is not aggregated.
- Research input provides publication records, a researcher roster, and publication targets; it does not provide researcher CV/expertise fields or research-funding transactions.
- Education input provides current enrollment plus admissions/graduate records but no harmonized annual student-count snapshots for a full trend.
- Domains have different time coverage, so the dashboard does not create cross-domain or universal YoY comparisons.
