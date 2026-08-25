"""Live Stream demo: sustains a target events-per-second rate of *real*
triage calls against Qwen2.5-7B-Instruct, AND paces real investigation
calls against Nemotron-3-Super-120B at the same ratio used throughout this
demo (1 investigation per 189 events triaged) -- so this page is a live,
faithful version of the *blended* cost the ROI artifact prices, not just
the triage half of it.

Threading model: two background threads each pace their own paced
submissions into their own ThreadPoolExecutor; completed results land in
plain queue.Queue instances. Only the main Streamlit thread ever touches
st.* APIs or session_state -- worker threads only ever produce plain
Python values, which is the safe way to combine background threads with
Streamlit.
"""

import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import streamlit as st

from src.analysis import (
    _call_investigation,
    _score_batch,
    parse_triage_batch,
)
from src.config import NEMOTRON_INVESTIGATE, QWEN_TRIAGE
from src.log_generator import get_demo_escalation, stream_batches
from src.ui_theme import header, inject_theme, risk_badge

st.set_page_config(page_title="Live Stream — Agentic SOC Demo", page_icon="📡", layout="wide")
inject_theme()
header(
    "Live Stream",
    f"Sustain a target events/sec of real triage calls against {QWEN_TRIAGE.label}, "
    f"paced alongside real investigation calls against {NEMOTRON_INVESTIGATE.label}.",
    tags=["Real endpoint calls", "Ties to the ROI breakeven"],
)

st.markdown(
    "This fires **real, live** requests at both endpoints for the whole run — it isn't "
    "simulated, and it isn't triage-only: investigations are paced at the same 1-per-189-events "
    "ratio the ROI cost model uses, so the blended $/EPS figure it reports at the end reflects "
    "the same mix of work that number was priced against. Do a short dry run at a low target "
    "rate before presenting this live; a shared endpoint may not sustain every rate equally, and "
    "that's a genuine, honest result either way."
)
st.caption(
    "⏱️ The duration below is the *submission* window, not the total wait — the last "
    "investigation call started near the end still has to finish (~15-19s on this endpoint), "
    "so the page keeps live-updating for a while after the configured duration passes. That's "
    "expected, not a hang."
)

BATCH_SIZE = 8
EVENTS_PER_INVESTIGATION = 189  # this demo's actual escalation ratio

# Fallback token-size estimates -- matches the ROI artifact's methodology
# exactly. Used only when the endpoint doesn't return a real usage object;
# real per-call token counts (from ChatResult.prompt_tokens/completion_tokens)
# are preferred whenever the endpoint provides them.
EST_TRIAGE_PROMPT_TOK, EST_TRIAGE_COMPLETION_TOK = 793, 218
EST_INVEST_PROMPT_TOK, EST_INVEST_COMPLETION_TOK = 899, 766

FRONTIER_PRICING = {
    "GPT-5-mini → GPT-5": {"triage": (0.25, 2.00), "investigate": (1.25, 10.00)},
    "Gemini 3 Flash → 3.1 Pro": {"triage": (0.50, 3.00), "investigate": (2.00, 12.00)},
    "Claude Sonnet 5 → Opus 5": {"triage": (3.00, 15.00), "investigate": (5.00, 25.00)},
}

# Self-hosted Cloudera AI Inference: fixed annual cost regardless of volume,
# reused from the sibling PoC's real deployment of these same two models
# (1x A10G Qwen + 4x A10G Nemotron) -- matches the ROI artifact exactly.
CLOUDERA_FIXED_ANNUAL = 26_000 + 86_000

st.subheader("Configuration")
c1, c2 = st.columns(2)
with c1:
    target_eps = st.slider("Target events/sec", min_value=1, max_value=40, value=28,
                            help="28 matches the ROI artifact's breakeven point against the GPT-5-mini → GPT-5 pairing.")
with c2:
    duration_s = st.slider("Run duration (seconds)", min_value=10, max_value=90, value=30)

calls_per_sec = target_eps / BATCH_SIZE
est_triage_latency = st.session_state.get("live_stream_last_triage_latency", 6.15)
est_invest_latency = st.session_state.get("live_stream_last_invest_latency", 17.0)
investigation_interval = EVENTS_PER_INVESTIGATION / target_eps

suggested_triage_concurrency = min(40, max(4, int(calls_per_sec * est_triage_latency * 1.3) + 2))
suggested_invest_concurrency = min(10, max(2, int((1 / investigation_interval) * est_invest_latency * 1.4) + 1))

c3, c4 = st.columns(2)
with c3:
    triage_concurrency = st.slider(
        "Triage concurrency", min_value=2, max_value=40, value=suggested_triage_concurrency,
        help=f"Suggested from Little's Law: {calls_per_sec:.2f} calls/sec × ~{est_triage_latency:.1f}s latency, +30% headroom.",
    )
