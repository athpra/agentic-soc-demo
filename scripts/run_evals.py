#!/usr/bin/env python3
"""
Deterministic triage eval (CLI).

Scores Qwen2.5-7B-Instruct's real triage output against the ground-truth
`scenario` labels baked into the synthetic dataset (src/log_generator.py) --
does it actually catch the seeded attack chain, and does it avoid crying
wolf on the noisy-scanner red herring and plain baseline noise? Rerun this
after any prompt or model change to see whether it actually helped.

Also runnable from the app itself: see pages/4_Evals.py. Both share the
same scoring logic in src/evals.py.

Usage:
    python scripts/run_evals.py [--save]

Requires the same auth as the rest of this app: run inside a Cloudera AI
Workbench Session/Application/Job, or export CDP_TOKEN locally.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import QWEN_TRIAGE  # noqa: E402
from src.evals import METRIC_LABELS, THRESHOLDS, run_eval, verdict  # noqa: E402


def print_scorecard(scores: dict) -> None:
    print()
    print(f"{'Metric':42} {'Score':>8}  {'Target':>10}  Verdict")
    print("-" * 82)
    passed = 0
    for key, (target, direction) in THRESHOLDS.items():
        actual = scores[key]
        ok = verdict(key, actual)
        passed += int(ok)
        cmp_sym = "≥" if direction == "higher_is_better" else "≤"
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

    print(f"Triaging against {QWEN_TRIAGE.label} ({QWEN_TRIAGE.base_url})...")
    scores, metrics, by_scenario = run_eval()

    print_scorecard(scores)
    print()
    print(
        f"Sample sizes: attack chain={len(by_scenario.get('scn_phish_to_exfil', []))}, "
        f"noisy scanner={len(by_scenario.get('scn_noisy_scanner', []))}, "
        f"baseline={len(by_scenario.get('baseline', []))}"
    )
    if metrics.triage_calls:
        print(
            f"Triage calls: {metrics.triage_calls}, errors: {metrics.errors}, "
            f"avg latency: {metrics.triage_latency_s / metrics.triage_calls:.2f}s"
        )

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
