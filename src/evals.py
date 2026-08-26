"""
Deterministic triage eval: shared logic for scripts/run_evals.py (CLI) and
pages/4_Evals.py (Streamlit) -- one place computes the scorecard, each
caller just renders it differently.

Scores the real triage pipeline against the ground-truth `scenario` labels
baked into the synthetic dataset: does it actually catch the seeded attack
chain, and does it avoid crying wolf on the noisy-scanner red herring and
plain baseline noise? Same dataset (seed=42) and temperature=0.0 every
run, so results are comparable run-to-run.
"""

from collections import defaultdict

from src.analysis import WorkMetrics, triage_events
from src.config import QWEN_TRIAGE
from src.log_generator import generate_dataset

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


def verdict(key: str, actual: float) -> bool:
    """True if `actual` for metric `key` meets its threshold."""
    target, direction = THRESHOLDS[key]
    if actual != actual:  # NaN -- empty sample, can't judge
        return False
    return actual >= target if direction == "higher_is_better" else actual <= target


def run_eval() -> tuple[dict, WorkMetrics, dict[str, list[dict]]]:
    """Runs the real triage pipeline against the ground-truth dataset and
    computes the scorecard. No printing/UI here -- callers render it."""
    events = load_ground_truth()
    metrics = WorkMetrics()
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

    return scores, metrics, dict(by_scenario)
