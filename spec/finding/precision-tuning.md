# Findings: tuning the emission policy against the dev case

Status: results, 2026-10-25. Companion to `spec/precision.md` (the F2/5 bar) and `spec/finding/ai-agent-baseline.md` (section 2.4, the first policy). Code: `src/ai_agent/emit.py`. Everything below is offline: it re-emits the saved candidates of `runs/dev-rear-lamp/run1` and `run2` and reuses their saved judge verdicts (`judge_verdicts.json`), so no paid call. The harness is `runs/_a1/harness.py` (git-ignored scratch). The one in-sample caveat is in the last section.

## Summary

- **New default policy `precision-v1`**: the old three filters plus (1) drop `conformity-of-production` obligations, (2) drop a regulation with no emitted `certain` candidate that was not picked at high confidence, (3) drop a page whose emitted candidates are all `possible` and at most three. `baseline-v1` (the old behaviour) stays reachable: `AI_AGENT_POLICY=baseline-v1`.
- **Run 2 (the current configuration), before / after:** regulation P/R 0.80/1.00 to **1.00/1.00**; page P/R 0.591/0.962 to **0.754/0.906**; requirement strict F2 0.601 to **0.624**, lenient 0.690 to **0.704**; 363 to 306 requirements.
- **Targets:** regulation 1.00/1.00 reached; strict F2 >= 0.60 reached; page P >= 0.73 reached (0.754) at page R 0.906 (48 of 53 gold pages; the 0.91 asked for is 0.906 rounded; it was 0.962 before, the price of the page precision).
- **Run 1 (medium effort, superseded extraction) does not gain on the requirement level** (strict F2 0.349 to 0.348, lenient 0.591 to 0.574): it is recall-starved (R 0.34), so the bar F2/5 is 0.07 and every dropped candidate costs. Regulation P goes to 1.00 and page P 0.727 to 0.804 there too, page R falls 0.906 to 0.849.
- End to end: `run.py cases/dev-rear-lamp --out runs/dev-rear-lamp/a1-policy` replayed 100% from the cache ($0.00 spent, $3.95 replayed), `validate.py --strict` OK, `score_local.py` page 0.754/0.906, equal to the offline harness.

## 1. Before and after

| | run 2 before | run 2 after | run 1 before | run 1 after |
|---|---|---|---|---|
| Emitted | 363 | 306 | 171 | 146 |
| Regulation P / R / F2 | 0.80 / 1.00 / 0.95 | 1.00 / 1.00 / 1.00 | 0.80 / 1.00 / 0.95 | 1.00 / 1.00 / 1.00 |
| Page P / R / F1 / F2 | 0.591 / 0.962 / 0.732 / 0.855 | 0.754 / 0.906 / 0.823 / 0.871 | 0.727 / 0.906 / 0.807 / 0.863 | 0.804 / 0.849 / 0.826 / 0.840 |
| Requirement strict P / R / F2 | 0.372 / 0.711 / 0.601 | 0.435 / 0.700 / 0.624 | 0.380 / 0.342 / 0.349 | 0.432 / 0.332 / 0.348 |
| Requirement lenient P / R / F2 | 0.427 / 0.816 / 0.690 | 0.490 / 0.789 / 0.704 | 0.643 / 0.579 / 0.591 | 0.712 / 0.547 / 0.574 |

Requirement numbers: the saved judge verdicts cover every grounded candidate (the judge pool is all candidates), so a different emitted set is re-matched with the same Hungarian assignment and no new judge call. The harness reproduces the saved `bench.json` of both runs exactly under the old policy (171 and 363 emitted, strict 65 and 135 matched).

## 2. The rules and their measured bins (run 2; strict match rate of the bin, bar = F2/5 = 0.12)

| Rule | What it drops | Bin rate | Effect (applied in order) |
|---|---|---|---|
| Regulation check | R128: 19 emitted, all `possible` or `likely` | 0 of 19 | reg P 0.80 to 1.00, page P 0.591 to 0.627, strict F2 0.601 to 0.611 |
| `kind` = conformity-of-production | 29 candidates (R148 Annex 4-5, R150 Annex 2-3, R48 Annex 9, R10 9.x) | 2 of 29 (7%); by regulation 2/24, 2/29, 1/15, 1/23, 2/25 leaving one out | page P 0.627 to 0.694, page R 0.962 to 0.925, strict F2 0.611 to 0.619 |
| Sparse `possible` pages | 9 candidates on pages that carry only 1-3 `possible` | 15 pages of this kind (`possible` only, any size) were 13% right at page level (2 of 15) | page P 0.694 to 0.754, page R 0.925 to 0.906, strict F2 0.619 to 0.624 |

