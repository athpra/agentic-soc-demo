"""Live Stream demo: sustains a target events-per-second rate of *real*
triage calls against Qwen2.5-7B-Instruct on Cloudera AI Inference, using the
exact same batching and prompt as the main Triage & Investigate page --
built to make the ROI artifact's EPS breakeven numbers tangible on stage.

Threading model: a background thread paces batch submissions on a fixed
schedule into a ThreadPoolExecutor; completed results land in a plain
queue.Queue. Only the main Streamlit thread ever touches st.* APIs or
session_state -- the worker thread and pool only ever produce plain Python
values, which is the safe way to combine background threads with Streamlit.
"""

import queue
import threading
import time

import pandas as pd
import streamlit as st

from src.analysis import WorkMetrics, _score_batch, parse_triage_batch
from src.config import QWEN_TRIAGE
from src.log_generator import stream_batches
from src.ui_theme import header, inject_theme, risk_badge

st.set_page_config(page_title="Live Stream — Agentic SOC Demo", page_icon="📡", layout="wide")
inject_theme()
header(
    "Live Stream",
    f"Sustain a target events/sec rate of real {QWEN_TRIAGE.label} triage calls against Cloudera AI Inference.",
    tags=["Real endpoint calls", "Ties to the ROI breakeven"],
)

st.markdown(
    "This fires **real, live** triage requests at the endpoint for the whole run — it isn't "
    "simulated. Do a short dry run at a low target rate before presenting this live; a shared "
    "endpoint may not sustain every rate equally, and that's a genuine, honest result either way."
)

BATCH_SIZE = 8

st.subheader("Configuration")
c1, c2 = st.columns(2)
with c1:
    target_eps = st.slider("Target events/sec", min_value=1, max_value=40, value=28,
                            help="28 matches the ROI artifact's breakeven point against the GPT-5-mini → GPT-5 pairing.")
with c2:
    duration_s = st.slider("Run duration (seconds)", min_value=10, max_value=90, value=30)

calls_per_sec = target_eps / BATCH_SIZE
est_latency = st.session_state.get("live_stream_last_avg_latency", 6.15)
suggested_concurrency = min(40, max(4, int(calls_per_sec * est_latency * 1.3) + 2))
concurrency = st.slider(
    "Concurrency (parallel in-flight requests)", min_value=2, max_value=40, value=suggested_concurrency,
    help=f"Suggested from Little's Law: {calls_per_sec:.2f} calls/sec × ~{est_latency:.1f}s latency, +30% headroom. "
         "Raise it if achieved EPS stays below target; the endpoint's real capacity is what it is.",
)
st.caption(f"{BATCH_SIZE} events/call (same batching as the main pipeline) → {calls_per_sec:.2f} calls/sec needed to hit {target_eps} events/sec.")

run = st.button("Start stream", type="primary")

