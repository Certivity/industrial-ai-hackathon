#!/usr/bin/env python3
"""Benchmark the extraction stage alone on an independent expert set: UN R175 and the 94 requirements of subgoal/dev/requirements_old.json.

    python eval/bench_extract.py                  # extract from all of R175 base, judge against requirements_old.json
    python eval/bench_extract.py --tag v2         # name the run (runs/extract-r175/<tag>/)

Why it exists. The dev case (cases/dev-rear-lamp) is one product: tuning the extraction prompt on its expected answer would fit that answer, not the
experts' habits. requirements_old.json is a second expert-written set, for a regulation the dev case does not use, with the same job (paragraph ->
atomic requirements) and about the same density (1.65 requirements per paragraph, 1.57 in the dev gold). Here nothing is selected and the profile says
that everything applies, so the numbers isolate what the extraction stage does with the text: does it find every paragraph the experts used, is a
requirement worded and split as theirs, are conditions and exceptions kept.

Every candidate whose modality is "obligation" counts as emitted here (the R175 set includes the applicant's and the authority's duties, which the main
goal's policy would drop). Scores come from eval/judge.py: strict (same obligation) and lenient (same or partial), matched one to one.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools"), str(Path(__file__).resolve().parent)]

from judge import judge, pool_from_run, prf  # noqa: E402

from ai_agent.config import Settings  # noqa: E402
from ai_agent.llm import LLM, stderr_log  # noqa: E402
from ai_agent.obligations import EXAMPLE_PARAGRAPHS, extract_all  # noqa: E402
from ai_agent.store import RegGraph, label_key  # noqa: E402

REG = "UN R175"
PROFILE = ("Product: a motor vehicle of category M1 or N1 fitted with an acceleration control for pedal error (ACPE) system, and the manufacturer that "
           "applies for its approval.\nEvery provision of the regulation is meant to apply to this product and its approval: grade each one 'certain' "
           "unless it is plainly about something else.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extraction-only benchmark on UN R175 against subgoal/dev/requirements_old.json.")
    parser.add_argument("--tag", default=time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--max-cost", type=float, default=3.0)
    parser.add_argument("--effort", help="effort of the obligations stage (default from Settings)")
    parser.add_argument("--chunk-chars", type=int)
    parser.add_argument("--no-cache", action="store_true", help="sample again instead of replaying identical requests (to measure the noise of a setting)")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    out_dir = ROOT / "runs" / "extract-r175" / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    overrides = {**({"chunk_chars": args.chunk_chars} if args.chunk_chars else {}), **({"cache_dir": None} if args.no_cache else {})}
    settings = Settings.from_env(max_cost_usd=args.max_cost, **overrides)
    if args.effort:
        settings = settings.with_effort(obligations=args.effort)
    llm = LLM(settings, log=stderr_log, call_log=out_dir / "calls.jsonl")
    gold = json.loads((ROOT / "subgoal" / "dev" / "requirements_old.json").read_text(encoding="utf-8"))
    gold = gold["requirements"] if isinstance(gold, dict) else gold

    graph = RegGraph(REG)
    nodes = {REG: list(range(len(graph.nodes)))}
    candidates, plan, failures, chunk_stats = extract_all(llm, {REG: graph}, nodes, PROFILE, settings.workers, settings.chunk_chars, stderr_log)
    for c in candidates:
        c["status"] = "emitted" if c.get("node") and c["modality"] == "obligation" else (c.get("status") or f"dropped:modality={c['modality']}")
    (out_dir / "candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=1), encoding="utf-8")

    # the paragraphs shown as examples in the extraction prompt are not graded: neither their expert requirements nor our candidates there
    shown = {label_key(p) for p in EXAMPLE_PARAGRAPHS}
    gold = [r for r in gold if label_key(r["source"]["paragraph"]) not in shown]
    pool = [p for p in pool_from_run(candidates) if label_key(p["paragraph"]) not in shown]
    items = [{"id": r["id"], "text": r["text"], "regulation": REG, "paragraph": r["source"]["paragraph"]} for r in gold]
    judged = judge(llm, items, pool)
    emitted = {p["cid"] for p in pool if p["emitted"]}
    strict, lenient = judged.assign(emitted, False), judged.assign(emitted, True)
    ceiling = judged.assign(None, False)
    wanted = Counter(label_key(r["source"]["paragraph"]) for r in gold)
    ours = Counter(label_key(p["paragraph"]) for p in pool if p["emitted"])
    covered = [k for k in wanted if ours.get(k)]
    report = {
        "tag": args.tag, "chunks": sum(len(v) for v in plan.values()), "candidates": len(candidates), "emitted": len(emitted),
        "by_status": dict(Counter(c["status"].split("=")[0] if c["status"].startswith("dropped") else c["status"] for c in candidates)),
        "strict": prf(len(strict), len(emitted), len(gold)), "lenient": prf(len(lenient), len(emitted), len(gold)),
        "graded_expected": len(gold), "left_out_example_paragraphs": sorted(shown), "chunk_stats": chunk_stats,
        "paragraphs_expected": len(wanted), "paragraphs_with_a_candidate": len(covered),
        "per_paragraph_expected": round(len(gold) / len(wanted), 2), "per_paragraph_ours": round(len(emitted) / max(1, len({label_key(p['paragraph']) for p in pool if p['emitted']})), 2),
        "recall_ceiling_all_candidates_strict": round(len(ceiling) / len(gold), 3), "failures": failures,
        "cost_usd": round(llm.ledger.spent + llm.ledger.replayed, 3)}
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "judge_verdicts.json").write_text(json.dumps({"verdicts": judged.verdicts, "strict": strict, "lenient": lenient}, indent=1), encoding="utf-8")
    print(f"\nR175 extraction benchmark ({args.tag}): {len(candidates)} candidates, {len(emitted)} obligations, {report['chunks']} chunks, ${report['cost_usd']}")
    for name in ("strict", "lenient"):
        r = report[name]
        print(f"  {name:<8} P {r['precision']:.3f}  R {r['recall']:.3f}  F1 {r['f1']:.3f}  F2 {r['f2']:.3f}   matched {r['matched']} / submitted {r['submitted']} / expected {r['expected']}")
    print(f"  paragraphs the experts used: {len(covered)}/{len(wanted)} have a candidate; requirements per paragraph: experts {report['per_paragraph_expected']}, "
          f"ours {report['per_paragraph_ours']}; recall ceiling of all candidates (strict) {report['recall_ceiling_all_candidates_strict']}")
    print(f"  files: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