Why each is generic rather than dev-specific:

- **Regulation check.** A regulation that applies to the product has provisions the model is sure apply (R148 55 `certain`, R150 43, R48 49, R10 2); one chosen with medium confidence and none certain is a regulation chosen "to be safe". The threshold is "none" and not "fewer than N": R10, a horizontal regulation (EMC) that is gold, has only 2 `certain`, so any N of 3 or more drops it. Two guards: a regulation selected at high confidence is never touched; and if the check would drop every regulation it drops none. A regulation that a citation hop added has no confidence and counts as medium.
- **Conformity of production.** The manufacturer's and the authority's control of the series (sampling, 20% deviation, "shall not be contested") is not a property of the product. Its match rate is below the bar in every fold.
- **Sparse `possible` pages.** `possible` is the model's weakest grade (22% matched). A page that holds nothing but a few `possible` items is where a stray hit lands; the experts cite pages that hold several obligations. The bin is defined on pages, not on candidates, so it moves page precision more than requirement precision.

## 3. Bin tables behind the choice (run 2, emitted, strict / lenient match)

| applies | n | strict | lenient | | section category | n | strict |
|---|---|---|---|---|---|---|---|
| certain | 149 | 0.48 | 0.53 | | general | 138 | 0.46 |
| likely | 104 | 0.38 | 0.40 | | function | 71 | 0.42 |
| possible | 110 | 0.22 | 0.27 | | marking | 72 | 0.39 |
| | | | | | test annex | 53 | 0.23 |
| | | | | | conformity | 29 | 0.07 |

| applies x category | n | strict |
|---|---|---|
| certain, general | 34 | 0.74 |
| certain, function / marking / test / conformity | 40 / 28 / 30 / 17 | 0.53 / 0.50 / 0.33 / 0.12 |
| likely, general / function / marking / test | 50 / 23 / 16 / 14 | 0.50 / 0.30 / 0.31 / 0.14 |
| possible, general / marking / function / test / conformity | 54 / 28 / 8 / 9 / 11 | 0.24 / 0.32 / 0.25 / 0.00 / 0.00 |

| addressee | n | strict |
|---|---|---|
| product | 226 | 0.42 |
| product via a test | 137 | 0.28 |
| product via a test, in a test annex / in a function section / in conformity | 45 / 15 / 21 | 0.20 / 0.00 / 0.05 |

Pages (88 cited in run 2, 52 right at page level): by best grade on the page, certain 41 of 57 right (0.72), likely 9 of 16 (0.56), possible 2 of 15 (0.13). By category, function-only pages 14 of 14, general-only 18 of 25, marking-only 6 of 13, test-only 10 of 23, conformity-only 2 of 11. Pages with one emitted candidate were 2 of 15 right, with five or more 27 of 30. No page without a strict match was right except 2 of 38 (the page score is lenient on paragraph numbers).

## 4. Tried and rejected

| Variant (on top of the first two rules unless noted) | Run 2 result | Why not |
|---|---|---|
| Regulation check "fewer than 3 certain" | R10 dropped | R10 is gold with 2 certain |
| Also drop `possible` + `product_via_test` (36, 2 matched) | page P 0.721, R 0.906; strict F2 0.617, lenient 0.697 | strict and lenient F2 go down (0.619 and 0.707 before), the 2 matches it removes are at the bar (2 of 14 after conformity); costs run 1 too (3 of 9 matched there) |
| Also drop `possible` + `test-procedure` (5, 0 matched) | page P +0.01 | too small to carry a rule |
| Drop `product_via_test` in function sections (15, 0 matched) | strict F2 +0.007 | these are the photometric tables of R148 5.2.1 / 5.5.1 / 5.8.1 and the R150 5.1.3 tests, real product limits; the zero is wording and granularity, not applicability. Dropping them is a fit to this gold |
| Drop pages with one emitted candidate | page P 0.80, R 0.887; strict F2 0.616 | run 1: page R 0.717, strict F2 0.329: density depends on how complete the extraction is |
| Drop pages with no `certain` | page P 0.81, R 0.717; strict F2 0.53 | removes 45% of the matches |
| Drop pages with only `likely`/`possible`, at most 2 | page P 0.807, R 0.849; strict F2 0.622 | run 1: page R 0.774, strict F2 0.347 to 0.335, lenient 0.573 to 0.542 |
| Drop all test-annex candidates | strict F2 0.575, page R -0.17 | 12 matches lost of 53 (23%, above the bar) |
| `possible` only pages with no size limit | page P 0.762, R 0.887; strict F2 0.626 | page R below 0.91; the cap of three gives the same page precision at one more gold page |
| `certain` only / without `possible` | strict F2 0.396 / 0.548 | already in `ai-agent-baseline.md` 2.4 |

