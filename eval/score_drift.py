#!/usr/bin/env python3
"""Score a drift agent's changes.json against an expected.json (the sub-goal format of schemas/submission_subgoal.schema.json).

    python eval/score_drift.py CHANGES EXPECTED --requirements-old R.json [--json out.json]
    python eval/score_drift.py --all [--runs runs/drift] [--cases spec/testing/cases-drift] [--dev runs/drift/subgoal-dev]

Offline, no model. Three questions, one per kind of change:
  flagged   the requirements the agent marks modified or removed against the experts' (by requirement_id): recall, precision, F2, the
            kind (modified / removed) of the ones both flag, and the false flags among the requirements the experts left alone
  added     the agent's added items against the experts' one to one: an item matches when it cites the same paragraph (the platform's
            key normalisation) and its text is at least ADD_SIMILARITY similar (token sequence ratio), assigned by the Hungarian method;
            `added_para` counts a match by paragraph alone
  overall   the three together as one count of items (flagged ids + added items): precision, recall, F2 = 5PR / (4P + R)
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tools")]
from score_local import _paragraph_key  # noqa: E402

ADD_SIMILARITY = 0.5


def toks(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", str(text or "").casefold())


def sim(a: str, b: str) -> float:
    x, y = toks(a), toks(b)
    return difflib.SequenceMatcher(None, x, y, autojunk=False).ratio() if x and y else 0.0


def prf(tp: int, n_pred: int, n_gold: int) -> dict:
    p = tp / n_pred if n_pred else (1.0 if not n_gold else 0.0)
    r = tp / n_gold if n_gold else 1.0
    f2 = 5 * p * r / (4 * p + r) if (4 * p + r) else 0.0
    return {"tp": tp, "pred": n_pred, "gold": n_gold, "precision": round(p, 3), "recall": round(r, 3), "f2": round(f2, 3)}


def match_added(pred: list[dict], gold: list[dict], threshold: float = ADD_SIMILARITY) -> tuple[list[tuple[int, int, float]], int]:
    """One-to-one pairs (pred index, gold index, text similarity) with the same paragraph key and similarity >= threshold, and the number
    of one-to-one pairs by paragraph alone."""
    def key(c):
        return _paragraph_key((c.get("source") or {}).get("paragraph"))

    if not pred or not gold:
        return [], 0
    s = np.zeros((len(pred), len(gold)))
    same = np.zeros((len(pred), len(gold)))
    for a, p in enumerate(pred):
        for b, g in enumerate(gold):
            if key(p) and key(p) == key(g):
                s[a, b] = sim(p.get("new_text"), g.get("new_text"))
                same[a, b] = 1
    rows, cols = linear_sum_assignment(-np.where(s >= threshold, s, 0.0))
    pairs = [(int(a), int(b), float(s[a, b])) for a, b in zip(rows, cols) if s[a, b] >= threshold]
    rows2, cols2 = linear_sum_assignment(-same)
    return pairs, int(sum(same[a, b] for a, b in zip(rows2, cols2)))


def score(changes: dict, expected: dict, requirements_old: list[dict]) -> dict:
    pred = {c["requirement_id"]: c for c in changes.get("changes", []) if c["change"] in ("modified", "removed")}
    gold = {c["requirement_id"]: c for c in expected.get("changes", []) if c["change"] in ("modified", "removed")}
    both = set(pred) & set(gold)
    kind_ok = sum(1 for i in both if pred[i]["change"] == gold[i]["change"])
    text_sim = [sim(pred[i].get("new_text"), gold[i].get("new_text")) for i in both if pred[i]["change"] == gold[i]["change"] == "modified"]
    ids = {r["id"] for r in requirements_old}
    unchanged = ids - set(gold)
    false_flags = sorted(set(pred) - set(gold))
    flagged = prf(len(both), len(pred), len(gold))
    flagged.update({"kind_accuracy": round(kind_ok / len(both), 3) if both else None, "new_text_similarity": round(sum(text_sim) / len(text_sim), 3) if text_sim else None,
                    "false_flags": len(false_flags), "unchanged": len(unchanged),
                    "false_flag_rate": round(len(false_flags) / len(unchanged), 3) if unchanged else 0.0,
                    "missed": sorted(set(gold) - set(pred)), "false_flag_ids": false_flags})
    p_add = [c for c in changes.get("changes", []) if c["change"] == "added"]
    g_add = [c for c in expected.get("changes", []) if c["change"] == "added"]
    pairs, para_pairs = match_added(p_add, g_add)
    added = prf(len(pairs), len(p_add), len(g_add))
    added["added_para"] = prf(para_pairs, len(p_add), len(g_add))
    added["unmatched_pred"] = [(p_add[a].get("source") or {}).get("paragraph") for a in range(len(p_add)) if a not in {x[0] for x in pairs}]
    added["unmatched_gold"] = [(g_add[b].get("source") or {}).get("paragraph") for b in range(len(g_add)) if b not in {x[1] for x in pairs}]
    overall = prf(flagged["tp"] + added["tp"], flagged["pred"] + added["pred"], flagged["gold"] + added["gold"])
    # lenient: a new sentence in a changed paragraph is "added" for one writer and a modified requirement for the other. A gold flagged
    # requirement is covered when the agent flags it or reports an added item at its paragraph; such an added item is not an extra.
    by_id = {r["id"]: r for r in requirements_old}
    keys = {i: {_paragraph_key((by_id.get(i, {}).get("source") or {}).get("paragraph")), _paragraph_key((g.get("source") or {}).get("paragraph"))} - {None}
            for i, g in gold.items()}
    added_keys = {_paragraph_key((c.get("source") or {}).get("paragraph")) for c in p_add}
    covered = {i for i in gold if i in pred or keys[i] & added_keys}
    gold_paras = set().union(*keys.values()) if keys else set()
    matched_pred = {x[0] for x in pairs}
    absorbed = sum(1 for a, c in enumerate(p_add) if a not in matched_pred and _paragraph_key((c.get("source") or {}).get("paragraph")) in gold_paras)
    lenient = {"flagged_recall": round(len(covered) / len(gold), 3) if gold else 1.0, "added_precision": round((len(pairs) + absorbed) / len(p_add), 3) if p_add else 1.0,
               "absorbed_added": absorbed}
    return {"flagged": flagged, "added": added, "overall": overall, "lenient": lenient}


def line(name: str, s: dict) -> str:
    f, a, o = s["flagged"], s["added"], s["overall"]
    return (f"{name:34s} flagged {f['tp']}/{f['gold']} gold, {f['pred']} pred  R {f['recall']:.2f} P {f['precision']:.2f} F2 {f['f2']:.2f}  "
            f"false {f['false_flags']}/{f['unchanged']} ({f['false_flag_rate']:.3f})  kind {f['kind_accuracy']}  |  "
            f"added {a['tp']}/{a['gold']} gold, {a['pred']} pred  R {a['recall']:.2f} P {a['precision']:.2f} (para-only {a['added_para']['tp']})  |  "
            f"overall P {o['precision']:.2f} R {o['recall']:.2f} F2 {o['f2']:.2f}  |  lenient flagged R {s['lenient']['flagged_recall']:.2f}, added P {s['lenient']['added_precision']:.2f}")


def load(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def aggregate(rows: list[tuple[str, dict]]) -> dict:
    tot = {k: {"tp": 0, "pred": 0, "gold": 0} for k in ("flagged", "added", "overall")}
    ff, un = 0, 0
    for _, s in rows:
        for k in tot:
            for f in ("tp", "pred", "gold"):
                tot[k][f] += s[k][f]
        ff += s["flagged"]["false_flags"]
        un += s["flagged"]["unchanged"]
    out = {k: prf(v["tp"], v["pred"], v["gold"]) for k, v in tot.items()}
    out["flagged"].update({"false_flags": ff, "unchanged": un, "false_flag_rate": round(ff / un, 4) if un else 0.0})
    return out


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("changes", nargs="?")
    parser.add_argument("expected", nargs="?")
    parser.add_argument("--requirements-old")
    parser.add_argument("--json", help="write the score here")
    parser.add_argument("--all", action="store_true", help="score every case of --cases against its run folder under --runs, and --dev")
    parser.add_argument("--runs", default=str(ROOT / "runs" / "drift"))
    parser.add_argument("--cases", default=str(ROOT / "spec" / "testing" / "cases-drift"))
    parser.add_argument("--dev", default="subgoal-dev", help="run folder name of subgoal/dev under --runs (scored against subgoal/dev/expected.json)")
    args = parser.parse_args(argv)
    if not args.all:
        if not (args.changes and args.expected and args.requirements_old):
            parser.error("CHANGES EXPECTED --requirements-old are required (or --all)")
        s = score(load(args.changes), load(args.expected), load(args.requirements_old))
        print(line(Path(args.changes).parent.name or "changes", s))
        print("  missed:", s["flagged"]["missed"], " false flags:", s["flagged"]["false_flag_ids"])
        print("  added unmatched (pred):", s["added"]["unmatched_pred"], " (gold):", s["added"]["unmatched_gold"])
        if args.json:
            Path(args.json).write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
        return 0
    rows = []
    dev_run = Path(args.runs) / args.dev / "changes.json"
    if dev_run.is_file():
        rows.append(("subgoal-dev", score(load(dev_run), load(ROOT / "subgoal" / "dev" / "expected.json"), load(ROOT / "subgoal" / "dev" / "requirements_old.json"))))
    for folder in sorted(Path(args.cases).iterdir()):
        run = Path(args.runs) / folder.name / "changes.json"
        if folder.is_dir() and run.is_file():
            rows.append((folder.name, score(load(run), load(folder / "expected.json"), load(folder / "requirements_old.json"))))
    for name, s in rows:
        print(line(name, s))
    cases = [r for r in rows if r[0] != "subgoal-dev"]
    if cases:
        t = aggregate(cases)
        f, a, o = t["flagged"], t["added"], t["overall"]
        print(f"{'TOTAL (10 cases)':34s} flagged {f['tp']}/{f['gold']} gold, {f['pred']} pred  R {f['recall']:.2f} P {f['precision']:.2f} F2 {f['f2']:.2f}  "
              f"false {f['false_flags']}/{f['unchanged']} ({f['false_flag_rate']:.3f})  |  added {a['tp']}/{a['gold']} gold, {a['pred']} pred  "
              f"R {a['recall']:.2f} P {a['precision']:.2f}  |  overall P {o['precision']:.2f} R {o['recall']:.2f} F2 {o['f2']:.2f}")
    if args.json:
        Path(args.json).write_text(json.dumps({n: s for n, s in rows}, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
