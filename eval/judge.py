#!/usr/bin/env python3
"""A local stand-in for the platform's requirement-level judge (spec/precision.md M1): which of our requirements state the same engineering
obligation as each expected one, matched one to one.

    python eval/judge.py runs/dev-rear-lamp/run1              # judge a run: its candidates against cases/dev-rear-lamp/expected.json

How it works. For every expected requirement the closest candidates are found by TF-IDF cosine (plus every candidate that cites the same
paragraph); a model reads each expected requirement with its candidates and says which are the same obligation (same subject, condition and
constraint; wording may differ) and which only overlap (broader, narrower, several in one, or another value). The Hungarian algorithm then
makes the matching one to one. Two numbers come out: strict (only "same" counts) and lenient ("same" or "partial" counts). The platform's
own judge is a model too and its strictness is not published, so read the pair as a range and calibrate it with one upload.

The pool is every candidate that grounded in its node, emitted or dropped, in one judging pass: matching only the emitted ones gives the
score of the submission, matching all of them gives the recall the extraction could reach, and the difference says what the policy cost.
The model that judges is the one of AI_AGENT_MODEL, as the agent itself; it is told nothing about how the candidates were made.
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]

import numpy as np  # noqa: E402
from scipy.optimize import linear_sum_assignment  # noqa: E402

from ai_agent.llm import LLM  # noqa: E402
from ai_agent.store import label_key, words  # noqa: E402

SYSTEM = """You compare engineering requirements derived from UN Regulations. For each EXPECTED requirement you get CANDIDATE requirements.

A candidate is the SAME as the expected requirement when it states the same engineering obligation: the same subject (the thing that is \
constrained), the same condition (when or where it applies) and the same constraint (the same limit, value, unit, tolerance or duty). \
Different wording, a different sentence structure and a different amount of explanation do not matter.

A candidate is PARTIAL when it overlaps with the expected requirement but is not the same: it is broader or narrower, it covers only part of the \
constraint, it merges the expected requirement with another obligation, it applies to a different case, or it states a different value.

