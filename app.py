"""
Agentic SOC Reference Demo -- Home page.

A Cloudera AI Workbench Application that shows a two-stage SOC analysis
pipeline calling model endpoints served by Cloudera AI Inference Service:

  Qwen2.5-7B-Instruct        -> fast, high-volume triage of raw telemetry
  Nemotron-3-Super-120B      -> deep, correlated investigation of what
                                 triage escalates

See pages/ for the interactive demo and the raw traffic generator.
"""

import streamlit as st

from src.config import MODELS
from src.llm_client import chat
from src.ui_theme import header, inject_theme

st.set_page_config(page_title="Agentic SOC Reference Demo", page_icon="🛡️", layout="wide")
inject_theme()

header(
    "Agentic SOC — Reference Demo",
    "Two-stage security telemetry analysis on Cloudera AI Inference Service, "
    "built to show how a Cloudera AI Workbench project calls internal model endpoints.",
    tags=["Cloudera AI Workbench", "Cloudera AI Inference Service"],
)

st.markdown(
    """
This project is a small, self-contained reference for calling model
endpoints deployed on **Cloudera AI Inference Service** from a **Cloudera AI
Workbench** application, using a security-operations scenario as the
worked example.

The scenario borrows its shape from a pattern increasingly common among
security operations vendors: an **"agentic SOC"**, where purpose-built AI
agents work together across detection, investigation, response, and
reporting, with governance built in and work measured by outcomes rather
than tokens processed. This demo is an independent reference build inspired
by that general industry framing, built purely to exercise Cloudera's
model-serving stack — it is not modeled on, affiliated with, or endorsed by
any specific vendor.
"""
)

st.subheader("Pipeline")
col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("#### 1 · Route")
    st.markdown(
        "Raw telemetry from identity, network, endpoint, and cloud logs is "
        "sent to **Qwen2.5-7B-Instruct** for fast, cheap risk scoring — "
        "similar in spirit to how a value-based data pipeline routes "
        "telemetry instead of treating every log line the same."
    )
with col2:
    st.markdown("#### 2 · Investigate")
    st.markdown(
        "Whatever gets escalated as high-risk is handed to "
        "**Nemotron-3-Super-120B**, which correlates it across sources into "
        "a single, human-readable investigation — timeline, MITRE ATT&CK "
        "mapping, risk score, and recommended response."
    )
with col3:
    st.markdown("#### 3 · Measure")
    st.markdown(
        "The demo tracks *work delivered* — events triaged, cases "
        "escalated, investigations completed — rather than raw request or "
        "token counts, echoing the idea of measuring AI by analyst work "
        "completed."
    )

st.divider()

st.subheader("Try it")
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.page_link("pages/1_Triage_and_Investigate.py", label="🔍 Triage & Investigate", icon="🔍")
    st.caption("Run the full pipeline over synthetic SOC telemetry and read the generated investigation report.")
with c2:
    st.page_link("pages/2_Traffic_Generator.py", label="📈 Traffic Generator", icon="📈")
    st.caption("Send configurable, concurrent request volume at either endpoint to exercise Cloudera AI Inference Service.")
with c3:
    st.page_link("pages/3_Live_Stream.py", label="📡 Live Stream", icon="📡")
    st.caption("Sustain a target events/sec of real triage calls — the live version of the ROI breakeven number.")
with c4:
    st.page_link("pages/4_Evals.py", label="🧪 Evals", icon="🧪")
    st.caption("Score triage against the dataset's ground-truth labels — rerun after any prompt change.")

st.divider()

st.subheader("Endpoint health")
st.caption("Sends one tiny prompt to each Cloudera AI Inference endpoint to confirm connectivity and auth.")

if st.button("Ping both endpoints"):
    cols = st.columns(len(MODELS))
    for col, model_cfg in zip(cols, MODELS.values()):
        with col:
            with st.spinner(f"Calling {model_cfg.label}..."):
                res = chat(
                    model_cfg,
                    [{"role": "user", "content": "Reply with exactly one word: ready"}],
                    max_tokens=8,
                )
            st.markdown(f"**{model_cfg.label}**")
            st.caption(model_cfg.role)
            if res.error:
                st.error(f"Failed ({res.latency_s:.2f}s)")
                st.code(res.error, language="text")
            else:
                st.success(f"OK — {res.latency_s:.2f}s")
                st.caption(f"Response: `{res.text.strip()[:60]}`")

with st.expander("Endpoint configuration"):
    for model_cfg in MODELS.values():
        st.markdown(f"**{model_cfg.label}** — _{model_cfg.role}_")
        st.code(f"base_url = {model_cfg.base_url}\nmodel_id = {model_cfg.model_id}", language="text")