if run:
    result_q: "queue.Queue" = queue.Queue()
    stop_flag = threading.Event()

    def submit_loop():
        from concurrent.futures import ThreadPoolExecutor

        gen = stream_batches(BATCH_SIZE)
        interval = BATCH_SIZE / target_eps
        start = time.perf_counter()
        next_send = start
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            while time.perf_counter() - start < duration_s and not stop_flag.is_set():
                now = time.perf_counter()
                if now >= next_send:
                    batch = next(gen)
                    fut = pool.submit(_score_batch, batch, QWEN_TRIAGE)
                    fut.add_done_callback(lambda f: result_q.put(f.result()))
                    next_send += interval
                else:
                    time.sleep(min(0.01, max(0.0, next_send - now)))
            # stop submitting; let whatever's already in flight finish
        result_q.put(None)  # sentinel: submission (and drain) is done

    worker = threading.Thread(target=submit_loop, daemon=True)
    worker.start()

    kpi_ph = st.empty()
    chart_ph = st.empty()
    risk_ph = st.empty()

    events_done = 0
    batch_errors = 0
    risk_counts = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
    per_sec: dict[int, int] = {}
    latencies: list[float] = []
    t0 = time.perf_counter()
    finished = False

    while not finished:
        drained = False
        while True:
            try:
                item = result_q.get(timeout=0.3)
            except queue.Empty:
                break
            drained = True
            if item is None:
                finished = True
                break
            batch, res = item
            bucket = int(time.perf_counter() - t0)
            per_sec[bucket] = per_sec.get(bucket, 0) + len(batch)
            latencies.append(res.latency_s)
            batch_results = parse_triage_batch(batch, res)
            if res.error or any(v["category"] in ("error", "parse_error") for v in batch_results.values()):
                batch_errors += 1
            for v in batch_results.values():
                risk_counts[v["risk"] if v["risk"] in risk_counts else "unknown"] += 1
            events_done += len(batch)

        elapsed = time.perf_counter() - t0
        cumulative_eps = events_done / elapsed if elapsed > 0 else 0.0
        # Cumulative EPS is dragged down by the ramp-up (first ~1 latency-period
        # has requests in flight but none completed yet) and by the tail-drain
        # after submission stops -- a recent-window rate reflects the actual
        # current sustained pace much better once steady state is reached.
        window_secs = [b for b in per_sec if b >= int(elapsed) - 5]
        recent_eps = sum(per_sec[b] for b in window_secs) / min(5, elapsed) if elapsed > 0 else 0.0
        with kpi_ph.container():
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Events triaged", events_done)
            k2.metric("Current EPS (5s window)", f"{recent_eps:.1f}", delta=f"{recent_eps - target_eps:+.1f} vs target")
            k3.metric("Elapsed", f"{min(elapsed, duration_s):.0f}s / {duration_s}s")
            k4.metric("Avg call latency", f"{(sum(latencies)/len(latencies)):.2f}s" if latencies else "—")
            k5.metric("Failed batches", batch_errors)

        if per_sec:
            df = pd.DataFrame({"second": list(per_sec.keys()), "events/sec": list(per_sec.values())}).sort_values("second")
            chart_ph.bar_chart(df.set_index("second"))

        with risk_ph.container():
            r1, r2, r3, r4 = st.columns(4)
            r1.markdown(f"{risk_badge('high')} **{risk_counts['high']}**", unsafe_allow_html=True)
            r2.markdown(f"{risk_badge('medium')} **{risk_counts['medium']}**", unsafe_allow_html=True)
            r3.markdown(f"{risk_badge('low')} **{risk_counts['low']}**", unsafe_allow_html=True)
            r4.markdown(f"{risk_badge('unknown')} **{risk_counts['unknown']}**", unsafe_allow_html=True)

        if not drained:
            time.sleep(0.1)

    worker.join(timeout=5)

    st.divider()
    final_elapsed = time.perf_counter() - t0
    overall_eps = events_done / final_elapsed if final_elapsed > 0 else 0.0
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    if latencies:
        st.session_state["live_stream_last_avg_latency"] = avg_latency

    # Fair "sustained" figure: only the seconds after the first completions
    # could plausibly have arrived (one avg latency in) and before submission
    # stopped -- excludes both the cold-start ramp-up and the tail-drain,
    # which otherwise dilute a naive events/total-wall-time calculation.
    warmup = int(avg_latency)
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

    st.caption(
        f"Steady-state EPS excludes the cold-start ramp-up (first ~{warmup}s, before any request "
        f"could have completed) and the tail-drain after submission stopped. Overall throughput "
        f"including that ramp-up/drain was {overall_eps:.1f} events/sec across the full "
        f"{final_elapsed:.0f}s wall time. {target_eps} EPS is the breakeven point against the "
        "GPT-5-mini → GPT-5 pairing in the cost model — sustaining it here is the live version of "
        "that number, against the real endpoint, not a projection."
    )
else:
    st.info("Configure a target rate and duration above, then click **Start stream**.")
