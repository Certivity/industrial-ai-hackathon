# Findings: precision-v2 on the DeepSeek-generated cases, and what tuning could and could not do

Status: results, 2026-10-25 (agent A7). Code: `src/ai_agent/emit.py` (two new opt-in policy knobs, default unchanged). Scratch: `runs/_a7/`. Per-case JSON: `testing/results-a7/per_case_policies.json`.
Everything is offline replay of saved candidates. Re-emission by `run.py ... --out runs/<case>/a7-v2` replayed 100% from the cache ($0). Spend: judge runs $1.40 (silencer 0.23 + ev-sound 0.42 + lpg 0.55 + coach 0.20; pedestrian and moto verdicts were already cached), agent $0.02. Total about $1.4 of the $8.

## Summary

- **Nothing I tried beats `precision-v2` out of sample. The default stays `precision-v2`.**
- On the six synthetic cases the emission filters are near a plateau: the filter variants move macro F1 and F2 by at most 0.02 on the tune split, and the one structural change that looked best there (cap of 3 per node) lowers requirement F2 on the held-out split (0.36 to 0.34) and dev (0.62 to 0.57).
- The large errors are not emission errors. They are (a) regulation sets in the gold that the agent's choice disagrees with, and for the silencer, ev-sound and moto cases the agent's choice reads as the more defensible one, so I did not tune toward them; (b) over-emission against a gold that cites roughly one requirement per paragraph; (c) the test-procedure and test-condition provisions, which the golds mostly do not cite.
- `precision-v1`'s regulation check dropped no gold regulation on any saved run here (synthetic: it never fires; dev run `lead-text-v2`: it drops R128 only, reg P 0.80 to 1.00). The earlier R10 drop was in a different run (text-and-image); it remains a sampling-sensitive rule.

## 1. Split

- TUNE: ts-pedestrian-front-end, ts-lpg-conversion, ts-moto-antitheft. All changes were decided here.
- HELD-OUT (reported once, after the decision): ts-motorcycle-silencer, ts-ev-sound, ts-coach-m3, and the expert dev case (run `runs/dev-rear-lamp/lead-text-v2`, text only).
- No deviation. The split is not balanced: the tune split has the three cases whose agent regulation set mostly matches the gold; the held-out silencer and ev-sound have gold regulation sets that look wrong (section 5), so held-out recall is low whatever the policy.
- Requirement-level numbers use the judge pool of each run (every grounded candidate judged against every gold requirement), so a different emitted set is re-matched with the same Hungarian assignment at no new cost (the A1 method). Strict = "same"; lenient = "same" or "partial".

## 2. Baseline tables (P / R / F1 / F2; macro = mean over cases)

precision-v2 (the default), per case:

| case | regulation | page | req strict | req lenient | emitted |
|---|---|---|---|---|---|
| ts-pedestrian-front-end | 1.00/1.00/1.00/1.00 | 0.67/0.57/0.62/0.59 | 0.34/0.34/0.34/0.34 | 0.54/0.55/0.55/0.55 | 127 |
| ts-lpg-conversion | 1.00/0.67/0.80/0.71 | 0.75/0.81/0.78/0.80 | 0.20/0.66/0.31/0.46 | 0.26/0.85/0.40/0.59 | 987 |
| ts-moto-antitheft | 0.75/0.75/0.75/0.75 | 0.78/0.71/0.74/0.72 | 0.46/0.53/0.49/0.51 | 0.60/0.69/0.64/0.67 | 265 |
| **tune macro** | **0.92/0.81/0.85/0.82** | **0.73/0.70/0.71/0.70** | **0.33/0.51/0.38/0.44** | **0.47/0.70/0.53/0.60** | |
| ts-motorcycle-silencer | 1.00/0.25/0.40/0.29 | 1.00/0.10/0.18/0.12 | 0.76/0.18/0.29/0.21 | 0.86/0.21/0.34/0.25 | 37 |
| ts-ev-sound | 1.00/0.50/0.67/0.56 | 0.76/0.21/0.33/0.25 | 0.40/0.20/0.27/0.22 | 0.55/0.27/0.36/0.30 | 104 |
| ts-coach-m3 | 0.33/1.00/0.50/0.71 | 0.28/0.90/0.42/0.62 | 0.14/0.64/0.24/0.38 | 0.18/0.81/0.30/0.48 | 476 |
| dev-rear-lamp | 0.80/1.00/0.89/0.95 | 0.73/0.91/0.81/0.86 | 0.42/0.70/0.52/0.62 | 0.47/0.79/0.59/0.70 | 318 |
| **held-out macro** | **0.78/0.69/0.61/0.63** | **0.69/0.53/0.44/0.46** | **0.43/0.43/0.33/0.36** | **0.52/0.52/0.40/0.43** | |