Single-bin removals over applies, category, addressee, kind and their pairs (every bin of at least one candidate) show that no bin besides the ones used is both below the bar and large: the next best (`likely`, test annex, 14 candidates) loses 2 matches for +0.019 page P.

## 5. Checks and overfitting

- **Leave one regulation out** (the rules fixed, gold and candidates of one regulation removed, strict F2 old to new, run 2): without R10 0.601 to 0.624, R128 0.611 to 0.624, R148 0.585 to 0.612, R150 0.591 to 0.617, R48 0.614 to 0.643. The gain is positive in each fold. This is a stability check, not a refit: the rules were read from the full data.
- **Run 1** as an independent sample of the same labels (different extraction): regulation and page precision rise, the requirement level is flat to slightly down (see summary). The rules are not a free lunch when extraction recall is low.
- **One case.** Everything here is measured on the dev rear lamp against its gold, which is also what suggested the rules. Held-out cases (the model-authored `spec/testing/cases/ds-*`) are the real test. Specific risks on a new case:
  - a correct horizontal or vehicle-level regulation with no `certain` provision and medium confidence is dropped (R10 survives here with 2 `certain`; the margin is thin);
  - a short case with few obligations per page loses its `possible` pages (3 or fewer per page);
  - `conformity-of-production` is dropped even when a case's gold cites such a paragraph (2 of 190 here, the experts cite it rarely, but they do).
- **What the judge-based numbers cover.** The matches of the 306 emitted come from the saved verdicts of the full candidate pool; the platform's own judge may differ by the strict-to-lenient range.

## 6. Reproduce

```
python src/ai_agent/run.py cases/dev-rear-lamp --out runs/dev-rear-lamp/a1-policy --no-image    # replays from runs/_llm_cache, $0
AI_AGENT_POLICY=baseline-v1 python src/ai_agent/run.py ...                                       # the old policy
python tools/score_local.py runs/dev-rear-lamp/a1-policy/submission.json --expected cases/dev-rear-lamp/expected.json
python eval/test_ai_agent.py                                                                     # policy tests, offline
```
Statuses written to `candidates.json`: `dropped:kind=conformity-of-production`, `dropped:regulation=no_certain`, `dropped:page=only_possible` (next to the old `dropped:modality|addressee|applies|duplicate` and `rejected:*`). The policy is in `run.json` under `policy`; `runs/_policy_ready.json` has the numbers for the outputs stage.

## Addendum (2026-10-25): the regulation check is off by default (`precision-v2`)

On the text-and-image dev run (`spec/finding/image-input.md`) the regulation check dropped UN R10, a correct horizontal regulation selected at medium confidence, because none of its emitted candidates was graded `certain` in that sample (run 1 had 8, run 2 had 2). R128 and R10 are both medium and horizontal, so neither confidence nor level separates them; only the `certain` count does, and it moves with sampling. The cost is lopsided: dropping R10 took strict F2 from 0.62 to 0.53 (28 expected requirements), keeping R128 costs about 0.01. `precision-v2`, now the default, is `precision-v1` without the regulation check; `AI_AGENT_POLICY=precision-v1` restores it.

| Dev, precision-v2 (replays) | Emitted | Regulation P/R | Page P/R/F1 | Strict P/R/F2 | Lenient F2 |
|---|---|---|---|---|---|
| text only (`runs/dev-rear-lamp/lead-text-v2`) | 318 | 0.80/1.00 | 0.731/0.906/0.809 | 0.418/0.700/0.617 | 0.696 |
| text + image (`runs/dev-rear-lamp/lead-textimage-v2`) | 317 | 1.00/1.00 | 0.731/0.906/0.809 | 0.429/0.716/0.631 | 0.715 |
