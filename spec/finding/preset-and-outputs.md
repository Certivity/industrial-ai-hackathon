# Findings: emission policy presets on the dev case and the generated cases, and the output files

Status: results, 2026-10-25. Companion to `spec/finding/ai-agent-baseline.md` and `spec/precision.md`. Policies are those of `src/ai_agent/emit.py`: `baseline-v1` (three label filters), `precision-v1` (adds: drop kind conformity-of-production, drop a regulation with no emitted `certain` candidate unless picked at high confidence, drop a page whose emitted candidates are all `possible` and at most 3), `precision-v2` (the default; v1 with the regulation check off). Every number is a replay of a saved `candidates.json` under a policy (`runs/_a3/reemit.py`, `runs/_a3/synth.py`; no model call), scored with `tools/score_local.py`; requirement level uses the saved judge verdicts (the candidates do not change, only which are emitted). F2 = 5PR / (4P + R).

## 1. Dev case: run 1, run 2 and the presets

| Candidates | Policy | n | Reg P / R / F1 | Page P / R / F1 / F2 | Req strict P / R / F2 | Req lenient F2 |
|---|---|---|---|---|---|---|
| run 1 (medium extraction) | baseline-v1 | 171 | 0.80 / 1.00 / 0.89 | 0.73 / 0.91 / 0.81 / 0.86 | 0.38 / 0.34 / 0.35 | 0.59 |
| run 1 | precision-v1 | 146 | 1.00 / 1.00 / 1.00 | 0.80 / 0.85 / 0.83 / 0.84 | 0.43 / 0.33 / 0.35 | 0.57 |
| run 1 | precision-v2 | 163 | 0.80 / 1.00 / 0.89 | 0.75 / 0.85 / 0.80 / 0.83 | 0.39 / 0.33 / 0.34 | 0.58 |
| run 2 (high extraction) | baseline-v1 | 363 | 0.80 / 1.00 / 0.89 | 0.59 / 0.96 / 0.73 / 0.85 | 0.37 / 0.71 / 0.60 | 0.69 |
| run 2 | precision-v1 | 306 | 1.00 / 1.00 / 1.00 | 0.75 / 0.91 / 0.82 / 0.87 | 0.43 / 0.70 / 0.62 | 0.70 |
| run 2 | precision-v2 | 318 | 0.80 / 1.00 / 0.89 | 0.73 / 0.91 / 0.81 / 0.86 | 0.42 / 0.70 / 0.62 | 0.70 |
| run 2 + drawing (`lead-textimage-v2`) | precision-v2 | 317 | 1.00 / 1.00 / 1.00 | 0.73 / 0.91 / 0.81 / 0.86 | 0.43 / 0.72 / 0.63 | 0.72 |

- **Target met.** Run 2's candidates under v2 reach page P 0.73 (run 1's value) at R 0.91, against 0.59 / 0.96 before; the requirement level does not move (strict F2 0.60 to 0.62). The two drops that matter are the conformity-of-production kind (page P 0.63 to 0.69 alone) and the sparse-possible page rule (to 0.73-0.75); both are generic statements about what the experts do not cite, not about this case's paragraphs.
- **Run 1 vs run 2 under the same policy.** Run 1 has the higher page P only because it emits half as many requirements (the medium extractor missed nodes: strict R 0.33 against 0.70). Under v2 run 2 is level on page P (0.73 vs 0.75) and doubles requirement recall. The page-level score that the user liked in run 1 is reproducible with the run 2 candidates.
- **The regulation check** is the only rule that lifts dev regulation P to 1.00 (it removes R128, the one extra). It rests on one fact of one case: R128 has no `certain` candidate. On the text+image run it removed the correct R10 instead (few `certain` grades), costing strict F2 0.62 to 0.53, hence v2 turns it off. Regulation P then depends on the profile: text only keeps the R128 extra (0.80), the text+image profile does not pick it (1.00).
- **Page vs paragraph level.** Every candidate already carries its paragraph label, and `score_local` counts a page right if the page or a paragraph on it is expected, so there is nothing to gain from "always emitting the paragraph". Page recall is 0.906 under v1/v2 (49 of 53 expected pages), against 0.962 for run 2 without them; the lost pages are conformity-of-production ones (R148 p27, R150 p25) and sparse `possible` pages.

## 2. Generated cases (DeepSeek gold, `testing/ts-*`), replays of A2's default runs

