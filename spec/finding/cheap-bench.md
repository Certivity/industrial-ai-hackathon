# Findings: the cheap benchmark (`--stop-after sections`) and how far its page upper bound carries

Status: tooling and baseline, 2026-10-25. Companion to `spec/finding/synthetic-tuning.md` and `spec/finding/preset-and-outputs.md`. Cases: the 6 `testing/ts-*` cases of `testing/_benched.json` plus `cases/dev-rear-lamp` (text + drawing, as `outputs/dev-rear-lamp` was made).

## 1. What the mode does

A full run costs $2.4-4.8, 92% of it in the obligation extraction (`runs/ts-*/a2-default/calls.jsonl`). The error is in the cheap stages (regulation and section selection), so `src/ai_agent/run.py --stop-after {profile,regulations,sections}` stops the run before the next stage and writes what exists (profile, `regulations.json`, `sections.json`, `walk-*.json`, `citation_hop.json`, `usage.json`, `run.json`). No `submission.json`, and `runs/<case>/latest.txt` is not moved. Without the flag nothing changes: the requests are byte-identical and the replay cache (`runs/_llm_cache`) hits (checked on dev: all calls replayed, $0 spent).

After `sections`, `upper_bound.json` is also written (`pipeline.upper_bound_submission`): every selected content node cited once, with regulation, version, the node's paragraph label and its first page, as the emitter cites a node. Nodes without a label are left out. `tools/score_local.py` scores it:

- **Regulation level is exact** (the real run cites the same regulations unless `emit.check_regulations` drops one; on all 7 cases it did not).
- **Page level**: recall is a ceiling (extraction and policy only remove nodes; a quote on a later page of a multi-page node is covered by the paragraph rule of `score_local`). Precision is a lower bound of the real precision (the real run cites far fewer nodes).

`eval/bench_cases.py ... --stop-after sections` runs or replays each case into `runs/<case>/<name>` (default `cheap-<timestamp>`; `--name cheap-base` for the baseline), scores `upper_bound.json`, and reports gold and agent regulations, regulation P / R / F1 / F2, page-UB P / R / F1 / F2, the section funnel (gold requirements whose paragraph lies inside the selected sections, `eval/bench_agent.py` anchors), selected nodes, and $ spent / replayed, with the macro mean and the sample std over cases. Output: `testing/results-cheap/<case>.json` and `testing/RESULTS-cheap.md` (`-<part>` suffix with `--part`); `testing/RESULTS.md` is never written. `--split testing/_split.json --part tune|heldout|all` selects cases (a missing file warns and uses all). Defaults: `--max-cost 0.8` per run, `--budget 3`. `--reuse` re-scores existing cheap runs for free.

## 2. Calibration: page upper bound against the real full run

Real = `runs/<case>/a2-default/submission.json` (dev: `outputs/dev-rear-lamp/submission.json`), both scored by `score_local` against the same gold (`python eval/calibrate_cheap.py`).

| case | real page P | real page R | real F2 | UB page P | UB page R | UB F2 | R kept (real R / UB R) | P ratio (real P / UB P) |
|---|---|---|---|---|---|---|---|---|
| ts-coach-m3 | 0.28 | 0.90 | 0.62 | 0.18 | 1.00 | 0.53 | 0.90 | 1.52 |
| ts-ev-sound | 0.76 | 0.21 | 0.25 | 0.44 | 0.37 | 0.39 | 0.57 | 1.71 |
| ts-lpg-conversion | 0.75 | 0.81 | 0.80 | 0.64 | 0.84 | 0.79 | 0.97 | 1.18 |
| ts-moto-antitheft | 0.78 | 0.71 | 0.72 | 0.57 | 0.78 | 0.73 | 0.91 | 1.36 |
| ts-motorcycle-silencer | 1.00 | 0.10 | 0.12 | 1.00 | 0.14 | 0.17 | 0.71 | 1.00 |
| ts-pedestrian-front-end | 0.67 | 0.57 | 0.59 | 0.35 | 0.89 | 0.68 | 0.65 | 1.89 |
| dev-rear-lamp | 0.73 | 0.91 | 0.86 | 0.48 | 1.00 | 0.82 | 0.91 | 1.53 |
| **mean of 7** | 0.71 | 0.60 | 0.57 | 0.52 | 0.72 | 0.58 | 0.80 | 1.46 |

