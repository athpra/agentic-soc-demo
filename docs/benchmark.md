# Cross-platform benchmark

`pages/5_Benchmark.py` compares `Qwen2.5-7B-Instruct` across two platforms that both serve the
identical model weights, so latency/throughput/quality differences are attributable to the
serving stack, not the model:

| Platform | Model config | Auth / setup |
|---|---|---|
| Cloudera AI Inference | `src.config.QWEN_TRIAGE` | Workload JWT (automatic, same as the rest of the app) |
| Fireworks AI | `src.config.QWEN_FIREWORKS` | `FIREWORKS_API_KEY` + `FIREWORKS_MODEL_ID` env vars — see below |

**Fireworks needs an on-demand deployment, not just an API key.** `Qwen2.5-7B-Instruct` isn't
available serverless on Fireworks (confirmed on their model page: "Serverless: Not supported")
— it has to be deployed to a dedicated GPU first (an H100 80GB, billed hourly while it's
running — tear it down after benchmarking). Once deployed, Fireworks' console shows the exact
model string to use, shaped like `accounts/<your-account>/deployments/<deployment-id>` — set
that as `FIREWORKS_MODEL_ID` (the base URL stays `https://api.fireworks.ai/inference/v1`
either way). That model ID is deployment-specific and meant to be temporary, so it's read from
an env var rather than hardcoded in `src/config.py`, unlike everything else in this project.

Cloudera's own Qwen endpoint runs on a confirmed 1× A10G GPU — check your own endpoint's
resource profile in Cloudera AI Registry / Model Serving before trusting a
Fireworks-vs-Cloudera latency comparison in a different environment, since the A10G-vs-H100
difference alone (bandwidth vs. compute-bound regimes) can account for part of any gap.

Databricks isn't included at all — `Qwen2.5-7B-Instruct` isn't on their pay-per-token
Foundation Model API list either (only newer Qwen3-series models are, as of when this was
checked), and that path needs a self-deployed Provisioned Throughput endpoint. The config in
`src/config.py` (`ModelConfig`, `BENCHMARK_MODELS`, `get_api_key()`, `is_configured()`) is
written so adding a third provider later, Databricks or otherwise, is just one more
`ModelConfig` entry plus the relevant env var(s).

The page skips (and clearly marks, naming exactly which env var is missing) any provider
that isn't fully configured, rather than failing when you click run.