| Case | Policy | n | Reg P / R / F1 / F2 | Page P / R / F1 / F2 | Req strict F2 / lenient F2 |
|---|---|---|---|---|---|
| ts-coach-m3 (gold 1 reg) | baseline-v1 | 487 | 0.33 / 1.00 / 0.50 / 0.71 | 0.27 / 0.95 / 0.42 / 0.63 | |
| | precision-v1 = v2 | 476 | 0.33 / 1.00 / 0.50 / 0.71 | 0.28 / 0.90 / 0.42 / 0.62 | |
| ts-ev-sound | baseline-v1 | 118 | 1.00 / 0.50 / 0.67 / 0.56 | 0.68 / 0.25 / 0.37 / 0.29 | |
| | precision-v1 = v2 | 104 | 1.00 / 0.50 / 0.67 / 0.56 | 0.76 / 0.21 / 0.33 / 0.25 | |
| ts-lpg-conversion | baseline-v1 | 996 | 1.00 / 0.67 / 0.80 / 0.71 | 0.74 / 0.81 / 0.77 / 0.80 | |
| | precision-v1 = v2 | 987 | 1.00 / 0.67 / 0.80 / 0.71 | 0.75 / 0.81 / 0.78 / 0.80 | |
| ts-moto-antitheft | baseline-v1 | 274 | 0.75 / 0.75 / 0.75 / 0.75 | 0.73 / 0.73 / 0.73 / 0.73 | 0.52 / 0.68 |
| | precision-v1 = v2 | 265 | 0.75 / 0.75 / 0.75 / 0.75 | 0.78 / 0.71 / 0.74 / 0.72 | 0.51 / 0.67 |
| ts-motorcycle-silencer | baseline-v1 | 40 | 1.00 / 0.25 / 0.40 / 0.29 | 1.00 / 0.14 / 0.25 / 0.17 | |
| | precision-v1 = v2 | 37 | 1.00 / 0.25 / 0.40 / 0.29 | 1.00 / 0.10 / 0.18 / 0.12 | |
| ts-pedestrian-front-end | baseline-v1 | 140 | 1.00 / 1.00 / 1.00 / 1.00 | 0.58 / 0.60 / 0.59 / 0.60 | 0.36 / 0.56 |
| | precision-v1 = v2 | 127 | 1.00 / 1.00 / 1.00 / 1.00 | 0.67 / 0.57 / 0.62 / 0.59 | 0.34 / 0.55 |
| dev (run 2, text only, for comparison) | baseline-v1 / v2 | 363 / 318 | 0.80 / 1.00 / 0.89 / 0.95 (both) | 0.59 / 0.96 / 0.73 / 0.85 and 0.73 / 0.91 / 0.81 / 0.86 | 0.60 / 0.69 and 0.62 / 0.70 |

- **The regulation check never fired on the generated cases.** v1 and v2 give identical numbers on all six: no regulation without a `certain` candidate was dropped, so no gold regulation was lost there (nor any wrong one removed). The only regulation it ever dropped was the dev case's R128. It is therefore not evidence of generalisation; it is a one-case rule, and v2 is right to leave it off.
- **The two group rules generalise weakly.** Page precision rises on 5 of 6 generated cases (+0.01 to +0.09) and is flat on the silencer; page recall falls 0.02 to 0.05 on five and is flat on lpg; page F2 changes by -0.05 to 0.00 (mean -0.02), against +0.01 on dev. Per case the trade-off is cheap where the recall is already high (moto-antitheft, pedestrian: P +0.05 / +0.09 for R -0.02 / -0.03) and costs most where the agent finds few pages (silencer, ev-sound: R -0.04 for P +0 / +0.08). The requirement level moves by 0.01-0.02 either way.
- **What limits the generated cases is regulation choice, not emission:** gold regulations missed (recall 0.25 for the silencer, 0.50 for ev-sound, 0.67 for lpg) or a single-regulation gold (coach: 3 cited, 1 expected). No emission policy can fix that; it is the profile and regulation stages. R10 (expected in every generated case) is cited in 5 of 6 (missing in the silencer run).
- No new rules were fitted to these cases (a separate effort will tune on them).

## 3. Output files

| File | What |
|---|---|
| `outputs/dev-rear-lamp/submission.json` | dev case, text+image run under precision-v2 (317 requirements, team-00); `validate --strict` OK; reg 1.00 / 1.00, page 0.731 / 0.906. Same file as `outputs/dev-rear-lamp-image/submission.json` |
| `outputs/dev-rear-lamp/submission-text-only.json` | text-only run 2 candidates under v2 (318 requirements): reg 0.80 / 1.00, page 0.731 / 0.906 |
| `outputs/dev-rear-lamp/submission-text-only-precision-v1.json` | the same under v1 (306): reg 1.00 / 1.00, page 0.754 / 0.906 (uses the regulation check) |
| `testing/<id>/output.json` | six generated cases under precision-v2, `case_id` = the case id; all pass `validate --strict` |
| `testing/_gold_style.json` | style rules of the expert gold for the DeepSeek generator |
| `runs/_a3/` | scratch: `reemit.py`, `synth.py`, `variants.py`, `synth_results.json` |

The dev output uses the text+image run because the case ships a drawing, it is better on every level (reg P 1.00, strict F2 0.63 against 0.62, lenient 0.72 against 0.70), and its profile is the default pipeline. It is one sample, and the text-only file is kept for the case that the image is not available.

## 4. Cost and caveats