with c4:
    invest_concurrency = st.slider(
        "Investigation concurrency", min_value=1, max_value=10, value=suggested_invest_concurrency,
        help=f"One investigation every ~{investigation_interval:.1f}s at this target rate, ~{est_invest_latency:.0f}s each.",
    )

st.caption(
    f"{BATCH_SIZE} events/call for triage → {calls_per_sec:.2f} calls/sec needed. "
    f"1 investigation per {EVENTS_PER_INVESTIGATION} events triaged → one every ~{investigation_interval:.1f}s."
)

run = st.button("Start stream", type="primary")

if run:
    triage_q: "queue.Queue" = queue.Queue()
    invest_q: "queue.Queue" = queue.Queue()

    def triage_submit_loop():
        gen = stream_batches(BATCH_SIZE)
        interval = BATCH_SIZE / target_eps
        start = time.perf_counter()
        next_send = start
        with ThreadPoolExecutor(max_workers=triage_concurrency) as pool:
            while time.perf_counter() - start < duration_s:
                now = time.perf_counter()
                if now >= next_send:
                    batch = next(gen)
                    fut = pool.submit(_score_batch, batch, QWEN_TRIAGE)
                    fut.add_done_callback(lambda f: triage_q.put(f.result()))
                    next_send += interval
                else:
                    time.sleep(min(0.01, max(0.0, next_send - now)))
        triage_q.put(None)

    def investigation_submit_loop():
        escalation = get_demo_escalation()
        start = time.perf_counter()
        next_send = start + investigation_interval  # first one lands mid-run, not at t=0
        with ThreadPoolExecutor(max_workers=invest_concurrency) as pool:
            while time.perf_counter() - start < duration_s:
                now = time.perf_counter()
                if now >= next_send:
                    fut = pool.submit(_call_investigation, escalation, NEMOTRON_INVESTIGATE)
                    fut.add_done_callback(lambda f: invest_q.put(f.result()))
                    next_send += investigation_interval
                else:
                    time.sleep(min(0.05, max(0.0, next_send - now)))
        invest_q.put(None)

    triage_worker = threading.Thread(target=triage_submit_loop, daemon=True)
    invest_worker = threading.Thread(target=investigation_submit_loop, daemon=True)
    triage_worker.start()
    invest_worker.start()

    triage_kpi_ph = st.empty()
    invest_kpi_ph = st.empty()
    chart_ph = st.empty()
    risk_ph = st.empty()
    st.caption(
        "ℹ️ Investigations here fire on a **fixed schedule** (1 per "
        f"{EVENTS_PER_INVESTIGATION} events triaged, matching the ROI cost model's assumed "
        "ratio) against a fixed real escalation payload — they don't track how many events "
        "triage actually marks `high` above. Investigating every real high-risk finding would "
        "be a much higher-volume (and higher-cost) workload than the one these numbers price; "
        "the fixed cadence is what keeps this page's cost figures consistent with the ROI artifact."
    )

    events_done = 0
    batch_errors = 0
    triage_api_errors = 0
    risk_counts = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
    per_sec: dict[int, int] = {}
    triage_latencies: list[float] = []
    triage_prompt_tok, triage_completion_tok, triage_real_usage_calls = 0, 0, 0

    invest_done = 0
    invest_errors = 0
    invest_latencies: list[float] = []
    invest_prompt_tok, invest_completion_tok, invest_real_usage_calls = 0, 0, 0

    t0 = time.perf_counter()
    triage_finished = False
    invest_finished = False

    while not (triage_finished and invest_finished):
        drained = False

        while True:
            try:
                item = triage_q.get_nowait()
            except queue.Empty:
                break
            drained = True
            if item is None:
                triage_finished = True
                break
            batch, res = item
            bucket = int(time.perf_counter() - t0)
            per_sec[bucket] = per_sec.get(bucket, 0) + len(batch)
            triage_latencies.append(res.latency_s)
            if res.error:
                triage_api_errors += 1  # no completion was generated -- not billable
            if res.prompt_tokens is not None:
                triage_prompt_tok += res.prompt_tokens
                triage_completion_tok += (res.completion_tokens or 0)
                triage_real_usage_calls += 1
            batch_results = parse_triage_batch(batch, res)
            if res.error or any(v["category"] in ("error", "parse_error") for v in batch_results.values()):
                batch_errors += 1
            for v in batch_results.values():
                risk_counts[v["risk"] if v["risk"] in risk_counts else "unknown"] += 1
            events_done += len(batch)

        while True:
            try:
                item = invest_q.get_nowait()
            except queue.Empty:
                break
            drained = True
            if item is None:
                invest_finished = True
                break
            res = item
            invest_latencies.append(res.latency_s)
            if res.prompt_tokens is not None:
                invest_prompt_tok += res.prompt_tokens
                invest_completion_tok += (res.completion_tokens or 0)
                invest_real_usage_calls += 1
            if res.error:
                invest_errors += 1
            else:
                invest_done += 1

        elapsed = time.perf_counter() - t0
        window_secs = [b for b in per_sec if b >= int(elapsed) - 5]
        recent_eps = sum(per_sec[b] for b in window_secs) / min(5, elapsed) if elapsed > 0 else 0.0

        with triage_kpi_ph.container():
            st.caption("Triage — Qwen2.5-7B-Instruct")
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Events triaged", events_done)
            k2.metric("Current EPS (5s window)", f"{recent_eps:.1f}", delta=f"{recent_eps - target_eps:+.1f} vs target")
            k3.metric("Elapsed", f"{min(elapsed, duration_s):.0f}s / {duration_s}s")
            k4.metric("Avg call latency", f"{(sum(triage_latencies)/len(triage_latencies)):.2f}s" if triage_latencies else "—")
            k5.metric("Failed batches", batch_errors)

        with invest_kpi_ph.container():
            st.caption("Investigate — Nemotron-3-Super-120B")
            i1, i2, i3 = st.columns(3)
            i1.metric("Investigations completed", invest_done)
            i2.metric("Avg investigation latency", f"{(sum(invest_latencies)/len(invest_latencies)):.1f}s" if invest_latencies else "—")
            i3.metric("Failed investigations", invest_errors)

        if per_sec:
            df = pd.DataFrame({"second": list(per_sec.keys()), "events/sec": list(per_sec.values())}).sort_values("second")
            chart_ph.bar_chart(df.set_index("second"), x_label="Seconds since start", y_label="Events triaged")

        with risk_ph.container():
            r1, r2, r3, r4 = st.columns(4)
            r1.markdown(f"{risk_badge('high')} **{risk_counts['high']}**", unsafe_allow_html=True)
            r2.markdown(f"{risk_badge('medium')} **{risk_counts['medium']}**", unsafe_allow_html=True)
            r3.markdown(f"{risk_badge('low')} **{risk_counts['low']}**", unsafe_allow_html=True)
            r4.markdown(f"{risk_badge('unknown')} **{risk_counts['unknown']}**", unsafe_allow_html=True)

        if not drained:
            time.sleep(0.1)

    triage_worker.join(timeout=5)
    invest_worker.join(timeout=5)

    st.divider()
    final_elapsed = time.perf_counter() - t0
    avg_triage_latency = sum(triage_latencies) / len(triage_latencies) if triage_latencies else 0.0
    avg_invest_latency = sum(invest_latencies) / len(invest_latencies) if invest_latencies else 0.0
    if triage_latencies:
        st.session_state["live_stream_last_triage_latency"] = avg_triage_latency
    if invest_latencies:
        st.session_state["live_stream_last_invest_latency"] = avg_invest_latency

    warmup = int(avg_triage_latency)
    steady_buckets = [b for b in per_sec if warmup <= b < duration_s]
    steady_eps = sum(per_sec[b] for b in steady_buckets) / len(steady_buckets) if steady_buckets else 0.0

    if steady_eps >= target_eps:
        hit_label = "Yes"
    elif steady_eps >= target_eps * 0.9:
        hit_label = f"Close ({steady_eps / target_eps:.0%} of target)"
    else:
        hit_label = f"Below target ({steady_eps / target_eps:.0%})"

    st.subheader("Run summary")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Total events triaged", events_done)
    s2.metric("Steady-state EPS", f"{steady_eps:.1f}", delta=f"{steady_eps - target_eps:+.1f} vs target")
    s3.metric("Target EPS", target_eps)
    s4.metric("Hit target?", hit_label)

    expected_investigations = final_elapsed / investigation_interval
    st.caption(
        f"Investigations: {invest_done} completed ({invest_errors} failed) — ≈{expected_investigations:.1f} "
        f"expected at 1-per-{EVENTS_PER_INVESTIGATION}-events over this run's {final_elapsed:.0f}s. "
        f"Steady-state EPS excludes the cold-start ramp-up (first ~{warmup}s) and the tail-drain "
        "after submission stopped."
    )

    # --- blended cost capstone: real token counts where the endpoint returned
    # usage, falling back to the ROI artifact's measured per-call estimates
    # otherwise -- same formula the ROI artifact uses, applied to this run's
    # actual call counts.
    # Billable calls only: a genuine API/network failure (res.error) produced
    # no completion and isn't billed on most APIs. A triage batch that came
    # back as unparseable JSON *did* still consume real prompt+completion
    # tokens, so it stays counted -- only true res.error calls are excluded.
    triage_calls_total = len(triage_latencies) - triage_api_errors
    invest_calls_total = invest_done

    if triage_real_usage_calls:
        avg_t_prompt = triage_prompt_tok / triage_real_usage_calls
        avg_t_completion = triage_completion_tok / triage_real_usage_calls
        triage_tok_source = "real usage reported by the endpoint"
    else:
        avg_t_prompt, avg_t_completion = EST_TRIAGE_PROMPT_TOK, EST_TRIAGE_COMPLETION_TOK
        triage_tok_source = "estimated (endpoint did not return token usage)"

    if invest_real_usage_calls:
        avg_i_prompt = invest_prompt_tok / invest_real_usage_calls
        avg_i_completion = invest_completion_tok / invest_real_usage_calls
        invest_tok_source = "real usage reported by the endpoint"
    else:
        avg_i_prompt, avg_i_completion = EST_INVEST_PROMPT_TOK, EST_INVEST_COMPLETION_TOK
        invest_tok_source = "estimated (endpoint did not return token usage)"

    st.subheader("What this exact run would have cost on a frontier API")
    st.caption(
        f"Triage token sizes: {triage_tok_source}. Investigation token sizes: {invest_tok_source}. "
        f"Applied to this run's actual {triage_calls_total} triage calls and {invest_calls_total} "
        "investigation calls — same pricing as the ROI cost model artifact."
    )
    rows = []
    for name, p in FRONTIER_PRICING.items():
        t_in, t_out = p["triage"]
        i_in, i_out = p["investigate"]
        triage_cost = triage_calls_total * (avg_t_prompt / 1e6 * t_in + avg_t_completion / 1e6 * t_out)
        invest_cost = invest_calls_total * (avg_i_prompt / 1e6 * i_in + avg_i_completion / 1e6 * i_out)
        rows.append({"Pairing": name, "Triage cost": f"${triage_cost:.4f}", "Investigation cost": f"${invest_cost:.4f}", "Total": f"${triage_cost + invest_cost:.4f}"})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.caption(
        "Self-hosted Cloudera AI Inference bills by fixed GPU capacity, not by this run — see the "
        "ROI artifact for the breakeven volume where that fixed cost beats these per-token totals."
    )

    # --- annualized projection at this run's actual demonstrated rate -----
    st.subheader("If sustained year-round at this rate")
    events_per_year = steady_eps * 86400 * 365
    investigations_per_year = events_per_year / EVENTS_PER_INVESTIGATION
    batches_per_year = events_per_year / BATCH_SIZE

    st.caption(
        f"Not a projection from a target — this extrapolates the {steady_eps:.1f} EPS this run "
        f"actually sustained ({events_per_year:,.0f} events/yr, {investigations_per_year:,.0f} "
        "investigations/yr) out to a full year, and compares it against Cloudera's fixed cost."
    )

    annual_rows = [{"Option": "Cloudera AI Inference (fixed)", "Annual cost": f"${CLOUDERA_FIXED_ANNUAL:,.0f}", "vs. Cloudera": "—"}]
    for name, p in FRONTIER_PRICING.items():
        t_in, t_out = p["triage"]
        i_in, i_out = p["investigate"]
        triage_annual = batches_per_year * (avg_t_prompt / 1e6 * t_in + avg_t_completion / 1e6 * t_out)
        invest_annual = investigations_per_year * (avg_i_prompt / 1e6 * i_in + avg_i_completion / 1e6 * i_out)
        total_annual = triage_annual + invest_annual
        delta = CLOUDERA_FIXED_ANNUAL - total_annual
        # delta = Cloudera - frontier: positive means Cloudera costs MORE,
        # negative means Cloudera costs LESS (i.e. is cheaper).
        sign = "more expensive" if delta > 0 else "cheaper"
        annual_rows.append({
            "Option": name,
            "Annual cost": f"${total_annual:,.0f}",
            "vs. Cloudera": f"Cloudera {sign} by ${abs(delta):,.0f}",
        })
    st.dataframe(pd.DataFrame(annual_rows), use_container_width=True, hide_index=True)

    beats_all = all(
        CLOUDERA_FIXED_ANNUAL
        < batches_per_year * (avg_t_prompt / 1e6 * p["triage"][0] + avg_t_completion / 1e6 * p["triage"][1])
        + investigations_per_year * (avg_i_prompt / 1e6 * p["investigate"][0] + avg_i_completion / 1e6 * p["investigate"][1])
        for p in FRONTIER_PRICING.values()
    )
    st.caption(
        "At this demonstrated rate, Cloudera beats every frontier pairing above." if beats_all else
        "At this demonstrated rate, Cloudera doesn't yet beat every frontier pairing above — the "
        "governance argument (telemetry never leaves the platform) holds regardless; the pure cost "
        "argument needs a higher sustained rate against whichever pairing still shows cheaper."
    )
else:
    st.info("Configure a target rate and duration above, then click **Start stream**.")
