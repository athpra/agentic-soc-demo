"""Traffic generator: fires a configurable volume of concurrent requests at
one or both Cloudera AI Inference Service endpoints, so you can watch
utilization show up on the endpoint / workspace side while exercising the
same client code as the analysis demo."""

import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st

from src.config import LOG_SOURCES, MODELS, SAMPLE_LOG_DIR
from src.llm_client import chat
from src.ui_theme import header, inject_theme

st.set_page_config(page_title="Traffic Generator — Agentic SOC Demo", page_icon="📈", layout="wide")
inject_theme()
header(
    "Traffic Generator",
    "Send configurable, concurrent request volume at Cloudera AI Inference Service endpoints.",
    tags=["Load generation", "Endpoint exercise"],
)

st.markdown(
    "Each request sends one synthetic SOC event through a short triage-style prompt, "
    "so traffic looks like the real workload the pipeline generates rather than throwaway "
    "'hello world' calls — useful for demoing utilization, latency, and autoscaling behavior "
    "on the endpoint."
)


@st.cache_data(show_spinner=False)
def load_sample_events() -> list[dict]:
    events = []
    for meta in LOG_SOURCES.values():
        path = os.path.join(SAMPLE_LOG_DIR, meta["file"])
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
    return events


SAMPLE_EVENTS = load_sample_events()

PROMPT_TEMPLATE = (
    "In one short sentence, assess the risk (low/medium/high) of this security "
    "event and say why:\n{event}"
)


def build_prompt() -> str:
    event = dict(random.choice(SAMPLE_EVENTS))
    event.pop("scenario", None)
    return PROMPT_TEMPLATE.format(event=json.dumps(event))


# --- controls --------------------------------------------------------------
st.subheader("Configuration")
c1, c2, c3 = st.columns(3)
with c1:
    target_keys = st.multiselect(
        "Target endpoint(s)",
        options=list(MODELS.keys()),
        default=list(MODELS.keys()),
        format_func=lambda k: MODELS[k].label,
    )
with c2:
    n_requests = st.slider("Total requests", min_value=5, max_value=300, value=40, step=5)
with c3:
    concurrency = st.slider("Concurrency (parallel workers)", min_value=1, max_value=25, value=8)

max_tokens = st.slider("Max tokens per response", min_value=16, max_value=256, value=64, step=16)

run = st.button("Generate traffic", type="primary", disabled=not target_keys)

if run:
    targets = [MODELS[k] for k in target_keys]
    jobs = [targets[i % len(targets)] for i in range(n_requests)]

    progress = st.progress(0.0, text=f"0 / {n_requests} requests completed")
    rows = []
    start_wall = time.perf_counter()

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(chat, model_cfg, [{"role": "user", "content": build_prompt()}], max_tokens=max_tokens): (i, model_cfg)
            for i, model_cfg in enumerate(jobs)
        }
        completed = 0
        for future in as_completed(futures):
            i, model_cfg = futures[future]
            res = future.result()
            rows.append(
                {
                    "seq": i,
                    "model": model_cfg.label,
                    "latency_s": round(res.latency_s, 3),
                    "success": res.error is None,
                    "completion_tokens": res.completion_tokens,
                    "error": res.error,
                }
            )
            completed += 1
            progress.progress(completed / n_requests, text=f"{completed} / {n_requests} requests completed")

    wall_time = time.perf_counter() - start_wall
    progress.empty()

    df = pd.DataFrame(rows).sort_values("seq").reset_index(drop=True)
    st.session_state["traffic_df"] = df
    st.session_state["traffic_wall_time"] = wall_time

if "traffic_df" in st.session_state:
    df = st.session_state["traffic_df"]
    wall_time = st.session_state["traffic_wall_time"]

    st.divider()
    st.subheader("Results")

    total = len(df)
    success = int(df["success"].sum())
    throughput = total / wall_time if wall_time > 0 else 0.0

    kpi = st.columns(5)
    kpi[0].metric("Requests sent", total)
    kpi[1].metric("Success rate", f"{success / total * 100:.0f}%")
    kpi[2].metric("Wall time", f"{wall_time:.1f}s")
    kpi[3].metric("Throughput", f"{throughput:.2f} req/s")
    kpi[4].metric("Mean latency", f"{df['latency_s'].mean():.2f}s")

    st.markdown("**Latency by model**")
    latency_summary = (
        df.groupby("model")["latency_s"]
        .agg(mean="mean", p50="median", p95=lambda s: s.quantile(0.95), max="max")
        .round(2)
    )
    st.dataframe(latency_summary, use_container_width=True)

    try:
        import plotly.express as px

        fig = px.histogram(
            df, x="latency_s", color="model", nbins=30, barmode="overlay",
            labels={"latency_s": "Latency (s)"}, opacity=0.75,
        )
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)

        fig2 = px.scatter(
            df, x="seq", y="latency_s", color="model",
            labels={"seq": "Request order", "latency_s": "Latency (s)"},
        )
        fig2.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig2, use_container_width=True)
    except ImportError:
        st.bar_chart(df.set_index("seq")["latency_s"])

    failures = df[~df["success"]]
    if len(failures):
        with st.expander(f"{len(failures)} failed request(s)"):
            st.dataframe(failures[["seq", "model", "error"]], use_container_width=True)
else:
    st.info("Configure the run above and click **Generate traffic** to start.")
