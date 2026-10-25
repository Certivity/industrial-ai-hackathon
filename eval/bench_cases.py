#!/usr/bin/env python3
"""Run the agent on a set of cases that have an expected.json, score each run, and write one results table.

    python eval/bench_cases.py testing/ts-*                          # run what has no run yet, then score
    python eval/bench_cases.py testing/ts-* --judge ts-a ts-b        # also the model judge (about $0.4 each) for these two
    python eval/bench_cases.py testing/ts-* --reuse                  # never start the agent; score the runs that exist
    python eval/bench_cases.py testing/ts-* --runs-map testing/_benched.json   # take run folders from a map {case: run_dir}

Cheap mode (spec/finding/cheap-bench.md): `--stop-after sections` stops every run before the obligation extraction (about $0.3-0.5 a case, $0 when
the requests replay) and scores upper_bound.json, a pseudo-submission citing every selected node once: the regulation level is exact, the page
level is a recall ceiling. Results go to testing/results-cheap/ and testing/RESULTS-cheap.md (never testing/RESULTS.md):

    python eval/bench_cases.py testing/ts-* cases/dev-rear-lamp --stop-after sections --split testing/_split.json --part tune

For each case folder (a glob works; the Windows shell does not expand it, so this script does):
  1. the run folder: from --runs-map, else runs/<case>/latest.txt when that run has a submission.json (nothing is paid twice),
     else `src/ai_agent/run.py <case> --out runs/<case>/<name> --max-cost M` at the default efforts; latest.txt is then written
  2. tools/validate.py --strict on its submission.json
  3. tools/score_local.py --expected <case>/expected.json: regulation and page level, P / R / F1 and F2 = 5PR / (4P + R)
  4. eval/bench_agent.py <run> --expected <case>/expected.json (--no-judge unless the case is in --judge): the paragraph level,
     the funnel and, with the judge, the strict and lenient requirement level
  5. the cost of the run (usage.json: spent plus replayed from the request cache) and of the judge
The per-case JSON goes to --out-dir (default testing/results/<case>.json), the table to --results (default testing/RESULTS.md).
Starting a run is refused when the money already spent plus --max-cost would pass --budget. The expected.json is read only after
the run has finished; src/ai_agent never sees it. Needs the hackathon python (PyMuPDF, anthropic) and AI_AGENT_KEY in .env.
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import glob
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def f2(p: float, r: float) -> float:
    return 0.0 if 4 * p + r == 0 else 5 * p * r / (4 * p + r)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def run_tool(args: list[str], log: Path | None = None) -> subprocess.CompletedProcess:
    done = subprocess.run([PY, *args], cwd=ROOT, env=ENV, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(done.stdout + "\n--- stderr ---\n" + done.stderr, encoding="utf-8")
    return done


def spent_of(run: Path) -> float:
    usage = read_json(run / "usage.json", {}) or {}
    return round(float(usage.get("spent_usd", 0)) + float(usage.get("replayed_usd", 0)), 3)


class Budget:
    def __init__(self, limit: float, already: float) -> None:
        self.limit, self.spent, self.lock = limit, already, threading.Lock()

    def reserve(self, amount: float) -> bool:
        with self.lock:
            if self.spent + amount > self.limit:
                return False
            self.spent += amount  # the worst case; settle() puts the real figure in its place
            return True

    def settle(self, reserved: float, actual: float) -> None:
        with self.lock:
            self.spent += actual - reserved


def find_run(case: Path, runs_map: dict, reuse: bool) -> Path | None:
    if case.name in runs_map:
        entry = runs_map[case.name]
        run = ROOT / (entry["run"] if isinstance(entry, dict) else entry)
        return run if (run / "submission.json").is_file() else None
    latest = ROOT / "runs" / case.name / "latest.txt"
    if latest.is_file():
        run = ROOT / latest.read_text(encoding="utf-8").strip()
        if (run / "submission.json").is_file():
            return run
    return None


def taxonomy(sub: dict, expected: dict) -> dict:
    """What went wrong at regulation and paragraph level: wrong regulations (cited, not in the gold), missed regulations, and per
    regulation the gold paragraphs the run did not cite and the paragraphs it cited that the gold does not."""
    sys.path[:0] = [str(ROOT / "tools")]
    from score_local import _paragraph_key

    def paragraphs(doc: dict) -> dict[str, set]:
        out: dict[str, set] = {}
        for r in doc["requirements"]:
            out.setdefault(r["source"]["regulation"], set()).add(_paragraph_key(r["source"]["paragraph"]))
        return out

    gold, ours = paragraphs(expected), paragraphs(sub)
    shared = sorted(set(gold) & set(ours))
    return {
        "gold_regulations": {r: sum(1 for x in expected["requirements"] if x["source"]["regulation"] == r) for r in sorted(gold)},
        "run_regulations": {r: sum(1 for x in sub["requirements"] if x["source"]["regulation"] == r) for r in sorted(ours)},
        "wrong_regulations": sorted(set(ours) - set(gold)),
        "missed_regulations": sorted(set(gold) - set(ours)),
        "paragraphs": {r: {"gold": len(gold[r]), "cited": len(ours[r]), "hit": len(gold[r] & ours[r]),
                           "missed": len(gold[r] - ours[r]), "extra": len(ours[r] - gold[r])} for r in shared},
    }


def bench_one(case: Path, args: argparse.Namespace, budget: Budget, runs_map: dict) -> dict:
    case_id = case.name
    out_dir = ROOT / args.out_dir
    row: dict = {"case": case_id}
    run = find_run(case, runs_map, args.reuse)
    row["reused"] = run is not None
    if run is None:
        if args.reuse:
            return {**row, "error": "no run to reuse"}
        if not budget.reserve(args.max_cost):
            return {**row, "error": f"skipped: budget ${budget.limit:.2f} would be passed"}
        run = ROOT / "runs" / case_id / args.name
        started = time.time()
        done = run_tool(["src/ai_agent/run.py", str(case), "--out", str(run), "--max-cost", str(args.max_cost)], ROOT / "runs" / case_id / f"{args.name}.log")
        row["agent_exit"], row["agent_seconds"] = done.returncode, round(time.time() - started)
        budget.settle(args.max_cost, spent_of(run))
        if not (run / "submission.json").is_file():
            return {**row, "error": f"the agent wrote no submission.json (exit {done.returncode}); see runs/{case_id}/{args.name}.log"}
        (ROOT / "runs" / case_id / "latest.txt").write_text(run.relative_to(ROOT).as_posix() + "\n", encoding="utf-8")
    row["run"] = run.relative_to(ROOT).as_posix()
    row["agent_cost_usd"] = spent_of(run)
    sub, expected = read_json(run / "submission.json"), read_json(case / "expected.json")

    check = run_tool(["tools/validate.py", str(run / "submission.json"), "--strict"])
    row["validate_strict"] = {"ok": check.returncode == 0, "message": (check.stdout.strip().splitlines() or [""])[-1][:200]}
    scored = run_tool(["tools/score_local.py", str(run / "submission.json"), "--expected", str(case / "expected.json"), "--json"])
    try:
        score = json.loads(scored.stdout)
    except ValueError:
        return {**row, "error": "score_local failed: " + (scored.stderr or scored.stdout)[-200:]}
    for level in ("regulation_level", "page_level"):
        score[level]["f2"] = round(f2(score[level]["precision"], score[level]["recall"]), 4)
    row["score_local"] = score
    row["taxonomy"] = taxonomy(sub, expected)
    row["n_gold"], row["n_submitted"] = len(expected["requirements"]), len(sub["requirements"])

    judged = case_id in args.judge
    bench = read_json(run / "bench.json") if judged else None
    if judged and not (bench and "requirement" in bench):  # a judge run costs money: once per run folder
        if not budget.reserve(args.judge_cost):
            row["judge"] = {"skipped": "budget"}
        else:
            run_tool(["eval/bench_agent.py", str(run), "--expected", str(case / "expected.json")], run / "bench.log")
            bench = read_json(run / "bench.json")
            budget.settle(args.judge_cost, float((bench or {}).get("judge_cost_usd", 0)))
    elif not judged:
        if not (read_json(run / "bench.json") or {}).get("funnel"):
            run_tool(["eval/bench_agent.py", str(run), "--expected", str(case / "expected.json"), "--no-judge"], run / "bench.log")
        bench = read_json(run / "bench.json")
    if bench:
        row["funnel"] = {k: bench.get("funnel", {}).get(k) for k in ("sections", "extraction")}
        row["paragraph_level"] = bench.get("paragraph")
        if "requirement" in bench:
            req = bench["requirement"]
            row["judge"] = {"strict": req["strict"], "lenient": req["lenient"],
                            "strict_f2": round(f2(req["strict"]["precision"], req["strict"]["recall"]), 4),
                            "lenient_f2": round(f2(req["lenient"]["precision"], req["lenient"]["recall"]), 4),
                            "cost_usd": bench.get("judge_cost_usd")}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{case_id}.json").write_text(json.dumps(row, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return row


def std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / (len(values) - 1)) ** 0.5


def cheap_funnel(run: Path, expected: dict) -> dict:
    """Gold requirements whose paragraph (node) lies inside the selected sections, from sections.json (the funnel of eval/bench_agent.py)."""
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools"), str(ROOT / "eval")]
    import bench_agent as ba
    from ai_agent.store import RegGraph

    gold = expected["requirements"]
    regs = sorted({g["source"]["regulation"] for g in gold} | set((read_json(run / "sections.json", {}) or {})))
    graphs = {reg: RegGraph(reg, grids=False) for reg in regs}
    anchor = ba.anchors(gold, graphs)
    sel, _ = ba.selected_sets(run, graphs)
    reach = [anchor[g["id"]] is not None and anchor[g["id"]] in sel.get(g["source"]["regulation"], set()) for g in gold]
    gold_nodes = {(g["source"]["regulation"], anchor[g["id"]]) for g in gold if anchor[g["id"]] is not None}
    content = {reg: {i for i in nodes if graphs[reg].is_content(i)} for reg, nodes in sel.items()}
    hit = {(r, i) for r, i in gold_nodes if i in content.get(r, set())}
    return {"gold_requirements": len(gold), "reachable": sum(reach), "recall": round(sum(reach) / len(gold), 4) if gold else 0.0,
            "selected_nodes": sum(len(v) for v in content.values()), "gold_nodes": len(gold_nodes), "gold_nodes_reached": len(hit),
            "unanchored": sum(1 for g in gold if anchor[g["id"]] is None)}


def cheap_run(case: Path, args: argparse.Namespace, budget: Budget) -> dict:
    """Run (or replay) one case to the end of the section stage; the scoring is done afterwards, in one thread (PyMuPDF is not thread-safe)."""
    row: dict = {"case": case.name}
    run = ROOT / "runs" / case.name / args.name
    if args.reuse:
        if not (run / "upper_bound.json").is_file():
            return {**row, "error": "no run to reuse"}
    else:
        if not budget.reserve(args.max_cost):
            return {**row, "error": f"skipped: budget ${budget.limit:.2f} would be passed"}
        started = time.time()
        done = run_tool(["src/ai_agent/run.py", str(case), "--out", str(run), "--max-cost", str(args.max_cost), "--stop-after", args.stop_after],
                        ROOT / "runs" / case.name / f"{args.name}.log")
        row["agent_exit"], row["agent_seconds"] = done.returncode, round(time.time() - started)
        budget.settle(args.max_cost, float((read_json(run / "usage.json", {}) or {}).get("spent_usd", 0)))
    row["run"] = run.relative_to(ROOT).as_posix()
    usage = read_json(run / "usage.json", {}) or {}
    row["spent_usd"], row["replayed_usd"] = round(float(usage.get("spent_usd", 0)), 3), round(float(usage.get("replayed_usd", 0)), 3)
    if not (run / "upper_bound.json").is_file():
        row["error"] = f"no upper_bound.json (exit {row.get('agent_exit')}); see runs/{case.name}/{args.name}.log"
    return row


def cheap_score(row: dict, case: Path, out_dir: Path) -> dict:
    if "error" in row:
        return row
    run, expected = ROOT / row["run"], read_json(case / "expected.json")
    ub = read_json(run / "upper_bound.json")
    scored = run_tool(["tools/score_local.py", str(run / "upper_bound.json"), "--expected", str(case / "expected.json"), "--json"])
    try:
        score = json.loads(scored.stdout)
    except ValueError:
        return {**row, "error": "score_local failed: " + (scored.stderr or scored.stdout)[-200:]}
    for level in ("regulation_level", "page_level"):
        score[level]["f2"] = round(f2(score[level]["precision"], score[level]["recall"]), 4)
    row["score_local"] = score
    row["gold_regulations"] = sorted({g["source"]["regulation"] for g in expected["requirements"]})
    row["run_regulations"] = sorted({r["source"]["regulation"] for r in ub["requirements"]})
    row["n_gold"], row["n_upper_bound"] = len(expected["requirements"]), len(ub["requirements"])
    row["funnel"] = cheap_funnel(run, expected)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{case.name}.json").write_text(json.dumps(row, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return row


def cheap_table(rows: list[dict]) -> str:
    keys = ("precision", "recall", "f1", "f2")
    lines = ["| case | gold regs | run regs | reg P | reg R | reg F1 | reg F2 | page-UB P | page-UB R | page-UB F1 | page-UB F2 "
             "| gold reqs in sections | selected nodes | $ spent / replayed |\n" + "|" + "---|" * 14]
    done = [r for r in rows if "score_local" in r]
    for r in rows:
        if "score_local" not in r:
            lines.append(f"| {r['case']} | {r.get('error', '?')} |" + " |" * 12)
            continue
        g, p, fu = r["score_local"]["regulation_level"], r["score_local"]["page_level"], r["funnel"]
        lines.append(f"| {r['case']} | {', '.join(x.replace('UN ', '') for x in r['gold_regulations'])} | {', '.join(x.replace('UN ', '') for x in r['run_regulations'])} "
                     + "".join(f"| {g[k]:.2f} " for k in keys) + "".join(f"| {p[k]:.2f} " for k in keys)
                     + f"| {fu['reachable']}/{fu['gold_requirements']} ({fu['recall']:.2f}) | {fu['selected_nodes']} | {r['spent_usd']:.2f} / {r['replayed_usd']:.2f} |")
    if done:
        for label, fn in (("macro mean", lambda v: sum(v) / len(v)), ("std", std)):
            cells = "".join(f"| {fn([r['score_local'][lv][k] for r in done]):.2f} " for lv in ("regulation_level", "page_level") for k in keys)
            money = f"{sum(r['spent_usd'] for r in done):.2f} / {sum(r['replayed_usd'] for r in done):.2f}" if label == "macro mean" else ""
            lines.append(f"| **{label} of {len(done)}** | | {cells}| {fn([r['funnel']['recall'] for r in done]):.2f} "
                         f"| {fn([r['funnel']['selected_nodes'] for r in done]):.0f} | {money} |")
    return "\n".join(lines)


def main_cheap(cases: list[Path], args: argparse.Namespace) -> int:
    budget = Budget(args.budget, args.spent)
    print(f"cheap mode: {len(cases)} cases to the end of the sections, budget ${args.budget:.2f}, run folder runs/<case>/{args.name}", flush=True)
    with futures.ThreadPoolExecutor(args.parallel) as pool:
        runs = list(pool.map(lambda c: cheap_run(c, args, budget), cases))
    ordered = []
    for case, row in zip(cases, runs):  # scored one after the other: the graphs are parsed with PyMuPDF
        row = cheap_score(row, case, ROOT / args.out_dir)
        ordered.append(row)
        if "score_local" in row:
            g, p = row["score_local"]["regulation_level"], row["score_local"]["page_level"]
            print(f"{row['case']}: reg P/R {g['precision']:.2f}/{g['recall']:.2f} F2 {g['f2']:.2f}  page-UB P/R {p['precision']:.2f}/{p['recall']:.2f} F2 {p['f2']:.2f}"
                  f"  sections {row['funnel']['reachable']}/{row['funnel']['gold_requirements']}  ${row['spent_usd']:.2f} (+${row['replayed_usd']:.2f} replayed)", flush=True)
        else:
            print(f"{row['case']}: {row.get('error')}", flush=True)
    new = sum(r.get("spent_usd", 0) for r in ordered)
    text = ("# Cheap benchmark: regulations and sections only\n\nEvery run stops after the section walks and the citation hop (`--stop-after sections`). "
            "Regulation columns are exact. Page-UB columns score `upper_bound.json` (every selected node cited once): recall is a ceiling, precision a "
            "lower bound of the real figure (`spec/finding/cheap-bench.md`). F2 = 5PR / (4P + R). Std is the sample standard deviation over cases.\n\n"
            + f"Run folder `{args.name}`, part `{args.part}`" + (f" of `{args.split}`" if args.split else "") + ".\n\n"
            + cheap_table(ordered) + f"\n\nNew Anthropic spend of this call: ${new:.2f}.\n")
    (ROOT / args.results).write_text(text, encoding="utf-8")
    print(f"\ntable -> {args.results}; new spend ${new:.2f}")
    return 0


def table(rows: list[dict]) -> str:
    head = ("| case | gold regs | run regs | n gold / run | reg P | reg R | reg F1 | reg F2 | page P | page R | page F1 | page F2 "
            "| judge F2 strict / lenient | agent $ | valid |\n" + "|" + "---|" * 15)
    lines = [head]
    for r in rows:
        if "score_local" not in r:
            lines.append(f"| {r['case']} | {r.get('error', '?')} |" + " |" * 13)
            continue
        g, p, t = r["score_local"]["regulation_level"], r["score_local"]["page_level"], r["taxonomy"]
        j = r.get("judge") or {}
        judge = f"{j['strict_f2']:.2f} / {j['lenient_f2']:.2f}" if "strict_f2" in j else "-"
        lines.append(f"| {r['case']} | {', '.join(x.replace('UN ', '') for x in t['gold_regulations'])} "
                     f"| {', '.join(x.replace('UN ', '') for x in t['run_regulations'])} | {r['n_gold']} / {r['n_submitted']} "
                     f"| {g['precision']:.2f} | {g['recall']:.2f} | {g['f1']:.2f} | {g['f2']:.2f} "
                     f"| {p['precision']:.2f} | {p['recall']:.2f} | {p['f1']:.2f} | {p['f2']:.2f} | {judge} "
                     f"| {r['agent_cost_usd']:.2f} | {'yes' if r['validate_strict']['ok'] else 'NO'} |")
    done = [r for r in rows if "score_local" in r]
    if done:
        mean = lambda level, key: sum(r["score_local"][level][key] for r in done) / len(done)  # noqa: E731
        lines.append(f"| **mean of {len(done)}** | | | | {mean('regulation_level', 'precision'):.2f} | {mean('regulation_level', 'recall'):.2f} "
                     f"| {mean('regulation_level', 'f1'):.2f} | {mean('regulation_level', 'f2'):.2f} | {mean('page_level', 'precision'):.2f} "
                     f"| {mean('page_level', 'recall'):.2f} | {mean('page_level', 'f1'):.2f} | {mean('page_level', 'f2'):.2f} | | "
                     f"{sum(r['agent_cost_usd'] for r in done):.2f} | |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run and score the agent on several cases; write a results table.")
    parser.add_argument("cases", nargs="+", help="case folders with expected.json and a text spec; globs are expanded here")
    parser.add_argument("--name", default=time.strftime("bench-%Y%m%d-%H%M"), help="run folder name under runs/<case>/")
    parser.add_argument("--reuse", action="store_true", help="never start the agent: score the existing runs (runs/<case>/latest.txt or --runs-map)")
    parser.add_argument("--runs-map", help="JSON {case: run_dir} (or {case: {run: run_dir, ...}}), e.g. testing/_benched.json")
    parser.add_argument("--judge", nargs="*", default=[], metavar="CASE", help="case ids to run the model judge on (about $0.4 each)")
    parser.add_argument("--stop-after", choices=["sections"], help="cheap mode: stop every run before the extraction, score upper_bound.json "
                        "(results in testing/results-cheap/, testing/RESULTS-cheap.md)")
    parser.add_argument("--split", help="JSON {tune: [case ids], heldout: [case ids]} (testing/_split.json); ignored with a warning when missing")
    parser.add_argument("--part", choices=["tune", "heldout", "all"], default="all", help="with --split: the cases of this part")
    parser.add_argument("--max-cost", type=float, default=None, help="USD cap of one agent run (default 5; 0.8 with --stop-after)")
    parser.add_argument("--judge-cost", type=float, default=0.8, help="USD reserved for one judge run")
    parser.add_argument("--budget", type=float, default=None, help="(default 27; 3 with --stop-after) stop starting runs when spent plus --max-cost would pass this")
    parser.add_argument("--spent", type=float, default=0.0, help="USD already spent before this call, counted against --budget")
    parser.add_argument("--parallel", type=int, default=3, help="runs at the same time")
    parser.add_argument("--out-dir", default=None, help="folder of the per-case JSON files")
    parser.add_argument("--results", default=None, help="the markdown table (default testing/RESULTS.md; testing/RESULTS-cheap[-<part>].md with --stop-after)")
    parser.add_argument("--benched-out", help="also write {case: {run, numbers}} here (e.g. testing/_benched.json), the map --runs-map reads")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    cheap = args.stop_after is not None
    if args.max_cost is None:
        args.max_cost = 0.8 if cheap else 5.0
    if args.budget is None:
        args.budget = 3.0 if cheap else 27.0
    suffix = "" if args.part == "all" else f"-{args.part}"
    if args.out_dir is None:
        args.out_dir = "testing/results-cheap" + suffix if cheap else "testing/results"
    if args.results is None:
        args.results = f"testing/RESULTS-cheap{suffix}.md" if cheap else "testing/RESULTS.md"
    if cheap and args.name.startswith("bench-"):
        args.name = args.name.replace("bench-", "cheap-", 1)

    cases = []
    for pattern in args.cases:
        cases += [Path(p) for p in sorted(glob.glob(pattern))] or [Path(pattern)]
    cases = [c for c in dict.fromkeys(c.resolve() for c in cases) if (c / "expected.json").is_file()]
    if not cases:
        parser.error("no case folder with an expected.json")
    if args.split and args.part != "all":
        split = read_json(ROOT / args.split) or read_json(Path(args.split))
        if split is None:
            print(f"warning: {args.split} is missing or unreadable; using all {len(cases)} cases", file=sys.stderr)
        else:
            keep = set(split.get(args.part, []))
            cases = [c for c in cases if c.name in keep]
            if not cases:
                parser.error(f"no case of the {args.part} part of {args.split}")
    if cheap:
        return main_cheap(cases, args)
    runs_map = read_json(ROOT / args.runs_map, {}) if args.runs_map else {}
    budget = Budget(args.budget, args.spent)
    print(f"{len(cases)} cases, {args.parallel} at a time, budget ${args.budget:.2f} (already ${args.spent:.2f})", flush=True)

    rows: dict[str, dict] = {}
    with futures.ThreadPoolExecutor(args.parallel) as pool:
        jobs = {pool.submit(bench_one, c, args, budget, runs_map): c for c in cases}
        for job in futures.as_completed(jobs):
            row = job.result()
            rows[row["case"]] = row
            if "score_local" in row:
                s = row["score_local"]
                print(f"{row['case']}: reg P/R {s['regulation_level']['precision']:.2f}/{s['regulation_level']['recall']:.2f} F2 {s['regulation_level']['f2']:.2f}"
                      f"  page P/R {s['page_level']['precision']:.2f}/{s['page_level']['recall']:.2f} F2 {s['page_level']['f2']:.2f}"
                      f"  ${row['agent_cost_usd']:.2f}  run {row['run']}", flush=True)
            else:
                print(f"{row['case']}: {row.get('error')}", flush=True)

    ordered = [rows[c.name] for c in cases]
    text = ("# Benchmark of the agent on the generated cases\n\nDefault efforts of `src/ai_agent/config.py`; the gold of each case is a "
            "DeepSeek writer's opinion (`testing/README.md`). F2 = 5PR / (4P + R). Judge F2 only where the judge ran.\n\n"
            + table(ordered) + f"\n\nTotal agent spend counted: ${budget.spent:.2f} of ${args.budget:.2f}.\n")
    (ROOT / args.results).write_text(text, encoding="utf-8")
    if args.benched_out:
        benched = {r["case"]: {"run": r["run"], "agent_cost_usd": r["agent_cost_usd"], "n_gold": r["n_gold"], "n_submitted": r["n_submitted"],
                               "regulation_level": r["score_local"]["regulation_level"], "page_level": r["score_local"]["page_level"],
                               "judge": r.get("judge")} for r in ordered if "score_local" in r}
        (ROOT / args.benched_out).write_text(json.dumps(benched, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\ntable -> {args.results}; spent about ${budget.spent:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
