# Local AI with LM Studio

The Factory UI can switch between a model running in LM Studio and Groq using
`AI_PROVIDER` in `data_factory/.env`. This folder contains the LM Studio,
OpenAI-compatible client.

## Start once per session

1. In LM Studio, load the selected model and start the server from
   **Developer > Start Server**.
2. Create `data_factory/.env` from `local-ai/.env.example`. This is the exact
   `.env` location loaded by the scripts.
3. Activate the data-factory environment and install the local client:

   ```powershell
   Set-Location D:\pactices\MULA_DataLink_php\data_factory
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r local-ai\requirements.txt
   ```

4. Confirm the connection:

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
LMSTUDIO_MODEL=Qwen/Qwen3-8B-GGUF
LMSTUDIO_API_KEY=lm-studio
LMSTUDIO_TIMEOUT=420
LMSTUDIO_MAX_TOKENS=1024
```

Set `AI_PROVIDER=local` to use this client. Set `AI_PROVIDER=groq` to return
Factory UI planning to Groq; both providers' settings may remain in the same
`.env` file. `LMSTUDIO_TIMEOUT` is the maximum wait for one non-streaming
completion. Keep it at least `420` seconds for a 1,024-token response on a
model generating about 3.5 tokens per second; increase it for slower hardware
or reduce `LMSTUDIO_MAX_TOKENS` only when the model consistently returns
complete JSON within the lower limit. If a response ends with an unterminated
JSON string, set `LMSTUDIO_MAX_TOKENS=2048` and `LMSTUDIO_TIMEOUT=720`, then
restart the Factory UI.

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