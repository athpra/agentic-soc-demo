"""
SOC analysis orchestration: a two-stage "agentic SOC" style pipeline --

  Stage 1 -- Triage (Qwen2.5-7B-Instruct):
    cheap, fast, high-volume scoring of every raw event so only the
    high-value telemetry gets escalated, instead of treating every log line
    the same.

  Stage 2 -- Investigation (Nemotron-3-Super-120B):
    a slower, higher-reasoning pass over just the escalated events that
    correlates across log sources and produces an analyst-grade,
    human-readable report -- explainable and auditable, not a black box.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from src.config import ModelConfig
from src.llm_client import ChatResult, chat, extract_json

TRIAGE_SYSTEM_PROMPT = """\
You are a SOC telemetry triage engine. You will be given a JSON array of \
raw security events from a single log source. For EACH event, assess how \
worthy it is of an analyst's attention.

Respond with ONLY a JSON array (no prose, no markdown fences), one object \
per input event, in this exact shape:
[{"id": "<event id>", "risk": "low|medium|high", "category": "<short label, \
e.g. credential_access, exfiltration, recon, benign>", "reason": "<one \
concise sentence>"}]

Guidance:
- "high": strong indicator of compromise, needs immediate analyst review.
- "medium": anomalous or policy-relevant, worth a second look.
- "low": routine or clearly benign activity, even if superficially unusual \
(e.g. a single blocked scan from a known noisy internet-wide scanner is \
low, not high, unless corroborated by something else in the batch).
Output valid JSON only.
"""

INVESTIGATE_SYSTEM_PROMPT = """\
You are an AI SOC analyst. You have been handed a set of telemetry \
events, already escalated by a triage system, spanning one or more log \
sources (identity, network, endpoint, cloud). Correlate them into a single \
investigation and write an analyst-grade report a human SOC lead can act on \
without re-reading the raw logs.

Respond in Markdown with these sections, in this order:
## Executive Summary
2-3 sentences, written for a security leader with no time to read logs.
## Timeline
A bullet list of the key events in chronological order.
## Entities Involved
Users, hosts, and external indicators (IPs/domains) implicated.
## MITRE ATT&CK Techniques
Technique ID + name for each stage you can identify, one per line.
## Risk Score
A 0-100 score and a one-word severity label (Low/Medium/High/Critical).
## Recommended Response Actions
A prioritized bullet list of concrete next steps.
## Confidence
Low/Medium/High, with a one-sentence justification.

Be precise and evidence-based. If the evidence does not support an \
escalation, say so plainly rather than manufacturing urgency.

