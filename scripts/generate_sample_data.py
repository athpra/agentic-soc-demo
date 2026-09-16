#!/usr/bin/env python3
"""Regenerate the bundled synthetic sample logs at data/sample_logs.db.

Run this if you want to change the seed or tweak the scenarios in
src/log_generator.py and refresh the checked-in sample data:

    python scripts/generate_sample_data.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.log_generator import write_dataset, SEED  # noqa: E402

if __name__ == "__main__":
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sample_logs.db")
    write_dataset(db_path, seed=SEED)
    print(f"Wrote synthetic sample logs to {db_path}")