The dev row reproduces the numbers of the brief (reg 0.80/1.00, page 0.731/0.906, strict F2 0.617, lenient 0.696).

Macro by policy (the three shipped policies; same candidates, so the regulation level only differs where a whole regulation is dropped):

| policy | split | regulation | page | req strict | req lenient |
|---|---|---|---|---|---|
| baseline-v1 | tune | 0.92/0.81/0.85/0.82 | 0.69/0.72/0.70/0.71 | 0.33/0.52/0.38/0.45 | 0.46/0.71/0.53/0.61 |
| precision-v1 | tune | 0.92/0.81/0.85/0.82 | 0.73/0.70/0.71/0.70 | 0.33/0.51/0.38/0.44 | 0.47/0.70/0.53/0.60 |
| precision-v2 | tune | 0.92/0.81/0.85/0.82 | 0.73/0.70/0.71/0.70 | 0.33/0.51/0.38/0.44 | 0.47/0.70/0.53/0.60 |
| baseline-v1 | held | 0.78/0.69/0.61/0.63 | 0.63/0.58/0.44/0.49 | 0.39/0.43/0.32/0.35 | 0.48/0.53/0.39/0.43 |
| precision-v1 | held | 0.83/0.69/0.64/0.64 | 0.70/0.53/0.44/0.47 | 0.44/0.43/0.33/0.36 | 0.52/0.52/0.40/0.43 |
| precision-v2 | held | 0.78/0.69/0.61/0.63 | 0.69/0.53/0.44/0.46 | 0.43/0.43/0.33/0.36 | 0.52/0.52/0.40/0.43 |

Reading: the precision policies raise page P by 0.04 to 0.06 and cost page R by 0.02 to 0.05; on the requirement level they are equal to baseline-v1 within 0.01 on F2. On the synthetic cases the gain of the tuning done on the dev case is therefore small and shows mainly at page level. The dev-only gain (strict F2 0.60 to 0.62) is also small. precision-v1 vs v2 differ only on dev (R128 dropped; one run, so not evidence of anything general).

## 3. Error analysis on the tune split (precision-v2)

Regulation level:

| case | error | cause |
|---|---|---|
| moto-antitheft | R62 emitted (gold R161 missed) | suspected gold error: R62 is the anti-theft regulation for vehicles with handlebars (L-category); R161 is scoped to M1/N1. The agent's reason says so. Not tuned toward. |
| lpg-conversion | R83 missed | judgement call: the agent read R83 (M1 exhaust emissions) as outside a retrofit kit and left it to R67. Gold wants it. Not an obvious agent defect. |
| pedestrian | none | |

Page level (emitted pages not in gold, gold pages not emitted):