- Spent by this work: about $2.0, by mistake: the first replay of `run.py cases/dev-rear-lamp` used the drawing by default (a different profile, a cache miss), stopped by the budget, and left `runs/dev-rear-lamp/a3-image-partial/` (incomplete: its regulation stage picked R148, R150 and R48 only, R10 missing). Text-only replays (`--no-image`) are free (`runs/dev-rear-lamp/a3-final`, v1).
- The synthetic gold is a DeepSeek writer's opinion; the page numbers are comparable between policies, not to the dev case in absolute terms.

## 5. Held-out cases (2026-10-25)

Pulled with `git pull --ff-only` (6c531e8 to e60025f; four new files: `cases/heldout-front-bumper/{spec.md,exploded_view.png}`, `subgoal/heldout/{files.json,requirements_old.json}`). Defaults throughout: text+image, precision-v2, select/vet v1; no code, prompt or env change.

```
python src/ai_agent/run.py cases/heldout-front-bumper --out runs/heldout-front-bumper/default --max-cost 6
python tools/validate.py runs/heldout-front-bumper/default/submission.json --strict
python src/ai_agent/run_drift.py subgoal/heldout --out runs/drift/subgoal-heldout --case-id subgoal-heldout --max-cost 1.5
python tools/validate.py runs/drift/subgoal-heldout/changes.json --kind subgoal --requirements-old subgoal/heldout/requirements_old.json --strict
```

**Main (front bumper, M1).** `validate --strict`: "OK: submission.json is valid (200 requirements)". No `expected.json`, so there is no score; `score_local.py` defaults to the dev gold and prints a meaningless number for this case, which is not reported. 200 requirements from 1067 candidates; regulations (requirements, pages): UN R148 (75, 18), UN R48 (47, 11), UN R10 (36, 9), UN R26 (18, 5), UN R42 (14, 3), UN R127 (10, 3). Applicability of the emitted 200: 20 certain, 102 likely, 78 possible. All quotes matched (quote_match 1.0); no failures recorded in `run.json`. Vision read 16 text blocks, 16 components. Cost $3.47 spent, $0.00 replayed, 411 s. Output: `outputs/heldout-front-bumper/submission.json` (`case_id` heldout-front-bumper, `team_id` team-00).

**Drift (UN R171, base 1.1.0 to latest 2.0.0).** `files.json` names `UN_R171_base.pdf` and `UN_R171_latest.pdf`; both were already in `regulations/data/UN_R171/` and their sha256 match `files.json` (no fetch). Appended sentences reported as `added` (default). `validate --strict`: "OK: changes.json is valid (108 changes)". 18 modified, 4 removed, 86 added; of the 117 old requirements 95 are unchanged. Alignment (trace.json): SAME 748, RENUMBERED 14, MODIFIED 70, REMOVED 5, ADDED 84 (paragraph nodes). Cost $0.42 spent, $0.00 replayed, 77 s. Output: `outputs/subgoal-heldout/changes.json` (`case_id` subgoal-heldout).

Total new spend $3.89.

## 6. Final submission with the marker parser (2026-10-25)

`src/ai_agent/store.py` now defaults `REGCOMP_PARSER` to `marker` (per-document induction); `rules` keeps the hand parser. The catalog cards (`catalog.py`, cache keyed by a hash of the marker parser files) and the drift pipeline (`drift.py`) take the parser from the same selector (`store.parser_module()`); before, both called `regcomp.parse` directly. The outline fallback did not trigger on any of the 92 corpus PDFs (checked: every induction confidence is at or above 0.55), so there was no DeepSeek call. Defaults otherwise (text+image, precision-v2, selection v1, drift `--appended added`). Runs: `runs/heldout-front-bumper/marker`, `runs/dev-rear-lamp/marker-final`, `runs/drift/subgoal-{heldout,dev}-marker`. The final files are in `submission/` (team_id DeepFry); the earlier files are kept as `*-rules-parser.json` under `outputs/`.

| | hand rules | marker parser |
|---|---|---|
| dev main, requirements | 317 | 334 |
| dev regulation P / R (F2) | 1.00 / 1.00 (1.00) | 0.80 / 1.00 (0.95), R128 added |
| dev page P / R (F2) | 0.731 / 0.906 (0.86) | 0.758 / 0.925 (0.89) |
| dev drift: flagged / added / overall F2 | 7/7, 13/17, 0.78 | 7/7, 15/17, 0.85 |
| bumper requirements | 200 (R148 75, R48 47, R10 36, R26 18, R42 14, R127 10) | 206 (R148 75, R48 47, R10 37, R26 23, R42 14, R127 10) |
| bumper regulations | the same six | the same six; 192 of the (regulation, paragraph, page) triples are shared, 14 new, 8 gone |
| held-out drift changes | 108 | 115 (17 modified, 5 removed, 93 added) |
| dev drift changes | 32 | 33 |

Cost: $3.51 spent, $4.59 replayed (bumper $2.01 + $1.45, dev main $1.09 + $3.03, drift held-out $0.33 + $0.06, drift dev $0.08 + $0.05). The requirement judge was not rerun. A regulation-stage sample difference (R128 on dev) is mixed with the parser change, because the run is one sample.
