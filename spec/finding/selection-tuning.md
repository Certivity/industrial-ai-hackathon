# Findings: tuning the cheap stages (regulation selection, citation hop) on the cheap bench

Status: results, 2026-10-25. Code: `src/ai_agent/regulations.py`, `config.py`, `pipeline.py` (two opt-in switches, default unchanged). Tests: `eval/test_selection.py`. Runs: `runs/<case>/c2-*`. Tool: `eval/bench_cases.py ... --stop-after sections` (`spec/finding/cheap-bench.md`).

## Summary

- **The default stays unchanged (`AI_AGENT_SELECT=v1`, `AI_AGENT_VET=v1`).** The best variant (`AI_AGENT_VET=v2`, recall-oriented citation vetting) gains +0.04 regulation F2 on tune and +0.03 on held-out, but loses 0.05 on dev, and every difference is inside the noise (see section 4).
- **Section 8 (v3, shortlist then verify against the scope text) is also not the default**: on held-out it gains 0.04 audited recall and loses 0.08 audited precision (seven unaudited extras count as wrong); dev is 1.00 / 1.00.
- The section walks are not the problem: inside the regulations the agent chose, the selected sections already reach 90-100% of the gold requirements on 9 of 10 tune cases (windscreen R43 131/156 is the exception: the walk made 2 reads and then `exclude`d six Annex 3 subsections unread). The page-level loss comes from the regulation level.
- The regulation misses on tune are mostly doubtful golds: R10 on passive products (windscreen, bus lamps, mechanical coupling, van lamps; the selector says "no electronics", which reads correctly), R13H for an N2 truck (its scope is M1/N1), R79 for a brake system that only senses steering angle, R128 for a headlamp with integral LEDs, R23/R38 (superseded, replaced by R148). I did not tune toward them.

## 1. Split and setup

`testing/_split.json`: 10 tune cases, 16 held-out (6 old + 10 new), dev (`cases/dev-rear-lamp`, expert gold) as the independent check. All choices were made on tune; held-out and dev were run once, for the final candidate only. Baseline `c2-base` (default prompts, 26 cases; dev baseline = `cheap-base`). Page level is the upper bound (every selected node cited once; real page R is about 0.8 of UB R).

## 2. Baseline diagnosis (tune)

Gold regulations missed: adaptive-headlamp R148 (rejected: "no signalling lamps"), braking R79, windscreen R10, bus-lamps R10, led-headlamp R128, van R38/R23/R10 (R10 only came back through the citation hop), aebs R13H, coupling R10. Extras: R155/R156 (medium, horizontal) for braking and AEBS, R128/R37 for lamps. Three of the gold regulations the agent missed (R148 headlamp, R79 braking, R128 led-headlamp) were cited by the text of the selected sections, and the hop vetting skipped them; the hop added only one regulation in 10 cases.

## 3. What was tried (tune, macro of 10; reg P / R / F1 / F2, page-UB P / R / F1 / F2, mean regulations per case)

| variant | reg P | reg R | reg F1 | reg F2 | pg P | pg R | pg F1 | pg F2 | regs |
|---|---|---|---|---|---|---|---|---|---|
| `c2-base` (v1 / v1) | 0.80 | 0.71 | 0.73 | 0.71 | 0.51 | 0.68 | 0.54 | 0.61 | 3.3 |
| `c2-v2` selection prompt v2 (recall-oriented, `confidence` carries the doubt) | 0.70 | 0.76 | 0.71 | 0.73 | 0.49 | 0.70 | 0.54 | 0.62 | 4.0 |
| `c2-vet2` vetting prompt v2 (a part or function of the product under the cited regulation is enough) | 0.78 | 0.77 | 0.74 | 0.75 | 0.50 | 0.70 | 0.55 | 0.62 | 3.7 |
| `c2-both` | 0.71 | 0.82 | 0.73 | 0.77 | 0.49 | 0.72 | 0.54 | 0.63 | 4.3 |

Stds over cases are 0.17-0.27 for each of these (baseline: reg F2 0.18, page F2 0.19). Selection v2 buys recall with precision (4 gold regulations back, 7 extra low-confidence ones: R155/R156, R127, R37, R128) and does not move page F2. `c2-both` has the highest recall but the lowest regulation precision, so I did not choose it. `c2-vet2` was chosen as the variant that keeps precision (0.78 against 0.80) and has a stated mechanism (the regulations come from citations in text the agent selected). Not tried (budget and noise): walk prompt changes (`exclude` only after reading; windscreen only), effort levels, `max_regulations`.

## 4. Chosen candidate against the baseline, out of sample (`c2-vet2` against `c2-base`)

