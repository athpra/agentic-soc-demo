"""Benchmark: compare the same model family (Qwen2.5-7B-Instruct) across
Cloudera AI Inference and Fireworks AI -- same weights, different serving
stack, so any latency/throughput/quality gap is about the platform, not
the model.

Latency/throughput uses src/benchmark.py; quality reuses src/evals.py's
ground-truth scoring, generalized to accept any provider's ModelConfig.
"""

import os
import time

import pandas as pd
import streamlit as st

from src.benchmark import run_latency_benchmark, summarize_latencies
from src.config import BENCHMARK_MODELS, is_configured
from src.evals import METRIC_LABELS, THRESHOLDS, run_eval, verdict
from src.ui_theme import header, inject_theme

st.set_page_config(page_title="Benchmark — Agentic SOC Demo", page_icon="⚡", layout="wide")
inject_theme()
header(
    "Benchmark",
    "Same model, different platforms — compare Qwen2.5-7B-Instruct across Cloudera AI "
    "Inference and Fireworks AI.",
    tags=["Cross-platform", "Same model family"],
)

st.markdown(
    "Both providers here run the identical model weights, so a difference in latency, "
    "throughput, or triage quality is telling you something about the *serving stack*, not "
    "about which model is smarter — with one asterisk: Qwen2.5-7B-Instruct isn't available "
    "serverless on Fireworks, so that leg runs on a dedicated on-demand GPU deployment "
    "(an H100) rather than shared capacity. Cloudera's endpoint is also dedicated (a single "
    "A10G), so this is a fair dedicated-vs-dedicated comparison — but an H100 is meaningfully "
    "more powerful hardware than an A10G, so a Fireworks win on latency is partly \"bigger "
    "GPU,\" not purely \"better serving stack.\" Worth saying out loud wherever these results "
    "get shown. Databricks isn't included at all: Qwen2.5-7B-Instruct isn't on their "
    "pay-per-token Foundation Model API list either, and that path needs a self-deployed "
    "Provisioned Throughput endpoint."
)

st.subheader("Providers")
cols = st.columns(len(BENCHMARK_MODELS))
configured = {}
for col, model_cfg in zip(cols, BENCHMARK_MODELS.values()):
    ok = is_configured(model_cfg)
    configured[model_cfg.key] = ok
    with col:
        st.markdown(f"**{model_cfg.label}**")
        if ok:
            st.success("Configured")
        else:
            missing = [v for v in (model_cfg.api_key_env, model_cfg.model_id_env) if v and not os.environ.get(v)]
            st.warning(f"Not configured — export {', '.join(f'`{m}`' for m in missing)} to enable")

available_models = [m for m in BENCHMARK_MODELS.values() if configured[m.key]]

if not available_models:
    st.info("No providers configured yet. At minimum, Cloudera should work automatically inside a CML workload.")
    st.stop()

st.divider()

# --- latency / throughput -------------------------------------------------
st.subheader("Latency & throughput")
c1, c2 = st.columns(2)
with c1:
    n_requests = st.slider("Requests per provider", min_value=5, max_value=200, value=30, step=5)
with c2:
    concurrency = st.slider("Concurrency", min_value=1, max_value=25, value=6)

st.caption(
    "Runs one provider's full load, then the next — sequential across providers so they "
    "don't contend with each other, which would make the comparison unfair."
)

run_latency = st.button("Run latency & throughput benchmark", type="primary")

if run_latency:
    all_summaries = {}
    all_rows = {}
    for model_cfg in available_models:
        with st.spinner(f"Benchmarking {model_cfg.label}: {n_requests} requests, concurrency {concurrency}..."):
            t0 = time.perf_counter()
            rows = run_latency_benchmark(model_cfg, n_requests, concurrency)
            wall = time.perf_counter() - t0
        all_rows[model_cfg.label] = rows
        all_summaries[model_cfg.label] = summarize_latencies(rows, wall)
    st.session_state["benchmark_summaries"] = all_summaries
    st.session_state["benchmark_rows"] = all_rows

if "benchmark_summaries" in st.session_state:
    summaries = st.session_state["benchmark_summaries"]

    kpi_df = pd.DataFrame(summaries).T
    kpi_df = kpi_df[["success_rate", "mean_latency_s", "p50_latency_s", "p95_latency_s", "throughput_rps"]]
    kpi_df.columns = ["Success rate", "Mean latency (s)", "p50 latency (s)", "p95 latency (s)", "Throughput (req/s)"]
    st.dataframe(
        kpi_df.style.format(
            {
                "Success rate": "{:.0%}",
                "Mean latency (s)": "{:.2f}",
                "p50 latency (s)": "{:.2f}",
                "p95 latency (s)": "{:.2f}",
                "Throughput (req/s)": "{:.2f}",
            },
            na_rep="—",  # a provider with 0 successes has no latency to show -- not "nan"
        ),
        use_container_width=True,
    )

    chart_df = pd.DataFrame({
        label: {"p50": s["p50_latency_s"], "p95": s["p95_latency_s"]}
        for label, s in summaries.items()
    }).T
    st.bar_chart(chart_df, x_label="Provider", y_label="Latency (s)")

    all_rows = st.session_state.get("benchmark_rows", {})
    failure_frames = []
    for label, rows in all_rows.items():
        for r in rows:
            if not r["success"]:
                failure_frames.append({"Provider": label, "seq": r["seq"], "error": r["error"]})
    if failure_frames:
        with st.expander(f"⚠️ {len(failure_frames)} failed request(s) — click to see why"):
            st.dataframe(pd.DataFrame(failure_frames), use_container_width=True, hide_index=True)
            st.caption(
                "If every request for a provider failed with the same auth-shaped error, that's "
                "almost always a missing or invalid API key for that provider, not a real "
                "performance problem — check the 'Providers' status row above."
            )

st.divider()

# --- quality / reliability --------------------------------------------------
st.subheader("Triage quality")
st.caption(
    "Same ground-truth eval as the Evals page (src/evals.py), run once per configured "
    "provider — does the same model, on a different serving stack, triage the same way?"
)

run_quality = st.button("Run quality eval on each provider", type="primary")

if run_quality:
    all_scores = {}
    for model_cfg in available_models:
        with st.spinner(f"Running the triage eval against {model_cfg.label}..."):
            scores, _, _ = run_eval(model_cfg)
        all_scores[model_cfg.label] = scores
    st.session_state["benchmark_quality"] = all_scores

if "benchmark_quality" in st.session_state:
    all_scores = st.session_state["benchmark_quality"]
    rows = []
    for key in THRESHOLDS:
        row = {"Metric": METRIC_LABELS[key]}
        for label, scores in all_scores.items():
            actual = scores[key]
            ok = verdict(key, actual)
            actual_str = "n/a" if actual != actual else f"{actual:.0%}"
            row[label] = f"{actual_str} {'✅' if ok else '⚠️'}"
        rows.append(row)
    st.dataframe(pd.DataFrame(rows).set_index("Metric"), use_container_width=True)