- Real page R is 0.57-0.97 of the UB recall (mean 0.80): a section-level recall gain carries to the real score at about four fifths, less where extraction misses nodes (ev-sound 0.57, pedestrian 0.65). Real R never exceeds UB R.
- Real page P is 1.0-1.9 times the UB precision (mean 1.46): the UB cites every selected node, so a drop in selected nodes (a tighter walk) raises UB P more than real P.
- UB F2 tracks real F2 closely on these 7 (differences 0.01-0.14, means 0.58 against 0.57), because the lower precision and the higher recall roughly cancel under F2. Use UB F2 and UB R to rank selection changes; read UB P as pessimistic. The real regulation F2 equals the UB one on every case.
- Seven cases, DeepSeek golds except dev: a rank signal, not a calibrated predictor.

## 3. Baseline (`runs/<case>/cheap-base`, default prompts, as replayed)

| case | gold regs | run regs | reg P | reg R | reg F2 | page-UB P | page-UB R | page-UB F2 | gold reqs in sections | selected nodes |
|---|---|---|---|---|---|---|---|---|---|---|
| ts-coach-m3 | R107 | R10, R107, R43 | 0.33 | 1.00 | 0.71 | 0.18 | 1.00 | 0.53 | 108/108 | 1113 |
| ts-ev-sound | R10, R100, R48, R51 | R10, R51 | 1.00 | 0.50 | 0.56 | 0.44 | 0.37 | 0.39 | 92/212 | 552 |
| ts-lpg-conversion | R10, R67, R83 | R10, R67 | 1.00 | 0.67 | 0.71 | 0.64 | 0.84 | 0.79 | 270/304 | 1201 |
| ts-moto-antitheft | R10, R161, R162, R163 | R10, R162, R163, R62 | 0.75 | 0.75 | 0.75 | 0.57 | 0.78 | 0.73 | 157/232 | 485 |
| ts-motorcycle-silencer | R10, R40, R53, R92 | R92 | 1.00 | 0.25 | 0.29 | 1.00 | 0.14 | 0.17 | 37/154 | 46 |
| ts-pedestrian-front-end | R10, R127, R26, R42 | R10, R127, R26, R42 | 1.00 | 1.00 | 1.00 | 0.35 | 0.89 | 0.68 | 109/125 | 578 |
| dev-rear-lamp | R10, R148, R150, R48 | R10, R148, R150, R48 | 1.00 | 1.00 | 1.00 | 0.48 | 1.00 | 0.82 | 190/190 | 826 |
| **macro mean of 7** | | | 0.87 | 0.74 | 0.72 | 0.52 | 0.72 | 0.58 | 0.73 (recall) | 686 |
| **std of 7** | | | 0.25 | 0.29 | 0.25 | 0.26 | 0.33 | 0.24 | 0.29 | 397 |

(Macro means: reg P 0.87, R 0.74, F1 0.73, F2 0.72; page-UB P 0.52, R 0.72, F1 0.50, F2 0.58. F1 and the full table: `testing/RESULTS-cheap.md`.) The std is large (0.25-0.33 per metric): with 7 cases, a change under about 0.1 macro is noise. The failures are selection, not extraction: silencer (R92 only: R10, R40, R53 missed) and ev-sound (R100, R48 missed) lose half of the gold regulations.

## 4. Cost

New Anthropic spend of this task: $0.00. Every baseline run replayed from `runs/_llm_cache` ($1.99 of calls replayed over the 7 cases; $0.17-0.41 each). A fresh case costs about the replayed figure: profile $0.02, regulations $0.12, sections $0.1-0.2, citation vetting $0.02, plus $0.07 for a drawing.

## 5. How to run

```
python eval/bench_cases.py testing/ts-* cases/dev-rear-lamp --stop-after sections --name cheap-X [--split testing/_split.json --part tune]
python src/ai_agent/run.py testing/ts-ev-sound --stop-after sections --out runs/ts-ev-sound/cheap-X --max-cost 0.8
python eval/calibrate_cheap.py --ub-name cheap-base
python eval/test_stop_after.py
```

Use a new `--name` for every prompt change (the run folder is re-run into the same name; unchanged requests replay for free). Run all cases of a new part before looking at its numbers; tune on `tune`, report `heldout`.