| split | n | variant | reg P | reg R | reg F1 | reg F2 | pg P | pg R | pg F1 | pg F2 | regs |
|---|---|---|---|---|---|---|---|---|---|---|---|
| tune | 10 | base | 0.80 | 0.71 | 0.73 | 0.71 | 0.51 | 0.68 | 0.54 | 0.61 | 3.3 |
| tune | 10 | vet2 | 0.78 | 0.77 | 0.74 | 0.75 | 0.50 | 0.70 | 0.55 | 0.62 | 3.7 |
| held-out | 16 | base | 0.86 | 0.63 | 0.66 | 0.63 | 0.53 | 0.57 | 0.45 | 0.50 | 2.7 |
| held-out | 16 | vet2 | 0.81 | 0.67 | 0.67 | 0.66 | 0.48 | 0.59 | 0.46 | 0.51 | 3.1 |
| dev | 1 | base | 1.00 | 1.00 | 1.00 | 1.00 | 0.48 | 1.00 | 0.65 | 0.82 | 4 |
| dev | 1 | vet2 | 0.80 | 1.00 | 0.89 | 0.95 | 0.44 | 1.00 | 0.61 | 0.80 | 5 |

Stds (held-out, 16): base reg F2 0.22, page F2 0.21; vet2 0.22 and 0.20. Nodes selected per case: 543 (base) and 603 (vet2) on held-out, 693 and 728 on tune; dev 826 and 936.

Cases that changed (reg F2 base to vet2): headlamp 0.71 to 0.91 (R148), braking 0.62 to 0.88 (R79), bus-lamps 0.79 to 0.71 (R37, R128 extra), replacement-catalyst 0.38 to 0.71, lpg-conversion 0.71 to 1.00, lane-keeping 0.95 to 0.83 (3 extras), airbag 0.29 to 0.28, dev 1.00 to 0.95 (R128 extra). Four cases up, four down; the 16 other cases are identical. The held-out gain is carried by two cases, so it is not distinguishable from noise, and dev (the only expert gold) goes the other way. Page F2 moves by 0.01-0.02 everywhere because the regulations added by a hop are mostly small.

## 5. Cost

New Anthropic spend: about $7.4 of $14 (baseline on 20 new cases $5.30; selection v2 on tune $1.45; vetting v2 on tune $0.17; both $0.09; vetting v2 on held-out $0.37 and dev $0.04). The 6 old cases and the unchanged calls replayed from the cache. No full end-to-end run was made.

## 6. Caveats

DeepSeek golds (R10 is in all 20 new golds and R155 in 3 and R156 in 2); UB page precision is pessimistic; results are one sample of the model per case (the temperature of the Anthropic calls is not controlled, so rerunning a changed prompt re-samples everything it feeds). The recall-oriented switches are opt-in; whether to turn them on depends on whether the user prefers recall at the cost of one or two extra regulations per case (extraction cost grows with them; the real run drops a regulation only under `regulation_check`, which `precision-v2` does not use).

## 7. How to run

```
AI_AGENT_VET=v2 python eval/bench_cases.py testing/ts-* --stop-after sections --split testing/_split.json --part tune --name c2-vet2 --max-cost 0.8 --budget 3
AI_AGENT_SELECT=v2 ...        # selection prompt v2
python eval/test_selection.py
```

## 8. Shortlist then verify (v3)

Status: results, 2026-10-25. Code: `src/ai_agent/verify.py`, `pipeline.py` (the `settings.select == "v3"` branches), `config.py`. Tests: `eval/test_selection.py` (10 tests, 7 new). Runs: `runs/<case>/c2-v3`, `c2-v3b`, `c2-v3c`, `c2-v3c-vet1`; dev `runs/dev-rear-lamp/c2-v3c`.

**Result: v3 is not the default.** The default stays `AI_AGENT_SELECT=v1`. On held-out v3 gains 0.04 audited recall and loses 0.08 audited precision; the adoption rule (recall up with at most 0.02 precision lost, or F1 and F2 up against both references) is not met. Dev passes (1.00 / 1.00). The bumper was therefore not rerun and `submission-v3.json` was not written.

### 8.1 Method