Everything else is different: do not list it. List only the same and the partial candidates of each expected requirement, and when several \
candidates are the same, list each. An expected requirement may have none."""

SCHEMA = {"type": "object", "properties": {"judgements": {"type": "array", "items": {"type": "object", "properties": {
    "expected": {"type": "string"},
    "matches": {"type": "array", "items": {"type": "object", "properties": {
        "candidate": {"type": "string"}, "verdict": {"type": "string", "enum": ["same", "partial"]}},
        "required": ["candidate", "verdict"], "additionalProperties": False}}},
    "required": ["expected", "matches"], "additionalProperties": False}}}, "required": ["judgements"], "additionalProperties": False}


def retrieve(gold: list[dict], pool: list[dict], top_k: int = 8) -> dict[str, list[str]]:
    """For each expected requirement: the ids of the `top_k` candidates closest by TF-IDF cosine, and every candidate that cites its paragraph."""
    docs = [Counter(words(r["text"])) for r in gold] + [Counter(words(r["text"])) for r in pool]
    df = Counter(t for d in docs for t in d)
    idf = {t: math.log(1 + len(docs) / n) for t, n in df.items()}
    vec = [{t: f * idf[t] for t, f in d.items()} for d in docs]
    norm = [math.sqrt(sum(v * v for v in x.values())) or 1.0 for x in vec]
    out: dict[str, list[str]] = {}
    for gi, g in enumerate(gold):
        sims = []
        for pi, p in enumerate(pool):
            a, b = vec[gi], vec[len(gold) + pi]
            dot = sum(v * b.get(t, 0.0) for t, v in a.items())
            sims.append((dot / (norm[gi] * norm[len(gold) + pi]), pi))
        near = [pool[pi]["cid"] for s, pi in sorted(sims, reverse=True)[:top_k] if s > 0.05]
        same = [p["cid"] for p in pool if p["regulation"] == g["regulation"] and label_key(p["paragraph"]) == label_key(g["paragraph"])]
        out[g["id"]] = list(dict.fromkeys(near + same))
    return out


@dataclass
class Judged:
    verdicts: dict[str, dict[str, str]] = field(default_factory=dict)  # expected id -> {candidate id: "same" | "partial"}

    def assign(self, allowed: set[str] | None = None, lenient: bool = False) -> dict[str, str]:
        """The one-to-one matching with the most pairs (Hungarian), among `allowed` candidates; only 'same', or 'same' and 'partial'."""
        edges = {(g, c): (2 if v == "same" else 1) for g, vs in self.verdicts.items() for c, v in vs.items()
                 if (v == "same" or lenient) and (allowed is None or c in allowed)}
        golds, cands = sorted({g for g, _ in edges}), sorted({c for _, c in edges})
        if not edges:
            return {}
        weight = np.zeros((len(golds), len(cands)))
        for (g, c), w in edges.items():
            weight[golds.index(g), cands.index(c)] = w
        rows, cols = linear_sum_assignment(-weight)
        return {golds[r]: cands[c] for r, c in zip(rows, cols) if weight[r, c] > 0}


def judge(llm: LLM, gold: list[dict], pool: list[dict], batch: int = 10, workers: int = 5, log=lambda m: None) -> Judged:
    """Gold: dicts with id, text, regulation, paragraph. Pool: dicts with cid, text, regulation, paragraph."""
    near = retrieve(gold, pool)
    by_cid = {p["cid"]: p for p in pool}
    ordered = sorted(gold, key=lambda g: (g["regulation"], g["id"]))
    batches = [ordered[i:i + batch] for i in range(0, len(ordered), batch)]

    def run(group: list[dict]) -> list[dict]:
        blocks = []
        for g in group:
            cands = "\n".join(f"  {c}: {by_cid[c]['text'][:600]}" for c in near[g["id"]]) or "  (none)"
            blocks.append(f"EXPECTED {g['id']}: {g['text']}\nCANDIDATES:\n{cands}")
        user = "\n\n".join(blocks) + "\n\nFor each expected requirement, list the same and partial candidates."
        return llm.complete_json(stage="judge", label=f"{group[0]['id']}..", system=SYSTEM, user=user, schema=SCHEMA, max_tokens=12_000)["judgements"]

    out = Judged()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool_:
        for k, answer in enumerate(pool_.map(run, batches)):
            for item in answer:
                known = set(near.get(item["expected"], []))
                out.verdicts[item["expected"]] = {m["candidate"]: m["verdict"] for m in item["matches"] if m["candidate"] in known}
            log(f"[judge] batch {k + 1}/{len(batches)}")
    return out


def prf(matched: int, submitted: int, expected: int) -> dict:
    p, r = (matched / submitted if submitted else 0.0), (matched / expected if expected else 0.0)
    f1, f2 = (2 * p * r / (p + r) if p + r else 0.0), (5 * p * r / (4 * p + r) if p + r else 0.0)
    return {"matched": matched, "submitted": submitted, "expected": expected, "precision": round(p, 3), "recall": round(r, 3), "f1": round(f1, 3),
            "f2": round(f2, 3)}


def pool_from_run(candidates: list[dict]) -> list[dict]:
    """Every candidate that grounded in a node, with a stable id (C0001 ...) and whether it was emitted."""
    pool = []
    for k, c in enumerate(candidates, 1):
        if c.get("paragraph") is None:
            continue
        pool.append({"cid": f"C{k:04d}", "text": c["text"], "regulation": c["regulation"], "paragraph": c["paragraph"], "emitted": c["status"] == "emitted",
                     "status": c["status"], "applies": c.get("applies"), "index": k - 1})
    return pool


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Judge a run's candidates against an expected file with a local model.")
    parser.add_argument("run", help="a run folder (candidates.json inside)")
    parser.add_argument("--expected", default=str(ROOT / "cases" / "dev-rear-lamp" / "expected.json"))
    args = parser.parse_args(argv)
    from ai_agent.config import Settings
    from ai_agent.llm import stderr_log

    sys.stdout.reconfigure(encoding="utf-8")
    run = Path(args.run)
    gold = [{"id": r["id"], "text": r["text"], "regulation": r["source"]["regulation"], "paragraph": r["source"]["paragraph"]}
            for r in json.loads(Path(args.expected).read_text(encoding="utf-8"))["requirements"]]
    pool = pool_from_run(json.loads((run / "candidates.json").read_text(encoding="utf-8")))
    judged = judge(LLM(Settings.from_env(), log=stderr_log), gold, pool, log=stderr_log)
    emitted = {p["cid"] for p in pool if p["emitted"]}
    for name, allowed in (("emitted", emitted), ("all candidates", None)):
        for mode, lenient in (("strict", False), ("lenient", True)):
            print(f"{name:<15} {mode:<8}", json.dumps(prf(len(judged.assign(allowed, lenient)), len(emitted) if allowed else len(pool), len(gold))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
