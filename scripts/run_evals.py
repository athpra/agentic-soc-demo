#!/usr/bin/env python3
"""
Deterministic triage eval.

Scores Qwen2.5-7B-Instruct's real triage output against the ground-truth
`scenario` labels baked into the synthetic dataset (src/log_generator.py):
does it actually catch the seeded attack chain, and does it avoid crying
wolf on the noisy-scanner red herring and plain baseline noise? Runs the
exact same triage_events() pipeline the app uses, at temperature=0.0
against the same deterministic (seed=42) dataset, so results are
comparable run-to-run -- rerun this after any prompt or model change to
see whether it actually helped.

Usage:
    python scripts/run_evals.py [--save]

Requires the same auth as the rest of this app: run inside a Cloudera AI
Workbench Session/Application/Job, or export CDP_TOKEN locally.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import WorkMetrics, triage_events  # noqa: E402
from src.config import QWEN_TRIAGE  # noqa: E402
from src.log_generator import generate_dataset  # noqa: E402

# --- Eval thresholds -- tune these as the prompt/model changes -------------
# key -> (target, "higher_is_better" | "lower_is_better")
THRESHOLDS = {
    "attack_chain_recall_high": (0.60, "higher_is_better"),
    # looser bar: caught as at least worth a second look, even if not flagged high
    "attack_chain_recall_medium_or_high": (0.85, "higher_is_better"),
    "noisy_scanner_false_positive_rate": (0.05, "lower_is_better"),
    "baseline_false_positive_rate": (0.05, "lower_is_better"),
    "parse_reliability": (0.99, "higher_is_better"),
}

METRIC_LABELS = {
    "attack_chain_recall_high": "Attack chain caught as HIGH",
    "attack_chain_recall_medium_or_high": "Attack chain caught as MEDIUM+",
    "noisy_scanner_false_positive_rate": "Noisy scanner wrongly flagged HIGH",
    "baseline_false_positive_rate": "Baseline noise wrongly flagged HIGH",
    "parse_reliability": "Valid, parseable triage result",
}


def load_ground_truth() -> list[dict]:
    events = []
    for source_events in generate_dataset().values():
        events.extend(source_events)
    return events


def _frac(rows: list[dict], predicate) -> float:
    if not rows:
        return float("nan")
    return sum(1 for r in rows if predicate(r)) / len(rows)


def run_eval() -> tuple[dict, WorkMetrics, dict[str, list[dict]]]:
    events = load_ground_truth()
    metrics = WorkMetrics()
    print(f"Triaging {len(events)} events against {QWEN_TRIAGE.label} ({QWEN_TRIAGE.base_url})...")
    results = triage_events(events, QWEN_TRIAGE, metrics)

    by_scenario: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_scenario[e["scenario"]].append(results[e["id"]])

    attack = by_scenario.get("scn_phish_to_exfil", [])
    scanner = by_scenario.get("scn_noisy_scanner", [])
    baseline = by_scenario.get("baseline", [])
    all_results = list(results.values())

    scores = {
        "attack_chain_recall_high": _frac(attack, lambda r: r["risk"] == "high"),
        "attack_chain_recall_medium_or_high": _frac(attack, lambda r: r["risk"] in ("medium", "high")),
        "noisy_scanner_false_positive_rate": _frac(scanner, lambda r: r["risk"] == "high"),
        "baseline_false_positive_rate": _frac(baseline, lambda r: r["risk"] == "high"),
        "parse_reliability": _frac(all_results, lambda r: r["risk"] != "unknown"),
    }

    print_scorecard(scores)
    print()
    print(f"Sample sizes: attack chain={len(attack)}, noisy scanner={len(scanner)}, baseline={len(baseline)}, total={len(events)}")
    if metrics.triage_calls:
        print(
            f"Triage calls: {metrics.triage_calls}, errors: {metrics.errors}, "
            f"avg latency: {metrics.triage_latency_s / metrics.triage_calls:.2f}s"
        )

    return scores, metrics, dict(by_scenario)


def print_scorecard(scores: dict) -> None:
    print()
    print(f"{'Metric':42} {'Score':>8}  {'Target':>10}  Verdict")
    print("-" * 82)
    passed = 0
    for key, (target, direction) in THRESHOLDS.items():
        actual = scores[key]
        higher_is_better = direction == "higher_is_better"
        ok = (actual >= target) if higher_is_better else (actual <= target)
        passed += int(ok)
        cmp_sym = "≥" if higher_is_better else "≤"
        mark = "✅" if ok else "⚠️ "
        label = METRIC_LABELS.get(key, key)
        actual_str = "n/a" if actual != actual else f"{actual:.1%}"  # actual != actual checks NaN
        print(f"{label:42} {actual_str:>8}  {cmp_sym}{target:>8.1%}  {mark}")
    print("-" * 82)
    print(f"{passed}/{len(THRESHOLDS)} metrics within target")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--save", action="store_true", help="Save this run's scorecard to evals/results/*.json")
    args = parser.parse_args()

    scores, metrics, _ = run_eval()

    if args.save:
        out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals", "results")
        os.makedirs(out_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(out_dir, f"triage_eval_{stamp}.json")
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
        print(f"\nSaved to {path}")


if __name__ == "__main__":
    main()
