# Agentic SOC Reference Demo

A small reference project showing how a **Cloudera AI Workbench** project calls model
endpoints served by **Cloudera AI Inference Service**, using a security-telemetry
analysis scenario as the worked example.

It runs a two-stage pipeline over synthetic SOC log data:

| Stage | Model | Role |
|---|---|---|
| 1 · Triage | `Qwen2.5-7B-Instruct` | Fast, cheap risk-scoring of every raw event |
| 2 · Investigate | `Nemotron-3-Super-120B` (A12B) | Deep, correlated investigation of what gets escalated |

The framing — route by value, investigate with a governed agent, measure work delivered
rather than tokens processed — borrows from a general "agentic SOC" pattern several
security operations vendors describe publicly. See [`pages/4_About.py`](pages/4_About.py)
for that framing in more detail and an explicit disclaimer: **this project is an
independent reference build and is not modeled on, affiliated with, or endorsed by any
specific security operations vendor.**

## What's in the app

- **Home** (`app.py`) — overview, pipeline explanation, one-click endpoint health check.
- **Triage & Investigate** (`pages/1_Triage_and_Investigate.py`) — load the bundled
  synthetic telemetry, run Stage 1 triage, review scored results, escalate to Stage 2
  investigation, and read the generated report. Tracks "work delivered" (events triaged,
  cases escalated, investigations completed) instead of raw token counts.
- **Traffic Generator** (`pages/2_Traffic_Generator.py`) — fires a configurable number of
  concurrent requests at either or both endpoints (SOC-flavored prompts, not throwaway
  pings) so you can watch latency, throughput, and utilization on the endpoint side.
- **Live Stream** (`pages/3_Live_Stream.py`) — sustains a target events/sec of real triage
  calls against the live endpoint, with a live-updating throughput dashboard. Built to make
  a cost model's EPS breakeven number (see below) tangible against real traffic.
- **About** (`pages/4_About.py`) — the "agentic SOC" framing this demo borrows from, and a
  plain statement of what the project is and isn't.

## Repo layout

```
app.py                          Home page / Streamlit entrypoint
pages/                          Additional Streamlit pages (multipage app)
src/
  config.py                     Endpoint URLs, model IDs, auth token loading
  llm_client.py                 OpenAI-compatible client wrapper + JSON extraction
  log_generator.py              Deterministic synthetic SOC telemetry generator
  analysis.py                   Triage / investigation orchestration + prompts
  ui_theme.py                   Shared Streamlit styling helpers
data/sample_logs/               Bundled synthetic sample logs (regenerable)
scripts/generate_sample_data.py Regenerates data/sample_logs/ from log_generator.py
cdsw-build.sh                   Build script Cloudera AI Workbench runs on start
requirements.txt
```

## Model endpoints

Configured in [`src/config.py`](src/config.py) against two endpoints already deployed on
Cloudera AI Inference Service (OpenAI-compatible `/v1/chat/completions` API):

- `Qwen/Qwen2.5-7B-Instruct` — fast triage
- `nvidia/nemotron-3-super-120b-a12b` — deep investigation

To point this at different endpoints or models, edit the `ModelConfig` entries at the top
of `src/config.py` — everything else in the app reads from that registry.

## Auth

Inside a Cloudera AI Workbench Session, Application, or Job, the platform mounts a
short-lived workload JWT at `/tmp/jwt` and keeps it refreshed automatically. This app reads
that token fresh on every request (`src/config.get_access_token`) and uses it as the bearer
token against both endpoints — no API key management needed when running in-platform.

For local development outside of Cloudera AI Workbench, export a valid token instead:

```bash
export CDP_TOKEN=<your Cloudera AI token>
```

## Running locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export CDP_TOKEN=<your Cloudera AI token>   # only needed outside CML
streamlit run app.py
```

## Deploying on Cloudera AI Workbench

1. Create a new Project from this repository (or upload the files directly).
2. **Session (quick test):** launch a Python session, run `pip install -r requirements.txt`,
   then `streamlit run app.py --server.port $CDSW_APP_PORT --server.address 127.0.0.1` from
   the session terminal, and open it via the session's application preview.
3. **Application (persistent demo):** in the Project, go to **Applications → New
   Application**, and set:
   - **Subdomain:** anything, e.g. `agentic-soc`
   - **Script:** `launch_app.py` — CML Applications run a Python script rather than an
     arbitrary shell command, so this small script just launches
     `streamlit run app.py` as a subprocess on the port CML assigns it.
   - **Build:** `cdsw-build.sh` is picked up automatically to install dependencies.
   - **Resource profile:** minimal CPU/memory is enough — this app only makes outbound
     calls to the inference endpoints, it doesn't run any models itself.
4. No environment variables are required for auth (see **Auth** above) — the Application's
   own workload JWT is used automatically.

## Regenerating sample data

The bundled logs in `data/sample_logs/` are generated deterministically (seeded) from
`src/log_generator.py`, which seeds one coherent multi-stage attack chain (phishing →
encoded PowerShell → beacon/exfil → new AWS access key → public S3 bucket) and one
red-herring noisy scanner among routine baseline activity. To regenerate after editing the
generator:

```bash
python scripts/generate_sample_data.py
```

## Evaluating the triage agent

`scripts/run_evals.py` is a deterministic eval: it runs the real triage pipeline against the
bundled dataset and scores the results against the dataset's ground-truth `scenario` labels —
does it actually catch the seeded attack chain, and does it avoid crying wolf on the
noisy-scanner red herring and plain baseline noise? Same dataset (seed=42) and
`temperature=0.0` every run, so results are comparable across runs — rerun it after any prompt
or model change to see whether it actually helped, not just whether it "seems better."

```bash
python scripts/run_evals.py            # print a scorecard
python scripts/run_evals.py --save     # also write it to evals/results/*.json
```

Scored metrics, against thresholds defined at the top of the script:

| Metric | What it checks |
|---|---|
| Attack chain caught as HIGH | Recall on the 7 real attack-chain events, strict bar |
| Attack chain caught as MEDIUM+ | Recall on the same events, looser bar (at least flagged for a second look) |
| Noisy scanner wrongly flagged HIGH | False-positive rate on the benign-but-noisy red herring |
| Baseline noise wrongly flagged HIGH | False-positive rate on routine, uninteresting activity |
| Valid, parseable triage result | How often the model returns strict, parseable JSON |

Needs the same auth as the rest of the app (Cloudera AI Workbench Session/Application/Job, or
`CDP_TOKEN` locally).

## Disclaimer

This project borrows the general shape of the "agentic SOC" pattern described publicly by
several security operations vendors, purely as scenario framing for the demo. It is an
independent reference build created to demonstrate Cloudera AI Workbench and Cloudera AI
Inference Service, is not modeled on, affiliated with, or endorsed by any specific security
operations vendor, and does not use, store, or connect to any real vendor product, data, or
customer information. All telemetry in this repo is synthetic.
