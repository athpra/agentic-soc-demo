"""
Cross-platform latency/throughput benchmark: fires the same load of real
triage-style requests at a given ModelConfig, on any provider, using the
same llm_client.chat() every other page in this app calls. Used by
pages/5_Benchmark.py to compare the same model family (e.g.
Qwen2.5-7B-Instruct) across Cloudera AI Inference and Fireworks AI.

Kept separate from the Traffic Generator page's own load-firing loop
(similar in spirit, different shape) rather than refactored to share code,
to avoid touching an already-tested, working page for this feature.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from src.config import ModelConfig
from src.llm_client import chat

# A real triage-shaped prompt, not a throwaway "hello world" -- so latency
# reflects the actual workload this app cares about.
BENCHMARK_PROMPT = (
    "In one short sentence, assess the risk (low/medium/high) of this security "
    'event and say why: {"event_type": "authentication", "action": "login_failed", '
    '"src_ip": "203.0.113.44", "user": "jsmith", "mfa": true}'
)


def run_latency_benchmark(
    model_cfg: ModelConfig,
    n_requests: int,
    concurrency: int,
    max_tokens: int = 64,
    on_result: Optional[Callable[[dict], None]] = None,
) -> list[dict]:
    """Fires n_requests at model_cfg with up to `concurrency` in flight.

    Returns a list of {seq, latency_s, success, error} rows, one per
    request, in completion order. If `on_result` is given, it's invoked
    once per completed request -- always from the calling thread (via the
    as_completed loop below, never from a worker thread), so it's safe to
    update Streamlit state/UI from it.
    """
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(chat, model_cfg, [{"role": "user", "content": BENCHMARK_PROMPT}], max_tokens=max_tokens): i
            for i in range(n_requests)
        }
        for future in as_completed(futures):
            seq = futures[future]
            res = future.result()
            row = {"seq": seq, "latency_s": res.latency_s, "success": res.error is None, "error": res.error}
            rows.append(row)
            if on_result:
                on_result(row)
    return rows


def summarize_latencies(rows: list[dict], wall_time_s: float) -> dict:
    """Aggregate a run_latency_benchmark() result into summary stats.

    Latency percentiles are computed from successful calls only. A failed
    call (auth error, connection refused, etc.) often fails almost
    instantly -- no network round-trip at all -- so mixing its "latency"
    into the percentiles makes a completely broken provider look fast
    rather than broken. success_rate and throughput still reflect every
    attempt, successful or not.
    """
    n = len(rows)
    successes = sum(1 for r in rows if r["success"])
    latencies = sorted(r["latency_s"] for r in rows if r["success"])
    n_ok = len(latencies)

    def _pct(p: float) -> float:
        if not latencies:
            return float("nan")
        idx = min(n_ok - 1, int(round(p * (n_ok - 1))))
        return latencies[idx]

    return {
        "n": n,
        "successes": successes,
        "success_rate": successes / n if n else float("nan"),
        "mean_latency_s": sum(latencies) / n_ok if n_ok else float("nan"),
        "p50_latency_s": _pct(0.50),
        "p95_latency_s": _pct(0.95),
        "max_latency_s": latencies[-1] if latencies else float("nan"),
        "throughput_rps": n / wall_time_s if wall_time_s > 0 else float("nan"),
        "wall_time_s": wall_time_s,
    }
