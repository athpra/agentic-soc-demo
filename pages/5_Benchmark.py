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
    "(an H100) rather than shared capacity. **The GPU backing this project's Cloudera AI "
    "Inference endpoint hasn't been confirmed** — an earlier version of this page assumed "
    "A10G, carried over from a different Cloudera demo environment, which was never actually "
    "verified for *this* one. If Cloudera's side turns out to be on lighter hardware than the "
    "on-demand H100, a Fireworks latency win is partly \"bigger GPU,\" not purely \"better "
    "serving stack\" — check your endpoint's resource profile in Cloudera AI Registry / Model "
    "Serving to know for sure before reading too much into a gap either way. Databricks isn't "
    "included at all: Qwen2.5-7B-Instruct isn't on their pay-per-token Foundation Model API "
    "list either, and that path needs a self-deployed Provisioned Throughput endpoint."
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
c1, c2, c3 = st.columns(3)
with c1:
    n_requests = st.slider("Requests per provider", min_value=5, max_value=200, value=30, step=5)
with c2:
    concurrency = st.slider("Concurrency", min_value=1, max_value=25, value=6)
with c3:
    max_tokens = st.slider(
        "Max tokens per response", min_value=16, max_value=512, value=128, step=16,
        help="Higher gives token-throughput numbers more room to reflect real generation speed "
             "instead of being dominated by prompt processing on a very short response.",
    )

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
            rows = run_latency_benchmark(model_cfg, n_requests, concurrency, max_tokens=max_tokens)
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

    st.markdown("**Inference throughput (output tokens/sec)**")
    have_tokens = any(s["n_with_token_usage"] > 0 for s in summaries.values())
    if have_tokens:
        tok_df = pd.DataFrame(summaries).T[["n_with_token_usage", "output_tokens_per_sec_aggregate", "output_tokens_per_sec_per_request"]]
        tok_df.columns = ["Requests with usage data", "Aggregate tok/s (whole run)", "Mean tok/s (per request)"]
        st.dataframe(
            tok_df.style.format(
                {"Aggregate tok/s (whole run)": "{:.1f}", "Mean tok/s (per request)": "{:.1f}"},
                na_rep="—",
            ),
            use_container_width=True,
        )
        tok_chart_df = pd.DataFrame({
            label: {"tok/s (aggregate)": s["output_tokens_per_sec_aggregate"]}
            for label, s in summaries.items()
        }).T
        st.bar_chart(tok_chart_df, x_label="Provider", y_label="Output tokens/sec")
        st.caption(
            "Both numbers are derived from real completion_tokens usage the endpoint reported, "
            "not estimated. **Aggregate** = total output tokens across the whole run ÷ wall "
            "time — real system throughput at this concurrency. **Per request** = each "
            "response's own tokens ÷ its own latency, averaged — single-stream generation "
            "speed. Both include prompt-processing time (this app calls the non-streaming API, "
            "so there's no separate time-to-first-token to exclude) — an honest ceiling on "
            "generation speed, not a pure decode-only rate."
        )
    else:
        st.info(
            "Neither configured endpoint returned token usage on these responses, so "
            "tokens/sec can't be computed for this run — only requests/sec above."
        )

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
