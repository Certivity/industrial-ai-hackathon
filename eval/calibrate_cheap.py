#!/usr/bin/env python3
"""Calibrate the cheap proxy: page-level upper bound (upper_bound.json of a --stop-after sections run) against the real page level of a full run.

    python eval/calibrate_cheap.py                         # the 6 ts-* cases of testing/_benched.json and the dev case
    python eval/calibrate_cheap.py --ub-name cheap-base    # the run folder name of the cheap runs

No model calls. Prints a markdown table: real and upper-bound page P / R / F2 per case, the recall kept (real R / UB R) and the precision ratio.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tools")]
from score_local import score  # noqa: E402


def f2(p: float, r: float) -> float:
    return 0.0 if 4 * p + r == 0 else 5 * p * r / (4 * p + r)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ub-name", default="cheap-base")
    parser.add_argument("--benched", default="testing/_benched.json")
    parser.add_argument("--dev-submission", default="outputs/dev-rear-lamp/submission.json")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    pairs = {case: (ROOT / "testing" / case / "expected.json", ROOT / v["run"] / "submission.json") for case, v in load(ROOT / args.benched).items()}
    pairs["dev-rear-lamp"] = (ROOT / "cases/dev-rear-lamp/expected.json", ROOT / args.dev_submission)
    rows = []
    print("| case | real page P | real page R | real page F2 | UB page P | UB page R | UB page F2 | R kept (real R / UB R) | P ratio (real P / UB P) | real reg F2 | UB reg F2 |\n" + "|" + "---|" * 11)
    for case, (expected_path, sub_path) in pairs.items():
        ub_path = ROOT / "runs" / case / args.ub_name / "upper_bound.json"
        if not ub_path.is_file():
            print(f"| {case} | no {ub_path.relative_to(ROOT)} |" + " |" * 9)
            continue
        expected = load(expected_path)
        real, ub = score(load(sub_path), expected), score(load(ub_path), expected)
        rp, ur = real["page_level"], ub["page_level"]
        kept = rp["recall"] / ur["recall"] if ur["recall"] else float("nan")
        ratio = rp["precision"] / ur["precision"] if ur["precision"] else float("nan")
        rows.append((rp, ur, kept, ratio))
        print(f"| {case} | {rp['precision']:.2f} | {rp['recall']:.2f} | {f2(rp['precision'], rp['recall']):.2f} | {ur['precision']:.2f} | {ur['recall']:.2f} "
              f"| {f2(ur['precision'], ur['recall']):.2f} | {kept:.2f} | {ratio:.2f} "
              f"| {f2(real['regulation_level']['precision'], real['regulation_level']['recall']):.2f} | {f2(ub['regulation_level']['precision'], ub['regulation_level']['recall']):.2f} |")
    if rows:
        n = len(rows)
        mean = lambda i, k: sum(r[i][k] for r in rows) / n  # noqa: E731
        print(f"| **mean of {n}** | {mean(0, 'precision'):.2f} | {mean(0, 'recall'):.2f} | {sum(f2(r[0]['precision'], r[0]['recall']) for r in rows) / n:.2f} "
              f"| {mean(1, 'precision'):.2f} | {mean(1, 'recall'):.2f} | {sum(f2(r[1]['precision'], r[1]['recall']) for r in rows) / n:.2f} "
              f"| {sum(r[2] for r in rows) / n:.2f} | {sum(r[3] for r in rows) / n:.2f} | | |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