- Pages that exist only in the agent's emitted set are mostly R10 Appendix 6/7 (pp 33-34) and Annex 10 (p 108), plus R10 vehicle-level test conditions (pp 71-73). R10 emitted 54 to 83 requirements per case against 26 to 46 gold. Three of the gold-uncited pages recur in all four cases with an R10 gold (including the expert dev gold); I did not write a rule for them (that would be a paragraph-specific rule fitted to the evaluation data). The generic cause is that `product_via_test` limits and test conditions get graded `likely`/`certain` for an ESA.
- Gold pages with no emitted candidate: dominated by candidates the policy dropped for `addressee=test_setup` (about 175 candidates on gold pages in pedestrian alone, all grades) and `applies=unlikely` (lpg 144, moto 48). Including them is not worth it: see section 4.
- Pedestrian R26 and R42: gold has 29 and 23 requirements; the agent emitted 11 and 10 (on gold pages 38 of the 57 R42 candidates were dropped for addressee, most as `test_setup`).
- Over-emission in lpg: 987 requirements against 304 gold; 921 in R67. Page P is 0.75 so the pages are right; requirement strict P is 0.20. The golds cite 1.1 to 1.4 requirements per cited paragraph, while the agent emits several per node (section 4).

Requirement level, bins of emitted candidates on the tune split (strict match rate; the F2/5 bar is about 0.09 at the tune F2 of 0.44):

| bin | n | strict rate |
|---|---|---|
| certain / likely / possible | 459 / 481 / 439 | 0.39 / 0.21 / 0.20 |
| kind test-procedure | 325 | 0.08 |
| test-procedure x certain / likely / possible | 104 / 126 / 95 | 0.17 / 0.02 / 0.05 |
| addressee product / product_via_test | 608 / 771 | 0.39 / 0.17 |
| node holds 1 / 2 / 3-4 / 5+ emitted candidates | 535 / 318 / 224 / 302 | 0.44 / 0.23 / 0.20 / 0.05 |
| rank in node (best-graded first) 1 / 2 / 3 / 4 / 5+ | 792 / 257 / 98 / 62 / 170 | 0.38 / 0.16 / 0.15 / 0.05 / 0.05 |

Two bins sit below the bar and have a structural cause (not a label of a particular regulation or paragraph): weakly graded test-procedure items, and the 4th and later candidates of one node (over-split).

## 4. Changes tried

Decided on the tune split; held-out reported once (same table, one pass). "No-trick" screen: none refers to a regulation, paragraph or case; each is a label or a node-structure rule.

| change | tune: req strict P/R/F1/F2 | tune: req lenient F2 | tune: page F1/F2 | held: req strict P/R/F1/F2 | held: req lenient F2 | held: page F1/F2 | held: dev strict F2 | verdict |
|---|---|---|---|---|---|---|---|---|
| precision-v2 (reference) | 0.33/0.51/0.38/0.44 | 0.60 | 0.71/0.70 | 0.43/0.43/0.33/0.36 | 0.43 | 0.44/0.46 | 0.62 | |
| cap of 3 emitted candidates per node (`max_per_node=3`, best grade first) | 0.37/0.50/0.40/0.44 | 0.60 | 0.71/0.70 | 0.44/0.40/0.31/0.34 | 0.41 | 0.44/0.47 | 0.57 | rejected: tune neutral to slightly positive, held-out F1 and F2 fall (dev -0.05) |
| drop `test-procedure` kind when graded likely/possible (`drop_kind_applies`) | 0.37/0.49/0.40/0.44 | 0.59 | 0.71/0.70 | 0.45/0.41/0.33/0.35 | 0.42 | 0.44/0.46 | 0.60 | rejected: tune lenient F2 down, held-out F2 down |
| both of the above | 0.39/0.48/0.41/0.44 | 0.59 | 0.71/0.70 | 0.44/0.39/0.31/0.33 | 0.40 | 0.44/0.46 | 0.56 | rejected |
| turn off the sparse-`possible`-page rule (`sparse_possible_pages=0`) | 0.34/0.52/0.39/0.45 | 0.61 | 0.72/0.72 | 0.41/0.43/0.32/0.36 | 0.43 | 0.45/0.49 | 0.61 | not adopted: page F2 +0.02 tune, +0.03 held-out, requirement level equal or lower (held-out strict F1 0.33 to 0.32); it only moves the page metric, and it removes a rule the dev bins supported |
| also emit `addressee=test_setup` | 0.22/0.59/0.30/0.41 | 0.56 | 0.69/0.74 | 0.28/0.48/0.27/0.34 | 0.41 | 0.45/0.48 | n/a | rejected: page R up, but strict F1 and F2 fall by 0.08 and 0.03 |
| also emit `applies=unlikely` | 0.29/0.54/0.36/0.44 | 0.59 | 0.70/0.71 | 0.34/0.46/0.27/0.32 | 0.40 | 0.43/0.47 | n/a | rejected |
| drop `applies=possible` | 0.35/0.39/0.35/0.37 | 0.52 | 0.69/0.67 | 0.47/0.34/0.31/0.32 | 0.38 | 0.44/0.47 | n/a | rejected: F2 -0.07 tune |