Reply with ONLY the report. Do not include any reasoning, planning, or \
preamble before it -- your response must begin immediately with the text \
"## Executive Summary" and contain nothing before that heading.
"""


@dataclass
class WorkMetrics:
    """Tracks 'work delivered' rather than raw token/request counts, echoing
    the Agentic SOC framing of measuring AI by completed analyst work."""
    events_triaged: int = 0
    high_risk_found: int = 0
    investigations_run: int = 0
    triage_calls: int = 0
    investigation_calls: int = 0
    triage_latency_s: float = field(default=0.0)
    investigation_latency_s: float = field(default=0.0)
    errors: int = 0

    def as_rows(self) -> list[tuple[str, str]]:
        avg_triage = self.triage_latency_s / self.triage_calls if self.triage_calls else 0.0
        avg_invest = (
            self.investigation_latency_s / self.investigation_calls if self.investigation_calls else 0.0
        )
        return [
            ("Events triaged", f"{self.events_triaged}"),
            ("High-risk events found", f"{self.high_risk_found}"),
            ("Investigations completed", f"{self.investigations_run}"),
            ("Avg. triage call latency", f"{avg_triage:.2f}s"),
            ("Avg. investigation latency", f"{avg_invest:.2f}s"),
            ("Errors", f"{self.errors}"),
        ]


def _strip_for_model(event: dict) -> dict:
    """Remove the ground-truth 'scenario' label before it ever reaches the
    model -- the model should find the signal, not be told the answer."""
    return {k: v for k, v in event.items() if k != "scenario"}


def chunk(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _score_batch(batch: list[dict], model_cfg: ModelConfig) -> tuple[list[dict], ChatResult]:
    payload = [_strip_for_model(e) for e in batch]
    messages = [
        {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload)},
    ]
    res: ChatResult = chat(model_cfg, messages, temperature=0.0, max_tokens=1200)
    return batch, res


def parse_triage_batch(batch: list[dict], res: ChatResult) -> dict[str, dict]:
    """Turn one triage ChatResult into {event_id: {risk, category, reason}}
    for every event in the batch it was scored from. Shared by the main
    triage pipeline and the Live Stream demo so both parse identically.
    """
    if res.error:
        return {e["id"]: {"risk": "unknown", "category": "error", "reason": res.error} for e in batch}

    parsed = extract_json(res.text)
    if not isinstance(parsed, list):
        return {
            e["id"]: {"risk": "unknown", "category": "parse_error", "reason": "Model response was not valid JSON."}
            for e in batch
        }

    by_id = {row.get("id"): row for row in parsed if isinstance(row, dict)}
    results = {}
    for e in batch:
        row = by_id.get(e["id"])
        if row:
            results[e["id"]] = {
                "risk": row.get("risk", "unknown"),
                "category": row.get("category", ""),
                "reason": row.get("reason", ""),
            }
        else:
            results[e["id"]] = {"risk": "unknown", "category": "missing", "reason": "No triage result returned."}
    return results


def triage_events(
    events: list[dict],
    model_cfg: ModelConfig,
    metrics: WorkMetrics,
    batch_size: int = 8,
    concurrency: int = 6,
) -> dict[str, dict]:
    """Score every event for risk. Returns {event_id: {risk, category, reason}}.

    Batches events into groups of `batch_size` per call -- large enough to
    be efficient, small enough to keep each call fast and the JSON short
    enough for a 7B model to return reliably. Batches are independent, so
    up to `concurrency` of them run at once (same pattern as the Traffic
    Generator page) -- with ~24 batches at ~6s each, running them one at a
    time takes ~2.5 minutes; a handful in flight together cuts that to
    well under a minute.

    All shared-state mutation (results dict, metrics counters) happens back
    on the calling thread as each future completes, not inside the worker
    threads, so this stays race-free without needing an explicit lock.
    """
    results: dict[str, dict] = {}
    batches = chunk(events, batch_size)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(_score_batch, batch, model_cfg) for batch in batches]
        for future in as_completed(futures):
            batch, res = future.result()
            metrics.triage_calls += 1
            metrics.triage_latency_s += res.latency_s
            metrics.events_triaged += len(batch)

            batch_results = parse_triage_batch(batch, res)
            if res.error or any(v["category"] in ("error", "parse_error") for v in batch_results.values()):
                metrics.errors += 1
            results.update(batch_results)

    metrics.high_risk_found += sum(1 for r in results.values() if r["risk"] == "high")
    return results


_THINK_TAG_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.IGNORECASE | re.DOTALL)
_REPORT_HEADING_RE = re.compile(r"^#{0,3}\s*Executive Summary\s*$", re.IGNORECASE | re.MULTILINE)


def strip_reasoning_preamble(text: str) -> tuple[str, str | None]:
    """Some reasoning-tuned models (Nemotron included) inline their
    chain-of-thought ahead of the actual answer instead of returning it in a
    separate field -- either wrapped in <think> tags, or as unwrapped prose
    like "We need to produce a report... Let's decode the base64...".

    Splits that off so the UI shows only the finished report by default,
    while keeping the reasoning available (e.g. for an optional "show
    reasoning" expander) rather than silently discarding it.
    """
    reasoning_parts = []

    tagged = _THINK_TAG_RE.search(text)
    if tagged:
        reasoning_parts.append(tagged.group(0))
        text = _THINK_TAG_RE.sub("", text).strip()

    match = _REPORT_HEADING_RE.search(text)
    if match and match.start() > 40:
        reasoning_parts.append(text[: match.start()].strip())
        text = text[match.start() :].strip()

    reasoning = "\n\n".join(p for p in reasoning_parts if p) or None
    return text, reasoning


def _call_investigation(events: list[dict], model_cfg: ModelConfig) -> ChatResult:
    """Pure investigation call: no metrics mutation, safe to run from a
    worker thread (see triage_events' docstring for why that matters)."""
    payload = [_strip_for_model(e) for e in events]
    messages = [
        {"role": "system", "content": INVESTIGATE_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, indent=2)},
    ]
    # max_tokens is generous: reasoning-tuned models can spend a large chunk
    # of the budget thinking out loud before writing the report itself.
    res = chat(model_cfg, messages, temperature=0.2, max_tokens=3500)
    if not res.error:
        res.text, res.reasoning = strip_reasoning_preamble(res.text)
    return res


def investigate_events(
    events: list[dict],
    model_cfg: ModelConfig,
    metrics: WorkMetrics,
) -> ChatResult:
    """Run the deep-investigation pass over an already-escalated set of
    events (typically the 'high' risk output of triage_events)."""
    res = _call_investigation(events, model_cfg)
    metrics.investigation_calls += 1
    metrics.investigation_latency_s += res.latency_s
    if res.error:
        metrics.errors += 1
    else:
        metrics.investigations_run += 1
    return res
