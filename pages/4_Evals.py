"""Evals: run the deterministic triage eval from the app and visualize the
scorecard, including a trend across any previously saved runs.

Same scoring logic as scripts/run_evals.py -- both go through src/evals.py,
so a run here and a run from the CLI always agree.
"""

import glob
import json
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from src.config import QWEN_TRIAGE
from src.evals import METRIC_LABELS, THRESHOLDS, run_eval, verdict
from src.ui_theme import header, inject_theme

st.set_page_config(page_title="Evals — Agentic SOC Demo", page_icon="🧪", layout="wide")
inject_theme()
header(
    "Evals",
    f"Score {QWEN_TRIAGE.label}'s real triage output against the dataset's ground-truth labels.",
    tags=["Deterministic", "Same dataset every run"],
)

st.markdown(
    "Runs the exact same triage pipeline as the Triage & Investigate page, over the same "
    "seeded dataset, at `temperature=0.0` — so scores are comparable run to run. Rerun this "
    "after any prompt or model change to see whether it actually helped, not just whether it "
    "*seems* better. Same logic as `scripts/run_evals.py`, for scripting or CI use outside the app."
)

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals", "results")

run = st.button("Run eval", type="primary")

if run:
    with st.spinner(f"Triaging the full dataset against {QWEN_TRIAGE.label}..."):
        scores, metrics, by_scenario = run_eval()
    st.session_state["eval_scores"] = scores
    st.session_state["eval_metrics"] = metrics
    st.session_state["eval_by_scenario"] = by_scenario

if "eval_scores" in st.session_state:
    scores = st.session_state["eval_scores"]
    metrics = st.session_state["eval_metrics"]
    by_scenario = st.session_state["eval_by_scenario"]

    st.subheader("Scorecard")
    cols = st.columns(len(THRESHOLDS))
    passed = 0
    for col, key in zip(cols, THRESHOLDS.keys()):
        target, direction = THRESHOLDS[key]
        actual = scores[key]
        ok = verdict(key, actual)
        passed += int(ok)
        actual_str = "n/a" if actual != actual else f"{actual:.0%}"
        cmp_sym = "≥" if direction == "higher_is_better" else "≤"
        col.metric(METRIC_LABELS[key], actual_str)
        col.markdown(f"target {cmp_sym} {target:.0%}")
        col.markdown("✅ **Pass**" if ok else "⚠️ **Below target**")

    st.caption(f"{passed}/{len(THRESHOLDS)} metrics within target.")

    st.subheader("Actual vs. target")
    chart_df = pd.DataFrame(
        {
            "Metric": [METRIC_LABELS[k] for k in THRESHOLDS],
            "Actual": [scores[k] for k in THRESHOLDS],
            "Target": [THRESHOLDS[k][0] for k in THRESHOLDS],
        }
    ).set_index("Metric")
    st.bar_chart(chart_df, x_label="Score", y_label="Metric", horizontal=True)

    st.caption(
        f"Sample sizes: attack chain={len(by_scenario.get('scn_phish_to_exfil', []))}, "
        f"noisy scanner={len(by_scenario.get('scn_noisy_scanner', []))}, "
        f"baseline={len(by_scenario.get('baseline', []))} · "
        f"{metrics.triage_calls} triage calls, {metrics.errors} errors, "
        f"avg latency {(metrics.triage_latency_s / metrics.triage_calls):.2f}s"
        if metrics.triage_calls else ""
    )

    if st.button("💾 Save this scorecard"):
        os.makedirs(RESULTS_DIR, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(RESULTS_DIR, f"triage_eval_{stamp}.json")
        with open(path, "w") as f:
            json.dump(
                {
                    "timestamp": stamp,
                    "model": QWEN_TRIAGE.model_id,
                    "scores": scores,
                    "thresholds": {k: v[0] for k, v in THRESHOLDS.items()},
                    "triage_calls": metrics.triage_calls,
                    "errors": metrics.errors,
                },
                f,
                indent=2,
            )
        st.success(f"Saved to `evals/results/{os.path.basename(path)}`")
else:
    st.info("Click **Run eval** to score triage against the ground-truth dataset.")

# --- history: trend across any previously saved runs ------------------
saved = sorted(glob.glob(os.path.join(RESULTS_DIR, "triage_eval_*.json")))
if saved:
    st.divider()
    st.subheader("History")
    st.caption(f"{len(saved)} saved run(s) in `evals/results/` — useful for spotting drift across prompt or model changes.")
    rows = []
    for path in saved:
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        row = {"run": data.get("timestamp", os.path.basename(path))}
        row.update(data.get("scores", {}))
        rows.append(row)
    if rows:
        hist_df = pd.DataFrame(rows).set_index("run")
        hist_df = hist_df.rename(columns=METRIC_LABELS)
        st.line_chart(hist_df, x_label="Run", y_label="Score")
        with st.expander("Raw history"):
            st.dataframe(hist_df, use_container_width=True)
