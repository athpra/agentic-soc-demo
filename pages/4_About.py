"""Background page: the "agentic SOC" framing this demo is modeled on, and
what this project is / is not."""

import streamlit as st

from src.ui_theme import header, inject_theme

st.set_page_config(page_title="About — Agentic SOC Demo", page_icon="ℹ️", layout="wide")
inject_theme()
header(
    "About this demo",
    "What this project is, what it borrows from, and what it is not.",
)

st.subheader("What this project is")
st.markdown(
    """
This is a **Cloudera reference project**: a small Streamlit application, deployable as a
Cloudera AI Workbench Application, that demonstrates calling model endpoints served by
**Cloudera AI Inference Service** — here, `Qwen2.5-7B-Instruct` and
`Nemotron-3-Super-120B` — from application code, using a security-operations log-analysis
scenario as a realistic, non-trivial worked example. It also includes a standalone traffic
generator for exercising the endpoints at configurable request volume and concurrency.

All telemetry in the demo is **synthetic**, generated deterministically by
`src/log_generator.py` — no real logs, customers, or incidents are involved.
"""
)

st.subheader("The framing it borrows from")
st.markdown(
    """
Several security operations companies now describe their platforms as an **"agentic
SOC"**: instead of a single AI feature bolted onto a SIEM, a set of purpose-built AI agents
work together across detection, investigation, response, and reporting as one coordinated
system, with policy and human oversight built into that coordination rather than left to
each feature individually. Three ideas from that general pattern shape this demo's
pipeline:

- **Route by value.** Not every log line deserves the same treatment. High-value or
  high-risk telemetry should get fast, real-time attention; the rest can be handled more
  cheaply. This demo's triage stage — a small, fast model scoring every event — is a toy
  version of that idea.
- **Governed orchestration.** Separating *deciding what to do* from *doing it* keeps AI
  action explainable, auditable, and policy-controlled, with a human able to stay in the
  loop rather than a single opaque model making every call. This demo keeps its two stages
  distinct (and their outputs visible) for the same reason, on a much smaller scale.
- **Measure work, not tokens.** The useful question for an AI system in this space isn't
  "how much did it process" but "how much analyst work did it actually complete." This
  demo's "work delivered" panel (events triaged, cases escalated, investigations completed)
  is a small nod to that framing.

This is a general pattern being adopted across the industry, not a specific product's
architecture, and the implementation here is this project's own simplified take on it —
built only to give the model-calling code something realistic to do.
"""
)

st.subheader("What this project is not")
st.markdown(
    """
- It is **not** modeled on, built from, or reverse-engineered from any specific security
  operations vendor's product, documentation, or marketing material.
- It does **not** connect to, use, or reference any real security operations platform,
  API, or customer data.
- The "triage → investigate" pipeline is a simplified, two-model illustration built for
  this demo — it is not a claim about how any commercial "agentic SOC" product is actually
  implemented.

It exists purely to show, end-to-end, how a project on **Cloudera AI Workbench** can call
models hosted on **Cloudera AI Inference Service** to do real analytical work.
"""
)
