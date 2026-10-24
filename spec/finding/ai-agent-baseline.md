# Findings: the first end-to-end run of the agent on the dev case

Status: results, 2026-10-24. Companion to `spec/proposal.md` (Part A), `spec/precision.md` and `spec/finding/mapping-simulation.md`. The code is `src/ai_agent/` (see its README); every number below comes from `eval/bench_agent.py`, `eval/bench_extract.py` and the run folders under `runs/` (git-ignored). The model is `claude-sonnet-5-5` (`AI_AGENT_MODEL`). The agent never opens `expected.json`; the benchmark does, afterwards.

## Summary

- **The chain works end to end on text alone.** spec.md in, a valid `submission.json` out (`tools/validate.py --strict` passes), in about 7.5 minutes and $4 for a full run (run 1, a cheaper setting, took 97 s and $1.07).
- **Platform-style numbers (`tools/score_local.py`, run 2):** regulation level P 0.80 / R 1.00 (F2 0.95), page level P 0.59 / R 0.96 (F2 0.86). All four expected regulations are chosen; R128 is the one extra.
- **Requirement level, with a local model judge (the platform's judge is not available offline):** F2 **0.60 strict, 0.69 lenient** (strict: only the same obligation counts; lenient: partial overlaps count too). 135 of 190 expected requirements matched strictly, 363 submitted. Treat the pair as a range: the platform's own judge sits somewhere in it, and one upload calibrates it.
- **Section choice is not the limit: it reached all 190 expected requirements.** The walks selected 975 provisions (12% of them are expected paragraphs) and every one of the 121 expected paragraphs is inside. Extraction and wording are where the score is.
- **Effort was the biggest lever, and it was a trap.** At `medium`, the same extraction prompt returned 142 of 190 expected nodes, and on UN R175 a 110-node chunk returned one obligation. At `high` every expected node has a candidate (190 of 190). Strict F2 went from 0.35 to 0.60.
- **The "agentic" walk barely used its tools.** Three of five walkers submitted on their first turn, two read one node first. The outline of a regulation costs 2-20K tokens, so the model chooses from it directly, and still reached every expected paragraph.
- **What is left is mostly not a defect to fix.** Of the 363 emitted requirements, 135 match strictly and 35 more are partial or differ in wording; 174 are applicable provisions of the right regulations that the experts did not pick (99 in sections they used, 75 in sections they did not: the arbitrary-selection floor of `spec/precision.md`); 19 belong to R128. The emission policy is near its optimum on this case.

## 1. What was run

| | Run 1 | Run 2 |
|---|---|---|
| Extraction effort / prompt | `medium`, v1 (one list per chunk, chunks of 40K characters) | `high`, v2 (one entry per node, repair pass, the experts' examples, chunks of 24K) |
| Other stages | profile `medium`, regulations `high`, walks `medium` | same, replayed from the cache |
| Parser | `f4acdb68` | `ac6beb6d` (edited by another session during run 1; the four dev regulations parse to identical nodes, labels, pages, text and parents under both) |
| Spent / time | $1.07 / 97 s | $3.59 (+$0.36 of stages 1-3 replayed) / 395 s |
| Calls | 21 | 20 paid in extraction, 18 chunks of 1,022 nodes, 2 repair calls |

The first three stages cost $0.37 and about 45 s; extraction is 90% of the bill. About $9 of API spend over the session, including the benchmarks and a judge ($0.34 and $0.43). No server-side fallback fired.

## 2. Results on the dev case

| Level | Run 1 P / R / F2 | Run 2 P / R / F2 | Source |
|---|---|---|---|
| Regulation (5 cited, 4 expected, 4 right) | 0.80 / 1.00 / 0.95 | 0.80 / 1.00 / 0.95 | `tools/score_local.py` |
| Page (run 2: 88 cited, 53 expected, 52 right) | 0.73 / 0.91 / 0.86 | 0.59 / 0.96 / 0.86 | `tools/score_local.py` |
| Paragraph (nodes cited vs expected, 121) | 0.59 / 0.74 / 0.70 | 0.41 / 0.89 / 0.72 | `eval/bench_agent.py` |
| Requirement, strict judge (190 expected) | 0.38 / 0.34 / 0.35 (171 submitted) | 0.37 / 0.71 / **0.60** (363) | `eval/judge.py` |
| Requirement, lenient judge | 0.64 / 0.58 / 0.59 | 0.43 / 0.82 / **0.69** | `eval/judge.py` |
| Recall ceiling of all 1,304 grounded candidates, strict / lenient | | 0.83 / 0.96 | `eval/judge.py` |

F2 = 5PR / (4P + R). The page-level score is lenient by construction ("page or paragraph"); the requirement level is the one that decides the ranking and the only one that depends on a judge.

### 2.1 The funnel (run 2)

| Stage | Result |
|---|---|
| Regulations | R10, R148, R150, R48 chosen, plus R128 (medium confidence; its 130 candidates match no expected requirement) |
| Sections | 190 of 190 expected requirements and 121 of 121 expected paragraphs inside the selected parts; 975 provisions selected, node precision 12.4% |
| Extraction | 1,310 candidates; every expected requirement has a candidate at its node (190 of 190, was 142); 157 of 190 have a candidate that is the same obligation |
| Emission | 363 of 1,304 grounded candidates emitted (6 more were rejected because the quote was not in the node) |
| Match | 135 strict / 155 lenient |

Selection by category, run 2 (provisions selected, share that are expected paragraphs): function 25%, marking 24%, general 14%, test annexes 6%, conformity of production 1%. Emitted precision by category: general 46%, function 42%, marking 39%, test 23%, conformity 7%.

### 2.2 Where the 190 expected requirements went (strict, run 2)

| | Count |
|---|---|
| Found | 135 |
| A candidate at the node, wording or split differs | 33 |
| Dropped by the policy | 22 (12 test set-up, 4 exemption, 3 permission, 3 `unlikely`) |
| Section or regulation not chosen, not extracted | 0 |

Run 1 for comparison: found 65, wording differs 77, not extracted 48.

### 2.3 What the 363 emitted requirements are (run 2)

| | Count |
|---|---|
| Matched strictly | 135 |
| Partial (lenient only) | 23 |
| Cited paragraph, wording or granularity differs | 12 |
| Right section, a paragraph the experts did not cite | 99 |
| A section the experts did not use | 75 |
| Wrong regulation (R128) | 19 |

Examples of the 174 in the middle: R48 5.15 "the rear position lamp shall emit red light", R148 3.3.2.3 on the approval marking symbols. They are applicable provisions; the experts did not pick them. Nothing in the text separates them from what was picked, as `spec/precision.md` section 3 says for the "rest" bucket. Under F2 they are kept because their match rate is above the F2/5 bar.

### 2.4 The emission policy and its bins (run 2, in-sample)

Match rate of the emitted requirements by the model's `applies` grade, against the bar F2/5 = 0.12: certain 48% (72 of 149), likely 38% (39 of 104), possible 22% (24 of 110). The 552 `unlikely` candidates held 3 expected requirements (0.5%). Dropped buckets: test set-up 3.7% (12 of 324), exemptions 13%, permissions 3.6%, manufacturer paperwork and authority actions 0% (185 candidates).

What the dev case says if the policy changes (strict / lenient F2; this is the dev gold, so it is a sensitivity, not a tuning):

| Policy | Emitted | Strict F2 | Lenient F2 |
|---|---|---|---|
| Current | 363 | 0.601 | 0.690 |
| plus test set-up | 543 | 0.564 | 0.645 |
| plus exemptions and permissions | 425 | 0.599 | 0.684 |
| plus manufacturer paperwork (certain, likely) | 412 | 0.576 | 0.661 |
| without `possible` | 253 | 0.548 | 0.612 |
| certain only | 149 | 0.396 | 0.440 |
| without R128 | 344 | 0.611 | 0.702 |
| without nodes reached only through a conformity-of-production selection | 334 | 0.608 | 0.695 |
| everything that grounded | 1,304 | 0.380 | 0.441 |

Every bucket the policy drops is below the bar and adding it lowers F2; `possible` has to stay.

## 3. An independent check of the extraction: UN R175

The dev case is one product, so tuning the extractor on its expected answer would fit that answer. `subgoal/dev/requirements_old.json` is a second expert-written set (94 requirements over 57 paragraphs of UN R175, 1.65 per paragraph against 1.57 in the dev gold). `eval/bench_extract.py` runs the extractor over all of R175 with a profile that says everything applies, so only fidelity and granularity are measured. The six paragraphs shown as examples in the v2 prompt are left out of the score (83 expert requirements graded).

| Setting | Obligations | Strict P / R / F2 | Lenient P / R / F2 | Paragraphs with a candidate |
|---|---|---|---|---|
| v1, `medium`, 40K chunks | 18 | 0.06 / 0.01 / 0.01 | 0.39 / 0.07 / 0.09 | 1 of 57 |
| v1, `high`, 40K | 160 | 0.40 / 0.77 / 0.65 | 0.45 / 0.87 / 0.73 | 55 of 57 |
| v1, `high`, 12K | 167 | 0.37 / 0.74 / 0.61 | 0.44 / 0.88 / 0.73 | 56 of 57 |
| v2, `high`, 24K | 181 | 0.36 / 0.78 / 0.63 | 0.40 / 0.87 / 0.70 | 50 of 51 |
| v2 again, sampled afresh | 185 | 0.33 / 0.74 / 0.59 | 0.39 / 0.87 / 0.70 | 50 of 51 |

(The two v1 `high` rows are rescored on the same 83 requirements as v2; the `medium` row was scored on all 94, before the examples existed. Precision is not meaningful here: the experts' set does not cover the Annex 3 paperwork or the test set-up that the extractor lists.)

- **The same prompt gave 1 or 107 obligations for the same chunk** depending on effort. At `medium` the model stops early on a long chunk; a prompt cannot fix that.
- **The v2 rewrite did not beat v1 at `high`** (strict F2 0.63 and 0.59 against 0.65 and 0.61; two samples of v2 differ by 0.04 strict, 0.01 lenient). What it adds is robustness (every node answered, 2 repairs in 1,022 nodes on the dev run) and the experts' granularity: 1.65 to 1.70 requirements per paragraph against their 1.63 (v1: 1.74-1.77).
- So the dev gain from run 1 to run 2 is mostly the effort. The v2 prompt rules were written after reading the dev errors as well as R175, so the part of the gain that is not effort is in-sample; the R175 table says not to count on it.
- Strict numbers carry about ±0.05 of sampling noise, lenient ±0.01.

## 4. What the agent did in the section walks

| Regulation | Turns | Tools before submitting | Selections (categories) |
|---|---|---|---|
| R10 | 1 | none | 11 (marking, general, conformity, 7 test) |
| R128 | 1 | none | 8 |
| R148 | 1 | none | 13 (function 5.2, 5.5, 5.8; marking 3.3; general 4; conformity; tests) |
| R150 | 2 | `read_node` once | 17 (function 5.1; marking 3.3; general 4; Annex 2-7, 10) |
| R48 | 2 | `read_node` once | 11 (function 6.4, 6.7, 6.10, 6.14; general 5; marking 4; conformity 8, Annex 9) |

The prompt asked for searches and the model skipped them. The outline of a regulation is 2-20K tokens (median 2.2K, largest R49 at 19.7K; all 56 build in 27 s), so putting it in the first message made the walk a single structured choice. The tools still work (labels are validated, bad ones are answered with the closest real ones) and matter when an outline is too long to show or a title says nothing. They did not matter here.

## 5. Next steps, by expected gain for the time

1. **Calibrate the judge with one upload** of `runs/dev-rear-lamp/run2/submission.json` (5 uploads an hour; the dev leaderboard keeps the best). The platform shows P and the submission size, so matched = P x S, which places the real judge inside the 0.60-0.69 range and tells whether the 33 wording misses are ours or the judge's. Ten minutes.
2. **Regulation precision.** R128 costs reg-level F1 (0.89 to 1.00 without it) and 19 false requirements. Its candidates have no `certain` grade at all (all likely or possible), while every correct regulation has many (R10: 15). A post-extraction check ("a regulation with fewer than three certain provisions is probably not about this product") or a second opinion on medium and low picks would catch it. One case is a hypothesis, not a rule; test it on the model-authored cases of `spec/testing/cases/` before it becomes one.
3. **The 33 wording misses and 23 partials.** The ceiling of all candidates is 0.83 strict against 0.71 emitted, and 0.96 lenient. Candidates: a self-check pass that compares each rewrite with its source for dropped conditions, more expert examples from the other R175 paragraphs (kept out of `bench_extract`'s score), two samples merged. Measure each on R175 first.
4. **Variance.** One strict score moves by 0.05 between samples. For a final upload, sample two or three times and keep the best by the local judge, or merge; remember the held-out case counts the last valid upload, not the best.
5. **Images.** `exploded_view.png` goes to the profile stage (one image block). On the dev case it will add little (an unlabelled line drawing, `mapping-simulation.md` section 1).
6. **Held-out robustness.** Run the chain on `spec/testing/cases/ds-front-bumper` and one more (about $4 and 7 minutes each); the unit of work that changes is the regulation choice (R42, R127, GTR 9, R26 are large).
7. **Not worth doing now:** more exploration in the walks (recall is already complete), tightening the policy (it is at its optimum on the dev case and every dropped bucket is below the bar).

## 6. Not measured, and risks

- **One case, and the design is in-sample.** The walk policy (named parts, class-wide parts, test annexes) and the emission filters come from the proposal and `precision.md`, which were derived from the dev gold. The model never saw the gold, but "blind" here means the model, not the design.
- **The judge is a stand-in.** Same vendor, same model family as the agent, strictness unknown. Strict and lenient bracket it; they are not the platform's number.
- **Sampling noise** is about ±0.05 on strict scores and was measured only on R175.
- **R175's expert set** is not product-filtered (it includes the applicant's and the authority's duties), so only recall and granularity transfer from it.
- **Prompt text and in-sample rules:** the R175 examples sit in the extraction prompt and the dev errors informed its rules (section 3).
- **Caching:** the replay cache returns an identical request's answer; a re-run with changed prompts samples afresh, a re-run with identical ones does not.

## 7. Reproduce

```
python src/ai_agent/run.py cases/dev-rear-lamp --out runs/dev-rear-lamp/run2        # needs AI_AGENT_KEY in .env or the environment
python tools/validate.py runs/dev-rear-lamp/run2/submission.json --strict
python tools/score_local.py runs/dev-rear-lamp/run2/submission.json
python eval/bench_agent.py runs/dev-rear-lamp/run2                                  # judge, funnel, error taxonomy, bins (about $0.4)
python eval/bench_extract.py --tag v2                                               # extraction alone on UN R175 (about $0.7)
python eval/test_ai_agent.py                                                        # 37 offline tests, no API calls
```
