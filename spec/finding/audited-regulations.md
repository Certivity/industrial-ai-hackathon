# Findings: a blind audit of regulation applicability for the 26 `testing/ts-*` cases

Status: tooling and first measurement, 2026-10-25. Companion to `spec/finding/selection-tuning.md` section 2 and `testing/README.md`. Files: `eval/audit_regs.py` (candidates, adjudication, tally), `eval/score_audited.py` (scorer), `testing/_audited_regs.json` (protocol, votes, quotes, decisions), `testing/_audited_scores.json` (per-case rows), raw replies in `runs/_audit/replies/` (ignored by git).

## 1. Why

The regulation level of the DeepSeek golds is unreliable (R10 in all 20 new golds including passive products, superseded R23/R38, R13H for an N2 truck), so regulation P/R against them measures agreement with that writer. The audit gives a second reference that sees the regulation text, not the writer's habits. It is a measurement fix: the protocol below was written into `testing/_audited_regs.json` (key `protocol`, with the full system prompt) before any DeepSeek call and was not changed afterwards.

## 2. Protocol (fixed in advance)

- **Candidates per case**: gold regulations, plus the regulations of the agent runs `c2-base`, `c2-vet2`, `c2-v2` (`upper_bound.json`, `regulations.json` selected, `citation_hop.json` vetted.add), plus 2 distractors: the regulations outside that union with the highest TF-IDF cosine between their card (title, scope, contents; `runs/_cards`) and `technical_spec.md`. 169 candidates in 26 cases (89 gold pairs, 28 agent-only, 52 distractors). `c2-v2` exists for the 10 tune cases only. Shuffled; the source is never sent.
- **Per request**: the spec, the card, the full verbatim paragraph 1 of the base PDF (regcomp parse), and the supersession note, for at most 4 candidates. Fixed rules: decide from the texts given; the vehicle categories of the scope count; cite the current, not a superseded regulation; a horizontal regulation like R10 only if the product has electrical/electronic sub-assemblies. Answer: applies yes/no, scope clause quoted, product part, reason.
- **Model**: `deepseek-flash` via the helpers of `eval/xprovider.py`, thinking off, temperature 0.7. Nothing from `cases/` is sent. 162 requests.
- **Samples**: 3 per candidate, each with its own shuffle of the case's candidates and its own batches. Majority (at least 2 of 3) = applies; 2-1 = contested.

## 3. Adjudicator quality

| measure | value |
|---|---|
| candidates accepted | 83 of 169 (gold 62 of 89, agent-only 17 of 28, distractors 4 of 52) |
| distractor false-accept rate | 4 of 52 = 7.7%: R174 for the coach, R171 for the power-steering case, GTR 9 for the pedestrian front end (all 3/3), R101 for ev-sound (2/3) |
| all 3 samples agree | 152 of 169 = 90%; 17 contested |
| yes votes whose scope quote is verbatim in the scope text | 200 of 252 (the rest is paraphrase, not checked further) |
| hand read, 15 random decisions (seed 7) | 12 right, 3 debatable, 0 clearly wrong |

