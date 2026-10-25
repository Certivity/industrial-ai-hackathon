#!/usr/bin/env python3
"""Regulation-level P/R/F1/F2 of agent runs against the original gold and against the audited set (testing/_audited_regs.json).

  python eval/score_audited.py --runs c2-base c2-vet2 c2-v2            # runs/<case>/<name>, split by testing/_split.json
  python eval/score_audited.py --runs-map testing/_benched.json        # {case: run_dir} or {case: {run: run_dir}}
  python eval/score_audited.py --runs c2-base --json out.json

The submitted set of a run is the regulations of its upper_bound.json (what tools/score_local.py scores). The audited positives are
the candidates with a majority of yes votes (eval/audit_regs.py). A regulation a run cites that was never a candidate is not audited:
it counts as negative and is listed under `unaudited` (rerun audit_regs for new runs). Page level: only the regulations both the
original gold and the audit accept, gold and submission both cut to them, with tools/score_local.py. Std is the sample std over cases.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tools")]
import score_local  # noqa: E402


def rj(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def prf(sub: set, ref: set) -> dict:
    m = len(sub & ref)
    p = m / len(sub) if sub else 0.0
    r = m / len(ref) if ref else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    f2 = 5 * p * r / (4 * p + r) if 4 * p + r else 0.0
    return {"P": p, "R": r, "F1": f1, "F2": f2}


def mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mu = sum(values) / len(values)
    sd = (sum((v - mu) ** 2 for v in values) / (len(values) - 1)) ** 0.5 if len(values) > 1 else 0.0
    return mu, sd


def audited_sets(audit: dict) -> dict:
    out = {}
    for case, rec in audit["cases"].items():
        out[case] = {"candidates": {c["regulation"] for c in rec["candidates"]},
                     "positive": {c["regulation"] for c in rec["candidates"] if c.get("applies")}}
    return out


def score_run(case: str, run: Path, aud: dict) -> dict | None:
    ub = rj(run / "upper_bound.json")
    if ub is None:
        return None
    gold_doc = rj(ROOT / "testing" / case / "expected.json")
    gold = {r["source"]["regulation"] for r in gold_doc["requirements"]}
    sub = {r["source"]["regulation"] for r in ub["requirements"]}
    pos = aud["positive"]
    both = gold & pos
    row = {"case": case, "gold": sorted(gold), "audited": sorted(pos), "run": sorted(sub),
           "vs_gold": prf(sub, gold), "vs_audit": prf(sub, pos),
           "gold_rejected": sorted(gold - pos), "agent_only_accepted": sorted((sub - gold) & pos),
           "agent_only_rejected": sorted((sub - gold) - pos), "audit_only_missed": sorted(pos - sub - gold),
           "unaudited": sorted(sub - aud["candidates"])}
    keep = lambda doc: {**doc, "requirements": [r for r in doc["requirements"] if r["source"]["regulation"] in both]}  # noqa: E731
    if both:
        s = score_local.score(keep(ub), keep(gold_doc))["page_level"]
        row["page_on_agreed"] = {"P": s["precision"], "R": s["recall"], "F1": s["f1"],
                                 "F2": 5 * s["precision"] * s["recall"] / (4 * s["precision"] + s["recall"]) if s["precision"] + s["recall"] else 0.0}
    return row


def table(rows: list[dict], label: str) -> str:
    keys = ("P", "R", "F1", "F2")
    lines = [f"| {label} (n={len(rows)}) | " + " | ".join(f"{k}" for k in keys) + " |", "|---|" + "---|" * len(keys)]
    for name, getter in (("regulation vs original gold", lambda r: r["vs_gold"]), ("regulation vs audited set", lambda r: r["vs_audit"]),
                         ("page on agreed regs (gold and audit accept)", lambda r: r.get("page_on_agreed"))):
        sel = [g for g in map(getter, rows) if g]
        cells = []
        for k in keys:
            mu, sd = mean_std([g[k] for g in sel])
            cells.append(f"{mu:.2f} ± {sd:.2f}")
        lines.append(f"| {name} (n={len(sel)}) | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="*", default=[], help="run folder names under runs/<case>/")
    ap.add_argument("--runs-map", help="JSON {case: run_dir} or {case: {name: run_dir}}")
    ap.add_argument("--audit", default=str(ROOT / "testing" / "_audited_regs.json"))
    ap.add_argument("--split", default=str(ROOT / "testing" / "_split.json"))
    ap.add_argument("--json", help="write the per-case rows here")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    audit = audited_sets(json.loads(Path(args.audit).read_text(encoding="utf-8")))
    split = rj(Path(args.split), {}) or {}
    variants: dict[str, dict[str, Path]] = {}
    for name in args.runs:
        variants[name] = {c: ROOT / "runs" / c / name for c in audit}
    if args.runs_map:
        for case, v in json.loads(Path(args.runs_map).read_text(encoding="utf-8")).items():
            v = v if isinstance(v, dict) else {"map": v}
            for name, d in v.items():
                d = d.get("run") if isinstance(d, dict) else d
                variants.setdefault(name, {})[case] = ROOT / d
    parts = {"tune": split.get("tune", []), "heldout": split.get("heldout", []), "all": list(audit)}
    out = {}
    for name, cases in variants.items():
        rows = [r for c, run in cases.items() if c in audit and (r := score_run(c, run, audit[c]))]
        out[name] = rows
        print(f"\n## {name}\n")
        for part, ids in parts.items():
            sel = [r for r in rows if r["case"] in ids]
            if sel:
                print(table(sel, part) + "\n")
        gr = sorted(r for row in rows for r in [f"{row['case']}:{x}" for x in row["gold_rejected"]])
        ao = sorted(f"{row['case']}:{x}" for row in rows for x in row["agent_only_accepted"])
        un = sorted(f"{row['case']}:{x}" for row in rows for x in row["unaudited"])
        print(f"gold regulations rejected by the audit: {len(gr)}; agent-only regulations accepted: {len(ao)}" + (f"; unaudited: {un}" if un else ""))
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
