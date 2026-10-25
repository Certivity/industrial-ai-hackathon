# Findings: the drift agent (which requirements change between two versions of a regulation)

Status: results, 2026-10-25. The sub-goal of README.md section 3 / `spec/proposal.md` B1 and B3: requirements derived from an OLD version + the NEW version in; which requirements are modified, removed or have to be added, and why, out. Code: `src/ai_agent/drift.py` (alignment, diff, reasons, agent), `src/ai_agent/run_drift.py` (CLI), `eval/drift_cases.py` (the cases), `eval/score_drift.py` (the score). The model is `claude-sonnet-5-5`. The agent never opens an `expected.json`; the scorer does, afterwards.

## Summary

- **The deterministic alignment does most of the work and is cheap.** `regcomp.parse.Node.text_hash` (ignores footnote numbers, line breaks, list layout) plus label equality, a Hungarian assignment on token similarity and a word diff decide what changed without a model. Page shifts and renumbering never reach the model: in `drift-r156-ota-renumber` 13 of 57 paragraphs change number and 0 requirements are flagged; in `drift-r10-emc-few-changes` nothing changes in 57 paragraphs and nothing is flagged.
- **On `subgoal/dev` (UN R175, the experts' gold): 7 of 7 modified+removed requirements flagged**, kind (modified/removed) right on all 7, 5 false flags among 87 unchanged requirements (0.057), added 13 of 17 matched with 20 reported. Three runs of the same agent without the replay cache: recall 7/7, 6/7, 6/7; false flags 5, 2, 0; added matched 13, 15, 14 of 17 (20, 27, 24 reported). Overall F2 (flagged ids + added items as one count) 0.78 / 0.80 / 0.79.
- **On the ten DeepSeek cases: flagged recall 0.80 (36 of 45), precision 0.88 (36 of 41), 5 false flags among 556 unchanged requirements (0.009); added recall 0.86 (25 of 29), precision 0.69 (25 of 36); overall F2 0.82.** The golds are DeepSeek's and noisy; read the misses before the numbers (section 4).
- **It is cheap: $1.08 of Anthropic spend for everything** (121 paid calls over every run, repeats and ablations included; judge $0.92, added extraction $0.17), 4 to 25 s a case. A single run of one case costs $0.00 to $0.08 because only changed paragraphs that carry a requirement reach the model (medium effort, 1.5K to 5K tokens a call); added extraction runs at high effort (`DEFAULT_EFFORT["obligations"]`), once per case.
- **The remaining disagreement is mostly a convention, not a defect:** a new sentence in a changed paragraph is "added" for the agent (sentence-level atomic requirements, as in `subgoal/dev`) and "modified" for DeepSeek's gold (paragraph-level). 7 of the 9 missed flags and most of the "unmatched added" items are this one thing.

## 1. Design

1. **Parse** both versions (`regcomp.parse`, grids on); content nodes = `para` and `table`.
2. **Align** (`drift.align`): (a) same label and same `text_hash` is SAME; (b) every other old node competes with every other new node: score = token similarity (sparse Jaccard prefilter, then `difflib` ratio) + 0.15 for the same label + 0.02 for the same parent; a pair is allowed at similarity 0.6, at 0.3 with the same label, at any similarity for equal hashes; `scipy.optimize.linear_sum_assignment` picks the best one-to-one pairing. Equal hash under another label is RENUMBERED, otherwise MODIFIED (and `renumbered` when the label moved). The rest is REMOVED (old) and ADDED (new). Counts for UN R175: 180 SAME, 13 MODIFIED, 2 REMOVED, 36 ADDED. All 36 regulations with a latest version align in under 70 s each (UN R49, 2,361 nodes, is the slowest); most take a few seconds.
3. **Map requirements to old nodes** (`map_requirements`): by `source.paragraph` through the platform's label normalisation; if that node's words hardly contain the requirement, or the label does not exist, by BM25 over the whole old version. Dev: all 94 map by label.
4. **SAME and RENUMBERED nodes are never flagged.** A MODIFIED node whose words differ only in case or punctuation is gated out without a model call.
5. **Judge** (one Sonnet call per changed node that carries requirements, medium effort, structured output): old paragraph, requirements on it, the new paragraph with the word diff; a MODIFIED node below similarity 0.95 and every REMOVED node also get up to 3 / 6 candidate new paragraphs (BM25 over added and modified new nodes) so a requirement whose sentence moved is not called removed. Per requirement: `modified` (with `new_text`: the old requirement rewritten with the change, and the new paragraph it now sits in), `unchanged` or `removed`, plus `new_obligations` the new paragraph states that no old requirement covers. A REMOVED node with no resembling new paragraph is `removed` without a call. The rules name what is not a change: renumbering, spelling, abbreviation, unit spelling, footnote renumbering, headings, same meaning.
6. **Added**: ADDED nodes that no modified requirement now sits in, inside the sections the old requirements cover (same first number, or the same annex), go to one extraction call per 20K characters (one entry per node, each requirement with a verbatim quote checked against the node; high effort; examples are the regulation's own old requirements); plus the `new_obligations` of the judge; near-duplicates of a modified `new_text` are dropped.
7. **Reasons are built in code**, in the gold's format: `Paragraph 5.1.4 (formerly 5.1) of UN R175 was amended in version 1.0.0: 'a' became 'b'; 'c' was added.`, `... the provision '...' no longer appears.`, `... is new in version 1.0.0: '...'.` (word diff with edits at most 2 unchanged words apart merged, at most 8 clauses, phrases cut at 170 characters). `source` of a modified or added item is the NEW paragraph and page.
8. `changes.json` is validated with `tools/validate.py --requirements-old` (and `--strict` for the dev output).

Replay cache and `--max-cost` come from `ai_agent/llm.py`. `new_in_modified` (default on) lets the judge's `new_obligations` become `added` items.

## 2. The cases (`spec/testing/cases-drift/`)

Ten real base to latest pairs, a window of sections each (33 to 83 requirements, 3 to 25% of paragraphs affected), requirements and changes written by DeepSeek (`deepseek-flash`, thinking off, 26 calls, 102K prompt tokens, 52K completion tokens). Call 1 writes `requirements_old.json` from the old window text in the format of `subgoal/dev`; call 2 decides, from the old and new paragraphs, the diff and the list of added paragraphs, which requirements are modified or removed, writes the new wording and lists the added obligations; code then drops anything that contradicts the alignment (nothing was dropped) and builds the reasons. See `spec/testing/cases-drift/README.md` for the table; `notes.md` in each folder says what changed and the trap.

Windows were chosen after aligning all 35 other regulations with a latest version (`python eval/drift_cases.py scan`): a latest version that only adds ADS provisions is common (R10, R39, R64, R94, R100, R131, R174), R156 and R149 renumber, R132 merges a list, R51 changes formulas.

## 3. Results

Agent run on each case with `run_drift.py`, scored by `eval/score_drift.py --all` (flagged = modified + removed by `requirement_id`; added matched one to one on paragraph key and token similarity 0.5; overall F2 counts flagged ids and added items together; "lenient" counts a gold flag as covered when the agent reports an added item at its paragraph).

| Case | Old reqs | Gold m/r/a | Agent m/r/a | Flagged R | Flagged P | False flags | Added R | Added P | Overall F2 | Lenient: flagged R / added P |
|---|---|---|---|---|---|---|---|---|---|---|
| subgoal-dev (experts) | 94 | 6/1/17 | 11/1/20 | 7/7 | 7/12 | 5/87 | 13/17 | 13/20 | 0.78 | 1.00 / 0.65 |
| drift-r10-emc-few-changes | 63 | 0/0/4 | 0/0/5 | 0/0 | 0/0 | 0/63 | 4/4 | 4/5 | 0.95 | 1.00 / 0.80 |
| drift-r100-battery-adsf | 83 | 8/0/3 | 10/0/3 | 6/8 | 6/10 | 4/75 | 2/3 | 2/3 | 0.70 | 0.88 / 1.00 |
| drift-r131-aebs-rewrite | 61 | 0/1/3 | 1/0/3 | 1/1 | 1/1 | 0/60 | 2/3 | 2/3 | 0.75 | 1.00 / 0.67 |
| drift-r132-reagent-restructure | 55 | 4/0/4 | 4/0/5 | 4/4 | 4/4 | 0/51 | 4/4 | 4/5 | 0.98 | 1.00 / 0.80 |
| drift-r149-lamp-uid-removed | 74 | 9/2/1 | 8/2/1 | 10/11 | 10/10 | 0/63 | 1/1 | 1/1 | 0.93 | 0.91 / 1.00 |
| drift-r156-ota-renumber | 37 | 0/0/2 | 0/0/2 | 0/0 | 0/0 | 0/37 | 2/2 | 2/2 | 1.00 | 1.00 / 1.00 |
| drift-r174-belt-reminder | 51 | 2/0/1 | 1/0/4 | 1/2 | 1/1 | 0/49 | 1/1 | 1/4 | 0.59 | 1.00 / 0.50 |
| drift-r39-speedometer | 57 | 5/0/4 | 4/0/2 | 4/5 | 4/4 | 0/52 | 2/4 | 2/2 | 0.71 | 0.80 / 1.00 |
| drift-r51-noise-asep | 74 | 3/1/7 | 5/0/9 | 4/4 | 4/5 | 1/70 | 7/7 | 7/9 | 0.95 | 1.00 / 0.89 |
| drift-r64-tyre-terms | 46 | 10/0/0 | 6/0/2 | 6/10 | 6/6 | 0/36 | 0/0 | 0/2 | 0.62 | 0.80 / 1.00 |
| **Ten cases, total** | 601 | 41/4/29 | 39/2/36 | 36/45 | 36/41 | 5/556 | 25/29 | 25/36 | **0.82** | |

(Flagged R and P in the totals: recall 0.80, precision 0.88, F2 0.81; added recall 0.86, precision 0.69.)

Ablations (same runs, replayed): without `new_obligations` of modified paragraphs the ten cases give the same flagged result, added recall 0.55 (16 of 29) and precision 0.84, overall F2 0.73 against 0.82; on dev added 12 of 17 against 13. Letting a changed paragraph show the added paragraphs that resemble it (the move check of step 5) took dev from 8 false flags and P 0.47 to 5 and 0.58 (R-022 to R-024, three sentences that moved to a new paragraph 5.1.5.1, stopped being called "removed"), and the ten cases from 34/45 to 36/45 flagged. That was the only change made after seeing dev results.

## 4. Insights

- **Alignment errors: none seen on the 11 cases** (I read every judged paragraph pair of the dev run and the notes of the others); no requirement sat on a mis-paired node. The weak spot is by construction: a paragraph rewritten under the same label with little text in common (R131 5.4.5, similarity under 0.3) is REMOVED + ADDED; the candidate search turns it back into one `modified` requirement, where the DeepSeek gold says "removed" and three added (kind mismatch, the only one in the ten cases). Dev's old 6.5, split into 6.5.x and 6.6.x in the new version, is the same pattern and works: R-084 to R-086 and R-090 are found, but R-087 to R-089 (same paragraph, "now limited to a stationary vehicle") are over-flagged.
- **Renumbering and page shift cost nothing**: R156 (13 renumbered), R149 (14 renumbered; 6 more renumbered and edited, reasons say "(formerly 3.3.4)"), R39 and R64 (every page shifts). Zero false flags in all four. A renumbered MODIFIED paragraph is flagged only when a requirement on it changes.
- **LLM over-flagging is modest and has one cause: exemptions.** The 5 false flags in the ten cases and 3 of the 5 on dev are a sentence that exempts or narrows a paragraph ("The provisions of this paragraph do not apply whilst an ADSF-2 is active", "now limited to a stationary vehicle"). That does change every requirement of the paragraph; the gold flags only some of them (R100 5.3.1, 5.3.2: the gold is inconsistent across eight identical insertions). The dev heading "Acceleration from standstill" added to 5.1.6 (R-025, R-026) was called a scope change; the experts did not flag it. Wording-only changes were handled correctly everywhere ('seconds' to 's', '70%' to '70 per cent', 'ignition' to 'vehicle master control' is not wording-only and is flagged).
- **Added granularity is the other disagreement.** Added precision is 0.69: R174 reports 4 added against 1 (each ADS sentence appended to a requirement-bearing paragraph is a new obligation to the agent), R51 9 against 7, dev 20 against 17 (3 from 5.1.5.1 split in three, which the experts counted once or not at all). Added items are scored on paragraph plus text similarity; matching by paragraph alone gives a few more (dev 14 of 17). A restructure that merges a list into one paragraph (R132 7.9) is reported as added at the new paragraph, as in the gold.
- **A sentence appended to a changed paragraph: "added" or "modified"?** Dev has no example (its modifications are inside one sentence). The agent makes it `added`; DeepSeek's gold makes it `modified` of the requirement. This accounts for R100 R-037, R-050, R64 R-009, R-011, R-030, R174 R-001 (R64 R-010 shares its paragraph with R-011; that is 7 of the 9 misses; the other two are wording-only edits, below). The lenient column (gold flag covered when an added item sits at the same paragraph) is 0.80 to 1.00; reporting both is the safe move until an upload tells which convention the platform uses.
- **Wording-only changes that the gold flags** (R39 R-002 'onboard' to 'on-board' and 'UN' inserted, R149 R-050 'Classes' to 'Class'): the agent says unchanged; arguably right, and the false flags are "the costly error" of `spec/proposal.md`. Footnote text that changes while the requirement does not (R174 5.1.1) is also not flagged; the gold flags it.
- **Tables and formulas (R51 Annex 7)**: modified found 4 of 4, the table node is one node whose grid is compared as text; no failure. A formula change inside a table cell is only as good as the grid extraction.
- **The agent is stochastic at the margin**: dev flagged 12, 8 and 6 requirements in three runs (recall 7/7, 6/7, 6/7), always the same core. The replay cache makes a given run reproducible; a second sample and a vote is the next step ($0.1 per dev run).

## 5. Caveats

- **DeepSeek golds are noisy.** One model wrote both the requirements and the changes, with its own convention for sentence-level changes, and flagged some wording-only edits. Never tune on them; the dev run is the only expert yardstick, and its 6/1/17 is one case. The score is an instrument for finding failure modes, not a leaderboard figure.
- The reasons are built from the paragraph diff; the dev gold's reasons have the same shape but the platform's judge for reasons is unknown.
- The old requirements of a hidden case may cite paragraphs of an older edition than `regulations/data/<reg>/base`; the label-then-BM25 mapping covers a moved label, not a different edition.
- Windows hide cross-window effects: an added paragraph outside the window is not counted, a requirement that the new version moves to another section is found only when the candidate search ranks it.
- Network note for DeepSeek: on this machine a request over about 15 KB is dropped when its packets arrive back to back (the server closes after 19 s); `eval/xprovider.py`'s small segments did not get 25 KB prompts through, so `eval/drift_cases.py` writes 900-byte pieces with 10 ms between them (`PacedConnection`). Calls to the Anthropic API are not affected.

## 6. How to run

```
# a case folder: spec/testing/cases-drift/<id> (pair.json), or subgoal/dev (the PDFs are the base and latest of the regulation the requirements cite)
python src/ai_agent/run_drift.py spec/testing/cases-drift/drift-r156-ota-renumber --out runs/drift/drift-r156-ota-renumber --max-cost 2
python src/ai_agent/run_drift.py subgoal/dev --out runs/drift/subgoal-dev --case-id subgoal-dev
# explicit files
python src/ai_agent/run_drift.py --old-pdf OLD.pdf --new-pdf NEW.pdf --requirements-old R.json --regulation "UN R175" --version-label 1.0.0 --out runs/drift/x

python tools/validate.py runs/drift/x/changes.json --kind subgoal --requirements-old R.json
python eval/score_drift.py runs/drift/x/changes.json EXPECTED.json --requirements-old R.json
python eval/score_drift.py --all                      # dev (runs/drift/subgoal-dev) + the ten cases (runs/drift/<id>)
python eval/drift_cases.py scan | build [--send] | check   # the cases
python eval/test_ai_agent.py                          # offline tests: alignment, reasons, scripted agent, scorer
```

`--no-new-in-modified` reports as added only the obligations of added paragraphs; `--no-cache` forces new samples. The run folder has `changes.json`, `trace.json` (alignment counts, mapping, every judge verdict with its note, candidate paragraphs, added nodes and drops), `usage.json`, `calls.jsonl`. `outputs/subgoal-dev/changes.json` is the dev result (valid, `--strict`).

## 7. Next steps

- ~~Settle the "sentence appended to a changed paragraph" convention.~~ Settled: `added` (see the end of section 8).
- Sample twice and keep a flag only when both runs agree (precision) or either does (recall); the cost is $0.1 per dev run.
- Re-pair low-similarity REMOVED/ADDED neighbours inside the same section before the judge, so a rewrite under one label is one `modified` with a proper diff reason.

## 8. Appended-sentence convention (2026-10-25)

**Method.** `run_drift(..., appended=)` and `run_drift.py --appended {added,modified,both}`. Post-processing over the unchanged judge verdicts, so every run replays from `runs/_llm_cache` (33 runs: $0.00 spent, $1.72 replayed, read from `usage.json`; the `added` runs are byte-identical to the earlier `runs/drift/*`). Detection (`drift.appended_sentences`, no model): a MODIFIED node whose word diff (edge punctuation ignored) has only insertions, each starting a sentence (paragraph start or after a word ending in '.') with a capital and ending in '.'. Any replace or delete, or a clause that is not a sentence, means "not appended". Modes on such a node:
- `added` (default): as before; the judge's verdicts and `new_obligations` decide.
- `modified`: every requirement on the paragraph the judge did not call removed is `modified`; its `new_text` gets the sentence (appended unless already there), the reason is the word diff (it quotes the sentence), and the judge's `new_obligations` for the node are dropped.
- `both`: as `modified`, and the sentence is reported once as `added` (the judge's own obligation, else the sentence itself).

Runs: `runs/drift-appended-<option>/<case>`; score: `python eval/score_drift.py --all --runs runs/drift-appended-<option>`. Offline tests: `eval/test_drift_appended.py` (7).

**Results** (flagged = modified + removed; the ten-case golds are DeepSeek's):

| Option | Set | Flagged R | Flagged P | False flags | Added R | Added P | Overall F2 | Lenient flagged R / added P |
|---|---|---|---|---|---|---|---|---|
| added | dev | 7/7 | 0.58 | 5/87 | 13/17 | 0.65 | 0.78 | 1.00 / 0.65 |
| modified | dev | 7/7 | 0.58 | 5/87 | 13/17 | 0.65 | 0.78 | 1.00 / 0.65 |
| both | dev | 7/7 | 0.58 | 5/87 | 13/17 | 0.65 | 0.78 | 1.00 / 0.65 |
| added | ten | 36/45 (0.80) | 0.88 | 5/556 | 25/29 (0.86) | 0.69 | 0.82 | see section 3 |
| modified | ten | 40/45 (0.89) | 0.64 | 23/556 | 19/29 (0.66) | 0.70 | 0.76 | |
| both | ten | 40/45 (0.89) | 0.64 | 23/556 | 25/29 (0.86) | 0.68 | 0.82 | |

- **Dev: no node is detected as appended, the three outputs are identical** (and equal to `outputs/subgoal-dev/changes.json`). Dev cannot settle the convention.
- Ten cases: 14 nodes with requirements get an appended sentence; 8 of them are exemptions or ADS conditions ("do not apply whilst an ADSF-2 is active", "Whilst an ADSF-2 is active, paragraph 5.1.4 shall apply"). `modified` and `both` add 22 flags: 4 are in the gold (R64 x2, R100 x2), 18 are not. False flags go from 5 to 23 (R100 4 to 11, R174 0 to 5, R39 0 to 3, R51 1 to 3, R149 0 to 1). Flagged recall rises 0.80 to 0.89, precision falls 0.88 to 0.64. `modified` loses 6 gold added items (the sentence is no longer an item); `both` keeps them and costs 1 extra added item.
- 5 gold flags stay missed in `modified` and `both` (45 - 40); they are not appended sentences (wording-only edits and kind mismatches, section 4).

**Recommendation.** Keep `added` as the default. On the ten cases `both` ties it on overall F2 (0.82) while trading recall for 18 more false flags, the error the proposal calls costly; `modified` is worse (0.76). The gain depends only on which convention the platform uses, which no data we hold shows. If the platform uses paragraph-level `modified`, `both` is the better setting (recall 0.89, added kept); if it uses sentence-level `added`, `both` costs about 18 false flags per 556 requirements.

**Candidate uploads** (all valid, `--strict`): `outputs/subgoal-dev/changes-appended-{added,modified,both}.json`, identical for dev. Uploading them tells nothing. The ten cases are our own and not uploadable, so the way to settle it is to ask the organisers:

> In a new version, a sentence is appended to an existing paragraph from which requirements were derived (for example "The provisions of this paragraph do not apply whilst an ADSF-2 is active."). In the expected changes, is this one `added` item for the new sentence, or is each requirement derived from that paragraph `modified` (new_text including the sentence), or both? And if it is `modified`, is it every requirement of the paragraph or only those the sentence concerns?

**Settled (2026-10-25).** The user answered the question above: a sentence appended to an existing paragraph is one `added` item for the new sentence. `--appended added` (the default) is the platform's convention; the seven "misses" of section 4 that come from this convention are gold artefacts of the DeepSeek cases, not agent errors. `modified` and `both` stay available but are not to be used for submissions.
