# Evaluating the triage agent

`scripts/run_evals.py` (CLI) and `pages/4_Evals.py` (in-app, with charts and a saved-run trend
view) are both thin wrappers around `src/evals.py` — one deterministic eval that runs the real
triage pipeline against the bundled dataset and scores the results against the dataset's
ground-truth `scenario` labels: does it actually catch the seeded attack chain, and does it
avoid crying wolf on the noisy-scanner red herring and plain baseline noise? Same dataset
(seed=42) and `temperature=0.0` every run, so results are comparable across runs — rerun it
after any prompt or model change to see whether it actually helped, not just whether it "seems
better." The in-app page's "Save this scorecard" button writes to the same `evals/results/`
directory the CLI's `--save` flag does, so a history built from either shows up in both.

```bash
python scripts/run_evals.py            # print a scorecard
python scripts/run_evals.py --save     # also write it to evals/results/*.json
```

Scored metrics, against thresholds defined at the top of the script:

| Metric | What it checks |
|---|---|
| Attack chain caught as HIGH | Recall on the 7 real attack-chain events, strict bar |
| Attack chain caught as MEDIUM+ | Recall on the same events, looser bar (at least flagged for a second look) |
| Noisy scanner wrongly flagged HIGH | False-positive rate on the benign-but-noisy red herring |
| Baseline noise wrongly flagged HIGH | False-positive rate on routine, uninteresting activity |
| Valid, parseable triage result | How often the model returns strict, parseable JSON |

Needs the same auth as the rest of the app — see [auth.md](auth.md).