Why the over-split cap fails out of sample: the 4th-and-later candidates of a node match at 0.05 on tune but at 0.25 to 0.34 on the held-out cases (rank 4: 10 of 29, rank 5+: 13 of 52; nodes with 5+ candidates 29 of 104 = 0.28, the same as single-candidate nodes, 0.29). Over-split is a property of the tune split (mostly lpg R67 tables and lists), not of the data in general. On dev the cap drops 17 candidates and loses 11 strict matches. A bin that crosses the F2/5 bar between splits is unstable and must not be a rule.

Prompt changes (regulation selection, profile) were not run. Reason: on the tune split the selection is correct for pedestrian, and the two misses (moto R161, lpg R83) are the writer's choice and not demonstrable agent errors, so a prompt edit aimed at them would be fitting the gold. Changing the extraction prompt (over-split, test conditions) would re-sample everything downstream (about $2.5 to $5 per case), and one resample's noise on a 100-300 requirement case is as large as the effects above, so it cannot be validated within $8 on six cases. I recommend it as the next step only with at least two resamples per case.

## 5. Suspected gold errors (reported, not tuned toward)

- ts-motorcycle-silencer: gold has R40 (L-category gaseous emissions), R53 (installation of lighting on L3) and R10 (EMC) for a passive metal silencer. The agent chose only R92 (replacement silencing systems), which is the regulation for this product. R53 for a silencer is not plausible. Gold R92 pages 2-6, 14-15: the agent finds 5 of 7. The case's regulation recall of 0.25 is mostly gold.
- ts-ev-sound: gold has R100 (HV powertrain safety) and R48 (lighting installation) for an acoustic vehicle alerting system; the agent's reasons (low-voltage accessory, no lamps) are the better reading. The agent picks R51 (medium confidence).
- ts-moto-antitheft: R161 is for M1/N1; the L-category regulation is R62.
- ts-coach-m3: gold has only R107 (a single regulation for the whole coach case). The agent adds R43 and R10 at medium confidence; R43 (safety glazing) is doubtful, R10 for an emergency-lighting ECU is plausible. Page precision 0.28 and requirement strict P 0.14 are driven by R107 emitting 354 requirements against 108 gold, and by R43 and R10 having no gold at all. The gold's size (108 for a 150-page regulation) suggests it is a partial answer.
- ts-lpg-conversion: R83 for an LPG kit is arguable.

## 6. Conclusion

- The agent under `precision-v2` gets a mean regulation F2 of 0.82 on the three cases with a plausible gold and 0.63 on the held-out set, where the misses are gold-driven. Page F2 0.70 and 0.46; requirement strict F2 0.44 and 0.36, lenient 0.60 and 0.43.
- The emission knobs have at most 0.01 to 0.02 of requirement F2 in them on this data, and nothing validated out of sample. Changing the default would be tuning noise.
- What would move the number: (1) extraction that cites one requirement per paragraph and does not split lists (over-split looked like the clearest structural error on tune, but the held-out cases do not show it, so it is unproven); (2) grading `product_via_test` limits and test conditions down for a component (`ESA` limits and vehicle test states); (3) a better gold. These need paid extraction runs with repeats.
- Opt-in code added (default off, so default behaviour and the replay of `precision-v2` are unchanged): `Policy.max_per_node` / `cap_nodes`, `Policy.drop_kind_applies`, and the named policy `cap3-experiment` (`AI_AGENT_POLICY=cap3-experiment`). `python eval/test_ai_agent.py`: 52 passed.