1. **Shortlist** = the v2 selection (`SELECT_SYSTEM_V2`, so its calls replay from the `c2-v2` cache) plus the regulations cited by the text of the regulations that were kept and that pass vetting (vet v2).
2. **Verify**, one call per shortlisted regulation (`stage verify`, effort medium, up to 5 in parallel). Input: the profile, the card, the verbatim Scope section (paragraph 1 and its sub-paragraphs, regcomp parse of the version the agent walks), paragraph 2 (definitions) only when it is at most 2500 characters, and the supersession note. Output (JSON schema): `applies` yes/no, `scope_clause`, `product_part`, `reason`. The rules are the three expert conventions of the other prompts: the current regulation, not a superseded one; a horizontal regulation (EMC, cyber security, software update) only when the product itself contains the electrical/electronic or software sub-assembly; a vehicle-level installation regulation only when the product is a device or part its installation provisions address.
3. **Quote check in code** (`quote_is_verbatim`): the quote must be a contiguous run of the scope text up to case, punctuation, spacing and thousands separators (pieces joined by an ellipsis are checked one by one; fewer than 3 tokens proves nothing). A yes whose quote fails is asked once more with the failure stated; if it fails again the regulation is unverified and is dropped. Of 112 verifications on tune and held-out, 11 yes answers needed the retry and 1 stayed unverified.
4. **Order of stages.** The shortlist from the selection is verified first, only the kept regulations are walked, the citation hop runs on their text, and the vetted citations are verified before they are walked (a regulation the verifier dropped is not offered to the hop again). This is cheaper than walking the whole shortlist to find its citations, and the text of a regulation that does not apply does not hand out requirements. `regulations.json` holds `shortlist`, `verification` (per regulation, with `quote_verbatim`, `retried`, `accepted`) and `selected` (the kept ones).
5. **Switches.** `AI_AGENT_SELECT=v3`; `AI_AGENT_VET` then defaults to v2 (v1 on request). A second verify sample ("keep on agreement or on either") was not built: the errors below are systematic readings of the scope text, not sample noise.

### 8.2 What was tried on tune (10 cases, regulation level, macro; P / R / F1 / F2)

| variant | vs original gold | vs audited set | regs per case |
|---|---|---|---|
| `c2-base` (v1) | 0.80 / 0.71 / 0.73 / 0.71 | 0.98 / 0.93 / 0.95 / 0.94 | 3.3 |
| `c2-v2` (shortlist only, no verify) | 0.70 / 0.76 / 0.71 / 0.73 | 0.86 / 0.98 / 0.90 / 0.94 | 4.0 |
| `c2-v3` (first verify prompt, with a fourth rule: a regulation that approves whole vehicles applies to a component only if its scope reaches components) | 0.81 / 0.58 / 0.67 / 0.61 | 0.90 / 0.66 / 0.74 / 0.68 | not computed |
| `c2-v3b` (that rule removed: it was mine, not one of the conventions already in our prompts) | 0.81 / 0.56 / 0.65 / 0.59 | 0.90 / 0.62 / 0.72 / 0.66 | not computed |
| `c2-v3c` (chosen: a horizontal regulation whose scope speaks of vehicles reaches the product through its ECU or software) | 0.68 / 0.63 / 0.64 / 0.63 | 0.88 / 0.82 / 0.84 / 0.83 | 3.1 |
| `c2-v3c-vet1` (vet v1 feeding the hop) | identical to `c2-v3c` | identical | 3.1 |

Stds over cases are 0.28-0.37 for the v3 variants (0.06-0.26 for base on the audit). Vet v1 and v2 give the same sets: every regulation the hop offered was rejected by the verifier, so vet v2 stays the choice for v3 (it costs nothing). The verifier reads "applies to vehicles" strictly; the third prompt softened that for horizontal regulations and restored R155/R156 for the power-steering and cyber-security products. Page-UB for `c2-v3c` on tune: P 0.42, R 0.63, F1 0.49, F2 0.56 (base 0.51 / 0.68 / 0.54 / 0.61). Three prompts were tried on tune; none beat `c2-base` there. Offline, with the stored verdicts, "keep every high-confidence v2 pick without verification and verify the rest" gives 0.98 / 0.92 on the audit, the same as `c2-base`: the confidence of the selection already carries most of what the verifier adds.

### 8.3 Out of sample, `c2-v3c` against `c2-base` (same cases)

