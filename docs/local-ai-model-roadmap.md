# Local AI Model Roadmap

## Purpose

Dashboard Factory uses a two-pass AI workflow: an AI analysis bundle followed
by a dashboard-specification pass. This document defines how to evaluate a
larger Local model without weakening the privacy boundary or changing the
verified Python calculation path.

## Current Baseline

The default Local configuration uses Qwen3 8B GGUF Q4_K_M through LM Studio.
It is suitable for private metadata planning, but output throughput and JSON
reliability depend on available CPU, GPU, RAM, VRAM, context length, and the
LM Studio chat template. It cannot be assumed to match a large cloud model's
reasoning quality.

## Upgrade Candidates

Evaluate instruction-tuned models with reliable OpenAI-compatible structured
JSON support. Start with a larger Qwen Instruct model that fits the available
VRAM or shared RAM; a 14B class model is a practical first comparison. Use a
32B class model only after confirming memory headroom and acceptable output
throughput. Larger models improve only the AI interpretation and design steps;
all calculations, validation, and publication checks remain local Python work.

Do not select a model solely by parameter count. A smaller model that reliably
returns strict JSON is preferable to a larger model that emits reasoning text
or repeatedly times out.

## Acceptance Benchmark

Before changing `LMSTUDIO_MODEL` for users, test the candidate with the same
anonymized project profile and instruction used by the current model:

1. Confirm `python local-ai/test_lmstudio.py` returns a JSON response.
2. Run Factory suggestion twice. The first run must complete the two AI passes;
   the second must reuse `output/metadata/ai-analysis-plan.json`.
3. Confirm semantic interpretations, normalization proposals, and requested
   aggregates contain only profile fields and bounded filters.
4. Build the dashboard and confirm QA reports no fabricated field, formula, or
   calculation result.
5. Record first-run duration, cached-run duration, peak RAM/VRAM, JSON failure
   count, and QA outcome in the project evaluation notes.

## Deployment Rules

Keep `AI_PROVIDER=local`, `LMSTUDIO_MODEL`, `LMSTUDIO_TIMEOUT`, and
`LMSTUDIO_MAX_TOKENS` in `data_factory/.env`; do not commit this file or model
server credentials. Load one evaluation model at a time, reserve enough context
for the structured schemas, and restart the Factory after changing provider
configuration. Roll back by restoring the prior model name and restarting the
LM Studio server and Factory.

## Future Work

- Add a benchmark command that records the acceptance metrics automatically.
- Store model name and duration with each AI analysis artifact.
- Add optional model routing only after each route passes the same grounding and
  QA checks; provider choice must never bypass Python validation.