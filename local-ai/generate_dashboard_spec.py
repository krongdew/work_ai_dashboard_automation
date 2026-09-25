from __future__ import annotations
import argparse, json
from pathlib import Path
from lmstudio_client import generate_json
SCHEMA={"type":"object","additionalProperties":False,"properties":{
"dashboard_title":{"type":"string"},"purpose":{"type":"string"},"audience":{"type":"string"},
"kpis":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"name":{"type":"string"},"metric":{"type":"string"},"reason":{"type":"string"}},"required":["name","metric","reason"]}},
"filters":{"type":"array","items":{"type":"string"}},
"charts":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"title":{"type":"string"},"type":{"type":"string"},"dimension":{"type":"string"},"metric":{"type":"string"},"reason":{"type":"string"}},"required":["title","type","dimension","metric","reason"]}},
"insight_questions":{"type":"array","items":{"type":"string"}}},"required":["dashboard_title","purpose","audience","kpis","filters","charts","insight_questions"]}
SYSTEM="""You are the local AI analyst inside a production dashboard factory. Convert a DATA PROFILE into a practical dashboard specification. Use only fields and statistics present in the profile. Do not invent facts or measurements. Do not calculate raw values that are not supplied. Prefer meaningful KPIs, appropriate chart types, useful filters, and an institutional/academic management style. Return only valid JSON matching the schema."""
def main():
 p=argparse.ArgumentParser(); p.add_argument('--profile',required=True); p.add_argument('--output',required=True); a=p.parse_args()
 profile=json.loads(Path(a.profile).read_text(encoding='utf-8'))
 spec=generate_json(SYSTEM,"Create a dashboard specification from this data profile:\n\n"+json.dumps(profile,ensure_ascii=False,indent=2),SCHEMA)
 out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8'); print(f'✓ Dashboard spec written to {out}')
if __name__=='__main__': main()