| split | n | variant | vs gold P / R / F1 / F2 | vs audit P / R / F1 / F2 | page-UB P / R / F1 / F2 | regs |
|---|---|---|---|---|---|---|
| tune | 10 | base | 0.80 / 0.71 / 0.73 / 0.71 | 0.98 / 0.93 / 0.95 / 0.94 | 0.51 / 0.68 / 0.54 / 0.61 | 3.3 |
| tune | 10 | v3c | 0.68 / 0.63 / 0.64 / 0.63 | 0.88 / 0.82 / 0.84 / 0.83 | 0.42 / 0.63 / 0.49 / 0.56 | 3.1 |
| held-out | 16 | base | 0.86 / 0.63 / 0.66 / 0.63 | 0.93 / 0.86 / 0.86 / 0.86 | 0.53 / 0.57 / 0.45 / 0.50 | 2.7 |
| held-out | 16 | v3c | 0.78 / 0.66 / 0.65 / 0.64 | 0.85 / 0.90 / 0.85 / 0.87 | 0.50 / 0.59 / 0.44 / 0.50 | 3.2 |
| dev | 1 | base | 1.00 / 1.00 / 1.00 / 1.00 | (not a ts case) | 0.48 / 1.00 / 0.65 / 0.82 | 4 |
| dev | 1 | v3c | 1.00 / 1.00 / 1.00 / 1.00 | (not a ts case) | 0.48 / 1.00 / 0.65 / 0.82 | 4 |

Held-out stds (v3c): regulation F2 0.19 against the gold, 0.16 against the audit (base 0.22 and 0.20); page-UB F2 0.20. Dev: R10, R48, R148, R150 kept and R128 dropped, so v3 is the only variant that removes the known wrong extra that v2 and vet2 add on dev. Against the audited set, held-out recall is +0.04 and precision -0.08; F1 -0.01, F2 +0.01. Page-UB moves by at most 0.03. Over the 112 verifications (tune and held-out) the verifier dropped 18 of the 22 that have an audited negative verdict and 8 of the 79 that have a positive one, and kept 4 audited negatives; 11 verified regulations were never audited.

Why precision fell: seven regulations v3c submits on held-out were never audit candidates (R155 for ev-sound, frontal crash, speed limiter and pedestrian; R156 and R94 for pedestrian; R79 for frontal crash), and `score_audited` counts such a regulation as wrong. If those seven are counted as accepted (an upper bound: the audit was lenient with R155/R156), v3c scores 0.94 / 0.91 / 0.91 / 0.90 on held-out against base 0.93 / 0.86 / 0.86 / 0.86, an F1 gain of 0.05. The audit should be extended to them before reading the table either way; I did not, because the audit protocol was fixed in advance and its candidate list is rebuilt from all runs.

### 8.4 Where v3 loses (tune)

- **Mechanical coupling (R102)**: the only shortlisted regulation, dropped (its definitions say that coupling devices with no adjusting effect are not covered; gold and audit say it applies). One case with no regulation at all costs the tune macro about 0.1 of P and R and widens the std. I did not tune toward it.
- **R10 for passive lamps** (bus signal lamps, van rear lamps): dropped by the "contains an electronic sub-assembly" convention; gold and audit keep it.
- **R148 for the adaptive headlamp, R79 for the braking system, R128 for the integral-LED headlamp**: the citation hop found them (vet v2) and the verifier dropped them on the scope text. The audit also rejects R148 and R79, so against the audit this is a correct "no"; against the original gold it costs recall. This is the part of the idea that does not work: a citation is evidence of a link, the scope text is evidence of an exclusion, and the verifier follows the second.

### 8.5 Cost

New Anthropic spend of this section: about $4.65 of the $12 (tune: first verify prompt $0.48, `c2-v3b` $0.46, `c2-v3c` $0.46, vet v1 $0.03; held-out $3.01; dev $0.21). The 10 tune selections replayed from the `c2-v2` cache; held-out needed new v2 selections ($0.12-0.15 each), the verifications (about $0.02 each at medium effort) and the walks of regulations the base run did not walk. $4.99 more was replayed (usage.json of `c2-v3c`).

### 8.6 Caveats

The audit and the verifier use the same idea (the scope text decides), so agreement with the audit is partly by construction; the original gold (DeepSeek, R10 almost everywhere) is the other reference and v3c loses precision against it on both splits. The audit is lenient with R155/R156/R10 and holds candidates only. Three prompts were tried on 10 tune cases; held-out and dev were run once, for `c2-v3c` only. One sample of the model per case (temperature not controlled). A tune std of 0.3 means differences under about 0.1 are noise. What would make v3 worth turning on: an extended audit of the unaudited extras (8.3), or a verifier asked only about the low- and medium-confidence picks of v2 (offline it matches the base on tune; not run on held-out).

### 8.7 How to run

```
AI_AGENT_SELECT=v3 python eval/bench_cases.py testing/ts-* --stop-after sections --split testing/_split.json --part tune --name c2-v3c --max-cost 0.6 --budget 3
AI_AGENT_SELECT=v3 python src/ai_agent/run.py cases/dev-rear-lamp --stop-after sections --out runs/dev-rear-lamp/c2-v3c --max-cost 1
python eval/score_audited.py --runs c2-base c2-v3c
python eval/test_selection.py
```
