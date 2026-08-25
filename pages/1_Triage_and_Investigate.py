"""Interactive demo: triage synthetic SOC telemetry with Qwen2.5-7B-Instruct,
then escalate the high-risk findings to Nemotron-3-Super-120B for a
correlated investigation report."""

import json
import os

import pandas as pd
import streamlit as st

from src.analysis import WorkMetrics, investigate_events, triage_events
from src.config import LOG_SOURCES, MODELS, NEMOTRON_INVESTIGATE, QWEN_TRIAGE, SAMPLE_LOG_DIR
from src.ui_theme import header, inject_theme, risk_badge

st.set_page_config(page_title="Triage & Investigate — Agentic SOC Demo", page_icon="🔍", layout="wide")
inject_theme()
header(
    "Triage & Investigate",
    "Stage 1 routes every event through Qwen2.5-7B-Instruct. Stage 2 hands what's escalated "
    "to Nemotron-3-Super-120B for a correlated investigation.",
    tags=["Synthetic telemetry", "Two-stage pipeline"],
)

# --- session state -----------------------------------------------------
for key, default in {
    "events": None,
    "triage_results": {},
    "metrics": WorkMetrics(),
    "investigation": None,
    "investigation_ids": [],
}.items():
    st.session_state.setdefault(key, default)


@st.cache_data(show_spinner=False)
def load_sample_events() -> list[dict]:
    events = []
    for source_key, meta in LOG_SOURCES.items():
        path = os.path.join(SAMPLE_LOG_DIR, meta["file"])
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                event["_source"] = source_key
                events.append(event)
    return sorted(events, key=lambda e: e["timestamp"])


# --- data selection ------------------------------------------------------
st.subheader("1 · Telemetry")
st.caption(
    "Bundled synthetic sample logs — identity, firewall/proxy, EDR, and cloud audit — "
    "generated deterministically by `src/log_generator.py`. One coherent attack chain and "
    "one noisy-but-benign scanner are seeded in among routine, uninteresting activity."
)

source_labels = {k: v["label"] for k, v in LOG_SOURCES.items()}
selected_sources = st.multiselect(
    "Log sources to include",
    options=list(source_labels.keys()),
    default=list(source_labels.keys()),
    format_func=lambda k: source_labels[k],
)

all_events = load_sample_events()
events = [e for e in all_events if e["_source"] in selected_sources]
st.session_state.events = events

show_ground_truth = st.toggle(
    "Show ground-truth scenario labels (for demo scoring only — a real SOC wouldn't have these)",
    value=False,
)

preview_cols = ["id", "timestamp", "_source"] + (["scenario"] if show_ground_truth else [])
df_all = pd.DataFrame(events)
display_cols = [c for c in preview_cols if c in df_all.columns]
st.dataframe(df_all[display_cols], use_container_width=True, height=220)
st.caption(f"{len(events)} events loaded across {len(selected_sources)} source(s).")

st.divider()

# --- stage 1: triage -------------------------------------------------------
st.subheader(f"2 · Triage — {QWEN_TRIAGE.label}")
st.caption(QWEN_TRIAGE.role + f" · batches of events sent to `{QWEN_TRIAGE.model_id}`")

run_triage = st.button("Run triage over loaded events", type="primary", disabled=not events)

if run_triage:
    metrics = WorkMetrics()
    with st.spinner(f"Scoring {len(events)} events with {QWEN_TRIAGE.label}..."):
        results = triage_events(events, QWEN_TRIAGE, metrics)
    st.session_state.triage_results = results
    st.session_state.metrics = metrics
    st.session_state.investigation = None

if st.session_state.triage_results:
    results = st.session_state.triage_results
    df = df_all.copy()
    df["risk"] = df["id"].map(lambda i: results.get(i, {}).get("risk", "—"))
    df["category"] = df["id"].map(lambda i: results.get(i, {}).get("category", ""))
    df["reason"] = df["id"].map(lambda i: results.get(i, {}).get("reason", ""))

    risk_order = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
    df = df.sort_values(by="risk", key=lambda s: s.map(lambda r: risk_order.get(r, 4)))

    counts = df["risk"].value_counts()
    kpi_cols = st.columns(4)
    for col, risk in zip(kpi_cols, ["high", "medium", "low", "unknown"]):
        col.metric(risk.capitalize(), int(counts.get(risk, 0)))

    table_cols = ["id", "timestamp", "_source", "risk", "category", "reason"] + (
        ["scenario"] if show_ground_truth else []
    )
    table_cols = [c for c in table_cols if c in df.columns]

    def _fmt_risk(v):
        return risk_badge(v)

    st.markdown("**Triage results** (highest risk first)")
    show_df = df[table_cols].reset_index(drop=True)
    st.dataframe(show_df, use_container_width=True, height=320)

    if show_ground_truth:
        with st.expander("Scoring vs. ground truth"):
            chain = df[df["scenario"] == "scn_phish_to_exfil"]
            noise = df[df["scenario"] == "scn_noisy_scanner"]
            baseline = df[df["scenario"] == "baseline"]
            caught = (chain["risk"] == "high").sum()
            st.markdown(
                f"- **Attack chain events flagged high:** {caught} / {len(chain)}\n"
                f"- **Noisy-scanner events incorrectly flagged high:** {(noise['risk'] == 'high').sum()} / {len(noise)}\n"
                f"- **Baseline events incorrectly flagged high:** {(baseline['risk'] == 'high').sum()} / {len(baseline)}"
            )

    st.divider()

    # --- stage 2: investigation -------------------------------------------
    st.subheader(f"3 · Investigate — {NEMOTRON_INVESTIGATE.label}")
    st.caption(NEMOTRON_INVESTIGATE.role + f" · escalated events sent to `{NEMOTRON_INVESTIGATE.model_id}`")

    high_risk = df[df["risk"] == "high"]
    default_ids = list(high_risk["id"])
    chosen_ids = st.multiselect(
        "Events to hand to the investigation stage (defaults to everything triage marked HIGH)",
        options=list(df["id"]),
        default=default_ids,
        format_func=lambda i: f"{i} — {df.loc[df['id'] == i, '_source'].values[0]}",
    )

    run_investigation = st.button(
        "Escalate to investigation", type="primary", disabled=not chosen_ids
    )
    if run_investigation:
        chosen_events = [e for e in events if e["id"] in chosen_ids]
        with st.spinner(f"Correlating {len(chosen_events)} events with {NEMOTRON_INVESTIGATE.label}..."):
            res = investigate_events(chosen_events, NEMOTRON_INVESTIGATE, st.session_state.metrics)
        st.session_state.investigation = res
        st.session_state.investigation_ids = chosen_ids

    if st.session_state.investigation:
        res = st.session_state.investigation
        if res.error:
            st.error(f"Investigation call failed after {res.latency_s:.2f}s")
            st.code(res.error, language="text")
        else:
            st.success(f"Investigation completed in {res.latency_s:.2f}s")
            if getattr(res, "reasoning", None):
                with st.expander("Model's reasoning trace (shown for transparency, not part of the report)"):
                    st.text(res.reasoning)
            st.markdown(res.text)

    st.divider()
    st.subheader("Work delivered")
    st.caption("Measured as analyst work completed, not tokens processed.")
    m = st.session_state.metrics
    mcols = st.columns(len(m.as_rows()))
    for col, (label, value) in zip(mcols, m.as_rows()):
        col.metric(label, value)
else:
    st.info("Run triage to see per-event risk scoring here.")
