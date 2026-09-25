# Local AI with LM Studio

The scripts in this folder use a model running in LM Studio through its local,
OpenAI-compatible server. No cloud API key is required.

## Start once per session

1. In LM Studio, load the selected model and start the server from
   **Developer > Start Server**.
2. Activate the repository environment:

   ```bash
   source .venv/bin/activate
   ```

3. Confirm the connection:

   ```bash
   python local-ai/test_lmstudio.py
   ```

## Configure the model

The root `.env` controls the connection. Copy the template if it does not yet
exist:

```bash
cp local-ai/.env.example .env
```

Set `LMSTUDIO_MODEL` to the exact model identifier shown by LM Studio. The
current server configuration can use, for example:

```dotenv
LMSTUDIO_BASE_URL=http://localhost:1234/v1
LMSTUDIO_MODEL=qwen/qwen3-8b
LMSTUDIO_API_KEY=lm-studio
LMSTUDIO_TIMEOUT=300
```

## Create a dashboard specification

Run the local model after the data profile has been generated:

```bash
python local-ai/generate_dashboard_spec.py \
  --profile projects/CASS/output/metadata/dataset-profile.json \
  --output projects/CASS/output/metadata/dashboard-spec.local-ai.json
```

The `.local-ai.json` output is a proposal. Validate it against the dataset,
data-quality report, and any `dashboard-request.md` before applying it as the
project's `dashboard-spec.json`.