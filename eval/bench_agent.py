#!/usr/bin/env python3
"""Benchmark the agent on a case that has an expected answer (cases/dev-rear-lamp): the platform's own checks, then the funnel.

    python eval/bench_agent.py runs/dev-rear-lamp/run1                   # score a finished run (judge calls cost a few cents)
    python eval/bench_agent.py runs/dev-rear-lamp/run1 --no-judge        # offline numbers only
    python eval/bench_agent.py --run cases/dev-rear-lamp                 # run the agent first, then score it

What it reports (spec/proposal.md Verification, spec/precision.md M3-M5):
  1. format        tools/validate.py on submission.json: the platform runs exactly this on every upload
  2. platform      tools/score_local.py: regulation level and page level, precision / recall / F1 (and F2 = 5PR / (4P + R), the brief's measure)
  3. paragraph     the node level: which expected paragraphs are cited (an upper bound of the requirement level)
  4. requirement   eval/judge.py: a model matches ours with the expected requirements one to one; strict (same) and lenient (same or partial)
  5. funnel        regulations -> sections -> nodes -> extraction -> policy -> emitted, with the share of the expected answer still reachable
  6. errors        every expected requirement we did not match and every emitted one that did not match, tagged with where it went wrong
  7. bins          the match rate of each `applies` bin against the F2/5 bar (the threshold the policy should be tuned with)
The expected file is read here and nowhere in src/ai_agent. Run it only after the agent has finished.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools"), str(Path(__file__).resolve().parent)]

from judge import judge, pool_from_run, prf  # noqa: E402
from score_local import score as platform_score  # noqa: E402

from ai_agent import tools as agent_tools  # noqa: E402
from ai_agent.emit import validate_submission  # noqa: E402
from ai_agent.store import RegGraph, label_key  # noqa: E402


def f2(p: float, r: float) -> float:
    return 0.0 if p + r == 0 else 5 * p * r / (4 * p + r)


def pr(matched: int, submitted: int, expected: int) -> dict:
    p, r = (matched / submitted if submitted else 0.0), (matched / expected if expected else 0.0)
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0, "f2": round(f2(p, r), 3),
            "submitted": submitted, "expected": expected, "matched": matched}


def section_root(graph: RegGraph, i: int) -> tuple:
    """spec/precision.md: a depth-2 body section, or a whole annex / appendix / part scope."""
    node = graph.nodes[i]
    return (node.scope, ()) if node.scope else ("", node.num[:2])


def read(run: Path, name: str, default=None):
    path = run / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def anchors(gold: list[dict], graphs: dict[str, RegGraph]) -> dict[str, int | None]:
    """expected id -> node index: the node with the expected label whose page range holds the expected page (the gate of eval/anchors.py)."""
    found: dict[str, int | None] = {}
    for g in gold:
        s = g["source"]
        graph = graphs[s["regulation"]]
        want = label_key(s["paragraph"])
        found[g["id"]] = next((i for i, n in enumerate(graph.nodes) if n.kind in ("para", "table") and label_key(n.label) == want
                               and n.page_start <= s["page"] <= n.page_end), None)
    return found


def selected_sets(run: Path, graphs: dict[str, RegGraph]) -> tuple[dict[str, set[int]], dict[str, list[dict]]]:
    """The nodes each regulation's walk selected (rebuilt from sections.json), and per selection its nodes."""
    nodes: dict[str, set[int]] = {}
    per_selection: dict[str, list[dict]] = {}
    for reg, summary in (read(run, "sections.json", {}) or {}).items():
        graph = graphs[reg]
        items = []
        for s in summary["selections"]:
            idx = graph.resolve(s["node"])
            if idx is None:
                continue
            excl = [j for j in (graph.resolve(x) for x in s.get("exclude", [])) if j is not None]
            items.append({"idx": idx, "exclude_idx": excl, "category": s["category"], "node": s["node"]})
        nodes[reg] = set(agent_tools.expand(graph, items))
        per_selection[reg] = [{**it, "covered": set(agent_tools.expand(graph, [it]))} for it in items]
    return nodes, per_selection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark a run of the agent against the expected answer of its case.")
    parser.add_argument("run", nargs="?", help="a run folder (submission.json, candidates.json, sections.json ...)")
    parser.add_argument("--run", dest="case", help="run the agent on this case folder first (needs AI_AGENT_KEY)")
    parser.add_argument("--expected", default=str(ROOT / "cases" / "dev-rear-lamp" / "expected.json"))
    parser.add_argument("--no-judge", action="store_true", help="skip the model judge (no cost)")
    parser.add_argument("--max-cost", type=float, default=12.0)
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    judge_llm = None
    if args.case:
        from ai_agent.config import Settings
        from ai_agent.pipeline import run_case
        run = run_case(Path(args.case), Settings.from_env(max_cost_usd=args.max_cost)).run_dir
    elif args.run:
        run = Path(args.run)
    else:
        parser.error("give a run folder, or --run <case folder>")
    if not args.no_judge:
        from ai_agent.config import Settings
        from ai_agent.llm import LLM, stderr_log
        judge_llm = LLM(Settings.from_env(max_cost_usd=args.max_cost), log=stderr_log, call_log=run / "judge_calls.jsonl")

    expected = json.loads(Path(args.expected).read_text(encoding="utf-8"))
    gold = expected["requirements"]
    sub = read(run, "submission.json")
    candidates = read(run, "candidates.json", [])
    out: dict = {"run": str(run)}

    # 1. format
    problems = validate_submission(sub)
    out["format"] = {"valid": not problems, "problems": problems[:10], "requirements": len(sub["requirements"])}

    # 2. platform's own score
    plat = platform_score(sub, expected)
    out["platform"] = {level: {**{k: round(v, 3) for k, v in plat[level].items() if isinstance(v, float)},
                               **{k: v for k, v in plat[level].items() if isinstance(v, int)}, "f2": round(f2(plat[level]["precision"], plat[level]["recall"]), 3)}
                       for level in plat}

    # graphs: every regulation the gold or the run touches
    gold_regs = sorted({g["source"]["regulation"] for g in gold})
    run_regs = (read(run, "run.json", {}) or {}).get("regulations", [])
    graphs = {reg: RegGraph(reg, grids=False) for reg in sorted(set(gold_regs) | set(run_regs))}
    anchor = anchors(gold, graphs)
    gold_nodes = {(g["source"]["regulation"], anchor[g["id"]]) for g in gold if anchor[g["id"]] is not None}
    gold_roots = {(reg, section_root(graphs[reg], i)) for reg, i in gold_nodes}
    unanchored = [g["id"] for g in gold if anchor[g["id"]] is None]

    # 3. paragraph level
    cited = {(r["source"]["regulation"], label_key(r["source"]["paragraph"])) for r in sub["requirements"]}
    wanted = {(g["source"]["regulation"], label_key(g["source"]["paragraph"])) for g in gold}
    out["paragraph"] = pr(len(cited & wanted), len(cited), len(wanted))

    # 5a. regulations and sections
    chosen = set(run_regs)
    out["funnel"] = {"regulations": {**pr(len(chosen & set(gold_regs)), len(chosen), len(gold_regs)), "chosen": sorted(chosen), "missed": sorted(set(gold_regs) - chosen),
                                     "extra": sorted(chosen - set(gold_regs))}}
    sel, per_selection = selected_sets(run, graphs)
    reach = {g["id"]: anchor[g["id"]] is not None and anchor[g["id"]] in sel.get(g["source"]["regulation"], set()) for g in gold}
    content_selected = {reg: {i for i in nodes if graphs[reg].is_content(i)} for reg, nodes in sel.items()}
    reached_nodes = {(reg, i) for reg, i in gold_nodes if i in content_selected.get(reg, set())}
    n_selected = sum(len(v) for v in content_selected.values())
    out["funnel"]["sections"] = {"gold_requirements_reachable": f"{sum(reach.values())}/{len(gold)}", "recall": round(sum(reach.values()) / len(gold), 3),
                                 "selected_provisions": n_selected, "gold_nodes_reached": f"{len(reached_nodes)}/{len(gold_nodes)}",
                                 "node_precision": round(len(reached_nodes) / n_selected, 3) if n_selected else 0.0,
                                 "by_regulation": {reg: {"selected": len(content_selected.get(reg, ())), "gold_nodes_reached": sum(1 for r, i in reached_nodes if r == reg),
                                                          "gold_nodes": sum(1 for r, i in gold_nodes if r == reg),
                                                          "requirements_reachable": sum(1 for g in gold if g["source"]["regulation"] == reg and reach[g["id"]]),
                                                          "requirements": sum(1 for g in gold if g["source"]["regulation"] == reg)} for reg in gold_regs}}
    by_category: dict[str, dict] = defaultdict(lambda: {"selected": 0, "gold_nodes": 0, "selections": 0})
    for reg, items in per_selection.items():
        for it in items:
            content = {i for i in it["covered"] if graphs[reg].is_content(i)}
            row = by_category[it["category"]]
            row["selections"] += 1
            row["selected"] += len(content)
            row["gold_nodes"] += sum(1 for r, i in gold_nodes if r == reg and i in content)
    out["funnel"]["sections"]["by_category"] = {k: {**v, "match_rate": round(v["gold_nodes"] / v["selected"], 3) if v["selected"] else 0.0} for k, v in by_category.items()}

    # 5b. extraction and policy
    status = Counter(c["status"].split("=")[0] if c["status"].startswith("dropped") else c["status"] for c in candidates)
    at_anchor = {(c["regulation"], c["node"]) for c in candidates if c.get("node")}
    extracted_at_anchor = {g["id"]: (g["source"]["regulation"], graphs[g["source"]["regulation"]].ids[anchor[g["id"]]]) in at_anchor
                           for g in gold if anchor[g["id"]] is not None}
    out["funnel"]["extraction"] = {"candidates": len(candidates), "by_status": dict(status),
                                   "grounded": sum(1 for c in candidates if c.get("node")), "reassigned": sum(1 for c in candidates if c.get("reassigned")),
                                   "gold_with_a_candidate_at_its_node": f"{sum(extracted_at_anchor.values())}/{len(gold)}"}

    # 4. requirement level (the judge) and the error taxonomy
    judged = None
    if judge_llm is not None:
        pool = pool_from_run(candidates)
        gold_items = [{"id": g["id"], "text": g["text"], "regulation": g["source"]["regulation"], "paragraph": g["source"]["paragraph"]} for g in gold]
        judged = judge(judge_llm, gold_items, pool, log=lambda m: None)
        emitted = {p["cid"] for p in pool if p["emitted"]}
        by_cid = {p["cid"]: p for p in pool}
        strict, lenient = judged.assign(emitted, False), judged.assign(emitted, True)
        ceiling, ceiling_lenient = judged.assign(None, False), judged.assign(None, True)
        n_out = len(sub["requirements"])
        out["requirement"] = {"strict": pr(len(strict), n_out, len(gold)), "lenient": pr(len(lenient), n_out, len(gold)),
                              "ceiling_all_candidates_strict": pr(len(ceiling), len(pool), len(gold))["recall"],
                              "ceiling_all_candidates_lenient": pr(len(ceiling_lenient), len(pool), len(gold))["recall"]}
        out["funnel"]["extraction"]["gold_with_a_matching_candidate_strict"] = f"{len(ceiling)}/{len(gold)}"
        # false negatives
        fn = Counter()
        fn_rows = []
        for g in gold:
            gid, reg = g["id"], g["source"]["regulation"]
            if gid in strict:
                tag = "found"
            elif reg not in chosen:
                tag = "regulation not chosen"
            elif anchor[gid] is None:
                tag = "no node for the expected paragraph (parser)"
            elif not reach[gid]:
                tag = "section not selected"
            elif gid in ceiling:
                c = by_cid[ceiling[gid]]
                tag = "lost in one-to-one matching" if c["emitted"] else f"dropped by policy: {c['status'].split(':', 1)[1] if ':' in c['status'] else c['status']}"
            elif extracted_at_anchor.get(gid):
                tag = "extracted at the node, wording differs"
            else:
                tag = "not extracted"
            fn[tag] += 1
            fn_rows.append({"id": gid, "regulation": reg, "paragraph": g["source"]["paragraph"], "tag": tag, "text": g["text"][:140]})
        out["errors_expected"] = dict(fn.most_common())
        # false positives (emitted, not matched)
        matched_cids = set(strict.values())
        partial_cids = set(lenient.values()) - matched_cids
        fp = Counter()
        fp_rows = []
        for p in pool:
            if not p["emitted"]:
                continue
            reg = p["regulation"]
            node_idx = graphs[reg].resolve(p["paragraph"])
            if p["cid"] in matched_cids:
                tag = "matched"
            elif p["cid"] in partial_cids:
                tag = "partial match (lenient only)"
            elif reg not in gold_regs:
                tag = "wrong regulation"
            elif node_idx is None or (reg, section_root(graphs[reg], node_idx)) not in gold_roots:
                tag = "section the expected answer does not use"
            elif (reg, node_idx) not in gold_nodes:
                tag = "right section, paragraph the expected answer does not cite"
            else:
                tag = "cited paragraph, wording or granularity differs"
            fp[tag] += 1
            fp_rows.append({"cid": p["cid"], "regulation": reg, "paragraph": p["paragraph"], "tag": tag, "applies": p["applies"], "text": p["text"][:140]})
        out["errors_emitted"] = dict(fp.most_common())
        # bins
        bar = f2(out["requirement"]["strict"]["precision"], out["requirement"]["strict"]["recall"]) / 5
        bins = {}
        for level in ("certain", "likely", "possible", "unlikely"):
            members = [p for p in pool if p["applies"] == level]
            emitted_members = [p for p in members if p["emitted"]]
            would = {p["cid"] for p in members if p["cid"] in set(ceiling.values())}
            bins[level] = {"candidates": len(members), "emitted": len(emitted_members), "matched_when_emitted": sum(1 for p in emitted_members if p["cid"] in matched_cids),
                           "match_rate_emitted": round(sum(1 for p in emitted_members if p["cid"] in matched_cids) / len(emitted_members), 3) if emitted_members else None,
                           "same_as_an_expected_requirement": len(would), "share_that_are_same": round(len(would) / len(members), 3) if members else None}
        out["bins"] = {"bar_f2_over_5": round(bar, 3), **bins}
        out["judge_cost_usd"] = round(judge_llm.ledger.spent, 3)
        (run / "bench_errors.json").write_text(json.dumps({"expected": fn_rows, "emitted": fp_rows}, ensure_ascii=False, indent=1), encoding="utf-8")
        (run / "judge_verdicts.json").write_text(json.dumps({"verdicts": judged.verdicts, "strict": strict, "lenient": lenient,
                                                              "pool": {p["cid"]: {k: p[k] for k in ("regulation", "paragraph", "emitted", "status", "applies", "index")}
                                                                       for p in pool}}, ensure_ascii=False, indent=1), encoding="utf-8")

    usage = read(run, "usage.json", {}) or {}
    out["cost"] = {"agent_spent_usd": usage.get("spent_usd"), "agent_replayed_usd": usage.get("replayed_usd"),
                   "seconds": (read(run, "run.json", {}) or {}).get("seconds"), "stages": {k: v["spent"] + v["replayed"] for k, v in usage.get("stages", {}).items()}}
    out["unanchored_expected"] = unanchored
    (run / "bench.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print_report(out)
    return 0 if out["format"]["valid"] else 1


def line(label: str, d: dict) -> str:
    return (f"  {label:<26}{d['precision']:>7.3f}{d['recall']:>8.3f}{d.get('f1', 0):>7.3f}{d.get('f2', 0):>7.3f}"
            f"   {d.get('n_submitted', d.get('submitted', ''))} / {d.get('n_expected', d.get('expected', ''))} / {d.get('n_matched', d.get('matched', ''))}")


def print_report(o: dict) -> None:
    print(f"\nRun {o['run']}")
    f = o["format"]
    print(f"\n1. format (tools/validate.py): {'OK' if f['valid'] else 'PROBLEMS'} - {f['requirements']} requirements" + ("" if f["valid"] else f"\n   {f['problems']}"))
    print("\n2-4. scores                      P       R     F1     F2   submitted / expected / matched")
    print(line("regulation level", o["platform"]["regulation_level"]))
    print(line("page level", o["platform"]["page_level"]))
    print(line("paragraph level (nodes)", o["paragraph"]))
    if "requirement" in o:
        print(line("requirement, strict judge", o["requirement"]["strict"]))
        print(line("requirement, lenient judge", o["requirement"]["lenient"]))
        print(f"  recall ceiling of all candidates (strict / lenient): {o['requirement']['ceiling_all_candidates_strict']} / {o['requirement']['ceiling_all_candidates_lenient']}")
    fu = o["funnel"]
    print(f"\n5. funnel\n  regulations: chosen {fu['regulations']['chosen']}  missed {fu['regulations']['missed']}  extra {fu['regulations']['extra']}")
    s = fu["sections"]
    print(f"  sections:    {s['gold_requirements_reachable']} expected requirements inside the selected parts (recall {s['recall']}); {s['selected_provisions']} provisions selected, "
          f"{s['gold_nodes_reached']} expected paragraphs among them (precision {s['node_precision']})")
    for reg, row in s["by_regulation"].items():
        print(f"      {reg:<9} {row['requirements_reachable']}/{row['requirements']} requirements reachable, {row['gold_nodes_reached']}/{row['gold_nodes']} paragraphs, {row['selected']} provisions selected")
    print("      by category of selection: " + "; ".join(f"{k} {v['gold_nodes']}/{v['selected']} ({v['match_rate']:.0%})" for k, v in s["by_category"].items()))
    e = fu["extraction"]
    print(f"  extraction:  {e['candidates']} candidates {e['by_status']}; expected requirements with a candidate at their node {e['gold_with_a_candidate_at_its_node']}"
          + (f", with a candidate that is the same obligation {e['gold_with_a_matching_candidate_strict']}" if "gold_with_a_matching_candidate_strict" in e else ""))
    if "errors_expected" in o:
        print("\n6. expected requirements, by what happened to them")
        for k, v in o["errors_expected"].items():
            print(f"  {v:>4}  {k}")
        print("   emitted requirements, by what they are")
        for k, v in o["errors_emitted"].items():
            print(f"  {v:>4}  {k}")
        b = o["bins"]
        print(f"\n7. applies bins (F2/5 bar = {b['bar_f2_over_5']})")
        for level in ("certain", "likely", "possible", "unlikely"):
            r = b[level]
            print(f"  {level:<9} candidates {r['candidates']:>4}  emitted {r['emitted']:>4}  matched {r['matched_when_emitted']:>3}  match rate {r['match_rate_emitted']}  "
                  f"same-as-expected share {r['share_that_are_same']}")
    c = o["cost"]
    print(f"\ncost: agent ${c['agent_spent_usd']} (replayed ${c['agent_replayed_usd']}), {c['seconds']}s" + (f"; judge ${o['judge_cost_usd']}" if "judge_cost_usd" in o else ""))
    print(f"files: {o['run']}/bench.json" + (", bench_errors.json" if "errors_expected" in o else ""))


if __name__ == "__main__":
    raise SystemExit(main())