The hand read opened the scope text for each: the 3 debatable ones are R155 accepted 3/3 for a brake system and for a speedometer (the scope reads "vehicles ... with regard to cyber security, M and N" and the product has ECUs, but R155 approves vehicles, not components), and R128 for the direction-indicator lamps at 2/3 (whether the lamps use replaceable LED light sources is not in the spec). One correct "no" rests on the supersession note alone (R38's paragraph 1 is a definitions list). The read was made by the person who ran the audit and who had seen the votes; it is a sanity check, not an independent label.

Limits. (1) The adjudicator is the family of model that wrote the golds, and it is lenient with vehicle-level regulations (R155, R156, R10) when the spec lists electronics; the hand read found no wrong decision but 2 of 3 doubts are of that kind. (2) The audited set can only contain candidates: a regulation nobody proposed and no distractor hit is invisible, so audited recall is a ceiling-style figure and audited precision is flattered because every agent regulation was put to the vote and the agent proposed most of what the adjudicator accepts. (3) The 90% agreement is within one model; it says the decision is stable under shuffling, not that it is correct. (4) Scope text is paragraph 1 only; where it is a definitions list (R38) or short, the card and supersession note decide.

## 4. What the audit changes in the gold

Of 89 gold (case, regulation) pairs the audit rejects 27 (30%):

- R10 for 6 passive products: windscreen, trailer conspicuity, spare wheel, mechanical coupling, replacement catalyst, motorcycle silencer (0/3 each). It keeps R10 (3/3) for the other 20 cases.
- Superseded: R38 and R23 (rear lamps van, 0/3).
- Others: R48 (ev-sound; o3 trailer 1/3), R53 (tricycle, silencer), R148 (adaptive headlamp), R79 (braking system, lane keeping), R26 (frontal crash), R83 (replacement catalyst, lpg 1/3), R39 (speed limiter, spare wheel), R107 (speed limiter 1/3), R161 (antitheft), R128 (motorcycle headlamp 1/3), R40 (silencer), R13H (N2 truck AEBS), R6 (direction indicators), R104 (trailer conspicuity).

Full list with votes: `testing/_audited_regs.json` (`applies: false`, `sources` contains `gold`).

Agent-only regulations accepted (not in the gold, majority yes): 17 pairs over 9 cases, for example R155 and R156 (braking system, lane keeping, AEBS, speedometer), R128 and R37 (van rear lamps, direction indicators), R62 (antitheft), R43 and R10 (coach). The audit therefore also says the golds miss regulations the agent found; part of the "agent precision loss" against the gold is gold incompleteness.

## 5. Agent runs against both references

`python eval/score_audited.py --runs c2-base c2-vet2 c2-v2` (macro mean ± sample std over cases; the submitted set is the regulations of `upper_bound.json`, as `score_local` counts them).

| run | part | vs original gold P / R / F1 / F2 | vs audited set P / R / F1 / F2 |
|---|---|---|---|
| c2-base | tune (10) | 0.80 / 0.71 / 0.73 / 0.71 (± 0.26 / 0.19 / 0.19 / 0.18) | 0.98 / 0.93 / 0.95 / 0.94 (± 0.06 / 0.11 / 0.08 / 0.09) |
| c2-base | heldout (16) | 0.86 / 0.63 / 0.66 / 0.63 (± 0.21 / 0.27 / 0.17 / 0.22) | 0.93 / 0.86 / 0.86 / 0.86 (± 0.16 / 0.22 / 0.18 / 0.20) |
| c2-vet2 | tune (10) | 0.78 / 0.77 / 0.74 / 0.75 (± 0.25 / 0.22 / 0.18 / 0.19) | 0.91 / 0.93 / 0.92 / 0.93 (± 0.16 / 0.11 / 0.13 / 0.11) |
| c2-vet2 | heldout (16) | 0.81 / 0.67 / 0.67 / 0.66 (± 0.24 / 0.28 / 0.18 / 0.22) | 0.83 / 0.86 / 0.82 / 0.83 (± 0.23 / 0.22 / 0.19 / 0.20) |
| c2-v2 | tune (10) | 0.70 / 0.76 / 0.71 / 0.73 (± 0.27 / 0.22 / 0.22 / 0.22) | 0.86 / 0.98 / 0.90 / 0.94 (± 0.19 / 0.06 / 0.12 / 0.07) |

Page level, on the regulations both gold and audit accept (gold and submission cut to them): P 0.58 / R 0.92 / F2 0.82 on tune, P 0.59 / R 0.83 / F2 0.75 on heldout, nearly the same for every run.

Reading it. Every run scores 0.17 to 0.23 higher in F2 against the audit than against the gold, in both precision and recall (gold regulations the agent left out are no longer misses; agent-only ones that the audit accepts are no longer false alarms). The ranking of the variants changes: against the gold c2-vet2 beats c2-base on F2 (0.75 vs 0.71 tune, 0.66 vs 0.63 heldout) because it adds regulations the gold has; against the audit c2-base is at or above c2-vet2 (0.94 vs 0.93 tune, 0.86 vs 0.83 heldout) because the added citations are mostly not accepted. c2-v2 (tune only) trades precision (0.86) for recall (0.98), F2 equal to c2-base on the audit (0.94 vs 0.94) and 0.02 above it on the gold (0.73 vs 0.71). The differences between variants are inside one std in both references (10 or 16 cases); do not read a winner from them. The audit is a different reference with its own errors (section 3), not the truth: use both, and prefer a change that does not lose on either.
