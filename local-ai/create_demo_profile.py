from pathlib import Path
import json
profile = {
  "dataset":{"name":"student_satisfaction_demo","rows":1250,"columns":7},
  "dimensions":[{"name":"faculty","type":"categorical","unique":8},{"name":"year_level","type":"categorical","unique":4},{"name":"semester","type":"categorical","unique":2}],
  "measures":[{"name":"satisfaction_score","type":"numeric","min":1.0,"max":5.0,"mean":4.18,"median":4.3},{"name":"response_count","type":"numeric","min":1,"max":380,"mean":156.25}],
  "quality":{"missing_cells":12,"duplicate_rows":4},
  "notes":["Synthetic demo data.","Use the profile to recommend a management dashboard."]
}
p = Path(__file__).with_name("demo_profile.json")
p.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding="utf-8")
print(f"Created {p}")
