# Testing beyond the dev case: the parser over the whole corpus, and a lexical baseline on three new cases

Status: results, 2026-10-24. Companion to `spec/finding/finding.md` and `spec/precision.md`; it uses the funnel and the F2 vocabulary of the second.

## Summary

- **The parser now lives in `src/regcomp/parse.py`** and keeps the gate: 178 of 178 distinct expert anchors (`python eval/anchors.py`). The "215" in `finding.md` mixed units (R175's 94 requirements sit on 57 distinct paragraphs); that file is corrected.
- **The first run over all 92 PDFs showed that rules written from five regulations were too narrow.** 27 PDFs were flagged, and 22 parse differently now (9,945 → 16,714 nodes in them). The causes were a hard-coded heading size (the renderer scales pages), uppercase and lowercase-suffixed annex headings, other `Part` forms, top-level parts, and the GTR layout. All 92 now parse in 30 seconds in total, with 11 flagged for a look (4 of them only a long introduction).
- **Three regulations drawn at random (seed 20261024): UN R43, R128, R79.** Each has a `spec.md` in the dev format and a gold of 26 to 47 requirements (111 in all) that were written from the regulation text. Every citation was grounded by a verbatim quote, and an independent plain-text check confirmed all 111 pages.
- **The lexical baseline fails first at choosing the regulation.** The gold regulation ranks 1st for R43, 5th for R128 and **22nd of 56 for R79**. Across the four cases only 2 of 7 gold regulations are in its chosen set (median rank 8), so end to end three of four cases score zero.
- **With the right regulations handed over, it still reaches little:** paragraph precision 0.04-0.24 at 25 nodes, recall 0.14-0.55 at 100 nodes, best F2 0.10-0.49. Page-level scores from `tools/score_local.py` look better (R79: 0.41 / 0.73 at 25 nodes) only because a page is a coarse unit.
- **Three structural findings follow from the measurements.** Definitions sections outrank requirements in 5 of 7 regulation-case pairs, and leaving them out raises mean recall at 100 nodes from 0.36 to 0.49. The breadcrumb (ancestor titles) helps retrieval by 12-35% in recall. And `precision.md` rule 4.1 (drop heading-only nodes) loses 3 of R128's 22 gold paragraphs unless it keeps leaves.
- **Read the numbers as a floor, not as the pipeline's score.** The gold is synthetic and has one author, the system has no model in it, and n is 3 (plus the dev case).
- **Section 9 (later the same day): the anchor gate could not see the text.** Four defects reached the extractor with 178/178 still passing (fused exponents, tables flattened to one string, list dashes glued to words, wrapped references taken for paragraphs). They are fixed, `eval/fidelity.py` and 61 tests now guard them, and `eval/xprovider.py` is ready to put the pipeline's questions to a model from another provider (not run: no key).

## 1. What was done

| Step | Result |
|---|---|
| Parser moved | `src/regcomp/parse.py` (the parser), `src/regcomp/corpus.py` (where the PDFs are). Needs PyMuPDF; the scripts below also use `tools/score_local.py` |
| Rest of the regulations fetched | `python tools/fetch_regulations.py --role base --out regulations/data`, then `--role latest`: 92 PDFs, 213 MB, all checksums verified (`regulations/data` is in `.gitignore`) |
| Corpus parsed | `eval/health.py`; table in `parse-health.csv` |
| Test cases | `spec/testing/cases/<id>/{spec.md, authoring.json, expected.json}` for three regulations |
| Baseline and measurement | `eval/baseline.py`, `eval/run_cases.py`, `eval/diagnose.py`; every number is in `results.json` |

## 2. The parser over the corpus

### 2.1 Result

92 PDFs (56 base, 36 latest), 5,496 pages, 50,279 nodes. For the base versions alone: 3,029 pages, 27,682 nodes, about 1.9M tokens of text, 10.4 nodes per page at the median (range 4.5-16.5). Parsing takes 0.2 s per PDF at the median, 30 s in total. The footer `page N of M` matches the physical page on 92 of 92 PDFs. The anchor gate was 178/178 before and after every change.

### 2.2 What broke, and what changed

The first run flagged 27 PDFs. I looked at each failing document's own text before changing a rule. Four causes accounted for most of it:

| Cause | Example | Change in `parse.py` | Nodes before → after |
|---|---|---|---|
| Heading size is scaled with the page: annex headings are bold 8.7-13 pt, never a fixed 13 | R43 latest 11.6 pt, R51 8.7 pt, R49 10.6 pt, R149 11.5 pt | heading = bold and at least 1.15 times the dominant font size of the document | R43 latest 372 → 1,789; R51 175 → 687; R49 911 → 2,363; R149 466 → 716; R123 260 → 525 |
| Case: `ANNEX 3 - APPENDIX 1 …` | R32 | case-insensitive keywords | R32 64 → 180 |
| Annex id with a lowercase letter: `Annex 1a`, `Annex 2b` | R162, R163 | `[A-Za-z]` suffix | R162 165 → 237; R163 234 → 320 |
| `Part` written `Part A.` (R92), `Part 1 Essential…` with no separator (R49), or `Part I`/`Part II` outside any annex (R163) | R92, R49, R163 | wider separator set, roman ids, top-level parts | R92 151 → 207 |
| A GTR is `I. Statement of technical rationale` (300 paragraphs) then `II. Text of the Regulation`, where numbering restarts | GTR 9 | a heavy roman heading opens a scope; "Text of the Regulation" gets no prefix, so its labels read like any other body | GTR 9 378 → 604 |

R67, R83, R89 and R155 also changed slightly. In total 22 of 92 PDFs parse differently from the first run, and 70 do not.

### 2.3 What is left

11 PDFs are still flagged. `eval/health.py` documents the rules; two things changed after I saw the data:

- The first flag, "more than 5% of numbered lines left out", counted table cells as much as lost text (R51's table of symbols has a column of paragraph numbers). It was replaced by **`lost`**: left-out lines that carry a sentence after the number, more than 3% of the candidates. The old figure stays in the CSV as information.
- `front` (more than 3,000 characters before the first heading) turned out to measure the length of the Introduction, not a failure (R79 4.9K, R131 4.7K).

What `lost` finds is small: R13H 4.0%, R107 4.2%, GTR 9 4.2%, R171 3.2%, R38 3.4%. The lines I opened are mostly wrapped references that start a line (`4.4.1. above need not be repeated…`), dotted-leader form fields, and the numbered Introduction of R171. A few are real paragraphs (R13H `2.35`, R171 `5.3.7.2.5.3`). Regulations written in a declarative style, where few nodes contain shall/must, are R101 (24%), R92 (26%), R51 (34%), R114 (34%) and R164 (32%); R48 is 36%.

No anchors exist outside the five regulations, so "parses" here means "passes these health signals", not "is correct".

## 3. The test cases

### 3.1 The draw

`random.Random(20261024).sample(sorted(pool), 8)`, where the pool is the 51 regulations not yet explored (everything except R10, R48, R148, R150, R175). The only pre-declared rule was to skip a regulation the proposal lists as superseded (R3, R6, R7, R19, R23, R38, R104, R123), because the right citation would then be its successor. The draw order was R43, R128, R79, R103, R156, R6, R100, R131, so the first three were taken and nothing was skipped.

### 3.2 How the gold was made and checked

Each `spec.md` follows `cases/dev-rear-lamp/spec.md` (product type, vehicle category, function, main parts, materials) and uses plain engineering words, not the regulation's. A spec attribute decides a table row, as the red lens does in the dev case: R43's nominal thickness (4.96 mm) selects the 4.5-5.5 mm row of the 227 g ball test.

The gold follows what the dev gold does: one obligation per requirement, standalone "X shall Y", product obligations and the test criteria they are judged by, marking, and the conditions of a table row that applies. It leaves out application and approval procedure, authority duties, definitions, permissions, transitional provisions, and clauses for other variants (R128's substitute and white-light sources; R79's full-power steering, ACSF and trailers).

Each requirement carries a verbatim `quote` from the cited node. `eval/build_expected.py` refuses a requirement whose paragraph or quote is not in the parsed regulation, takes the page from the line where the quote starts, and writes `expected.json`. The files also pass `tools/validate.py`. As an independent check I confirmed with plain PyMuPDF text, without the parser, that the paragraph number sits at a line start on the cited page (or the page before, for a paragraph that continues): **111 of 111**.

| Case | Product | Gold | Paragraphs | Sections | Pages | Requirements per paragraph | Notes |
|---|---|---|---|---|---|---|---|
| `synth-r43-windscreen` | laminated windscreen, M1 | 47 | 35 | 9 | 5-97 | 1.34 | 32 of 47 in annexes (Annex 6 tests, and the Annex 3 paragraphs it points to) |
| `synth-r128-led-source` | replaceable red LED light source | 26 | 22 | 9 | 2-7 | 1.18 | all in the body; §3.10 applies because the spec declares a maximum operating temperature |
| `synth-r79-eps` | electric power-assisted steering, M1 | 38 | 25 | 6 | 9-51 | 1.52 | one table row (M1, Table 2), four Annex 6 items |
| dev rear lamp (expert gold, for reference) | | 190 | 121 | 48 | | 1.57 | |

### 3.3 What the synthetic gold cannot tell us

It was written by the same agent that wrote the parser and the baseline, from the same parsed text; there is no expert second opinion. Judgement calls could differ from Certivity's experts: R43's radiation test is left to the laboratory's discretion and is out; R43's gold goes down into Annex 3 because Annex 6 delegates its pass criteria there. Treat the precision figures as depending on how the gold was cut.

## 4. The baseline

It stands in for steps 2-4 of the proposal's A4 with BM25 where the real pipeline would use a model, and it makes no model call. All settings were fixed before any case was run.

1. **Regulations:** BM25 of the whole spec against one card per regulation (title plus its scope section); keep those scoring at least half of the best, three at most.
2. **Nodes:** BM25 of every node of a chosen regulation against each facet of the spec (product type, each function, each main part). The node is matched with its breadcrumb, the titles of its ancestors and of its annex or part.
3. **Emit:** the N = 25 best nodes, or every node of the K = 3 best sections (a depth-2 body section or an annex/part scope, as in `precision.md`). Heading-only nodes are never emitted.

`text` is the node's own text, so the baseline can be judged only on what it cites. Three further variants were added **after** seeing why the default fails; they are labelled post hoc wherever they appear: no breadcrumb ("flat"), nodes under a Definitions, Scope or Purpose heading left out ("no definitions"), and two other queries for choosing the regulation.

## 5. Results

Paragraph level counts a requirement as found when it cites a paragraph the gold cites. It is an upper bound for the requirement-level score, because the baseline emits one non-atomic requirement per node. F2 = 5PR / (4P + R).

### 5.1 The funnel

**Stage 1, regulations** (rank among all 56 regulations; chosen set; P and R at regulation level):

| Case | Gold regulations (rank) | Chosen | P / R |
|---|---|---|---|
| dev rear lamp | R148 (2), R150 (8), R48 (12), R10 (31) | R19, R148, R23 | 0.33 / 0.25 |
| R43 windscreen | R43 (1) | R43, GTR 9, R19 | 0.33 / 1.00 |
| R128 LED source | R128 (5) | R38, R19, R23 | 0.00 / 0.00 |
| R79 EPS | R79 (22) | R100, R10, R101 | 0.00 / 0.00 |

Pooled: 2 of the 7 gold regulations are chosen, 2 of 12 choices are right (precision 0.17), and the median gold rank is 8.

**Stage 2 and 3, sections and nodes, with the gold regulations handed over** (paragraph level, P / R / F2, nodes emitted in brackets):

| Case | Every node of the gold sections (no headings) | K = 3 sections | N = 25 nodes | N = 100 nodes |
|---|---|---|---|---|
| dev rear lamp | 0.26 / 1.00 / 0.63 (473) | 0.12 / 0.23 / 0.19 (242) | 0.11 / 0.09 / 0.09 (100) | 0.10 / 0.35 / 0.24 (400) |
| R43 windscreen | 0.11 / 1.00 / 0.38 (321) | 0.00 / 0.00 / 0.00 (5) | 0.04 / 0.03 / 0.03 (25) | 0.05 / 0.14 / 0.10 (100) |
| R128 LED source | 0.59 / 0.86 / 0.79 (32) | 0.71 / 0.46 / 0.49 (14) | 0.24 / 0.27 / 0.27 (25) | 0.13 / 0.55 / 0.34 (100) |
| R79 EPS | 0.15 / 1.00 / 0.47 (167) | 0.11 / 0.48 / 0.29 (107) | 0.16 / 0.16 / 0.16 (25) | 0.10 / 0.40 / 0.25 (100) |

(For the dev case the N columns emit N nodes in each of its four regulations.) The first column is the ceiling of "pick the right sections, then list everything": with expert gold it reproduces `precision.md` (568 nodes at 21%, then 473 against its 472 once headings go). Best F2 anywhere on the grid with the gold regulations given: dev 0.25, R43 0.10, R128 0.49, R79 0.29.

**End to end, with the regulations the baseline chooses** (same layout):

| Case | K = 3 sections | N = 25 nodes | N = 100 nodes | Best F2 on the grid |
|---|---|---|---|---|
| dev rear lamp | 0.30 / 0.17 / 0.19 (70) | 0.05 / 0.03 / 0.04 (75) | 0.04 / 0.11 / 0.08 (300) | 0.19 |
| R43 windscreen | 0.00 / 0.00 / 0.00 (68) | 0.01 / 0.03 / 0.02 (75) | 0.02 / 0.14 / 0.06 (300) | 0.07 |
| R128 LED source | 0.00 / 0.00 / 0.00 (50) | 0 (75) | 0 (300) | 0.00 |
| R79 EPS | 0.00 / 0.00 / 0.00 (67) | 0 (75) | 0 (300) | 0.00 |

**The same runs scored by `tools/score_local.py` at page level** (precision / recall, N = 25 nodes): with the gold regulations dev 0.34 / 0.36, R43 0.10 / 0.17, R128 0.20 / 0.60, R79 0.41 / 0.73; end to end dev 0.24 / 0.15, R43 0.04 / 0.17, R128 0 / 0, R79 0 / 0. A page is a coarse unit and "page or paragraph" credits a page whose paragraph is wrong, so these numbers flatter the baseline: R79 reads 0.41 / 0.73 at page level against 0.16 / 0.16 at paragraph level. Neither is the requirement-level score, which needs the judge.

### 5.2 Where the emitted nodes go wrong (end to end, N = 25)

| Case | Emitted | Wrong regulation | Wrong section | Uncited, in a gold section | Found |
|---|---|---|---|---|---|
| dev rear lamp | 75 | 50 | 8 | 13 | 4 |
| R43 | 75 | 50 | 19 | 5 | 1 |
| R128 | 75 | 75 | 0 | 0 | 0 |
| R79 | 75 | 75 | 0 | 0 | 0 |

Of the gold paragraphs: not reachable because the regulation was not chosen 81 of 121 (dev), 0 of 35 (R43), 22 of 22 (R128), 25 of 25 (R79).

### 5.3 What the structure buys, and what it does not

**The right regulation is where the signal is lost, and the spec text is a poor query for it.** Ranks of the gold regulations under three queries (post hoc):

| Query | dev R10 / R148 / R150 / R48 | R43 | R128 | R79 | Median over the 7 |
|---|---|---|---|---|---|
| whole spec (the default) | 31 / 2 / 8 / 12 | 1 | 5 | 22 | 8 |
| product type line only | 27 / 1 / 7 / 5 | 1 | 3 | 8 | 5 |
| product type + functions | 35 / 1 / 11 / 9 | 1 | 3 | 14 | 9 |

The materials and parts lines add noise: R79's spec says motor, electronic control unit and 12 V, which match R100 (electric power train), R10 (EMC) and R101 more than "steering". Even the best query puts R79 8th. This is a vocabulary problem in both directions, which a model reading a card can bridge and BM25 cannot.

**Definitions outrank requirements.** The first section the lexical ranker returns inside the gold regulation is a definitions section in 5 of 7 regulation-case pairs (R10 2.12; R150 2.3; R48 2.4, 2.8, 2.10; R43 2.2, 2.4, 2.14; R79 2.5): "windscreen" is defined there. None of the 121 expert-cited paragraphs is in a definitions section. Leaving out nodes under a Definitions, Scope or Purpose heading (post hoc), with the gold regulations given and N = 100:

| | default | no definitions |
|---|---|---|
| dev | R 0.35 / P 0.10 | R 0.37 / P 0.11 |
| R43 | R 0.14 / P 0.05 | R 0.23 / P 0.08 |
| R128 | R 0.55 / P 0.13 | R 0.59 / P 0.15 |
| R79 | R 0.40 / P 0.10 | R 0.64 / P 0.16 |
| mean of the three synthetic | R 0.36 / P 0.09 | R 0.49 / P 0.13 |

**The breadcrumb helps, modestly.** Matching a node together with its ancestors' titles instead of its own text, at N = 25 with the gold regulations given: dev R 0.09 vs 0.05, R43 0.03 vs 0.03, R128 0.27 vs 0.23, R79 0.16 vs 0.08. At N = 100: dev 0.35 vs 0.28, R128 0.55 vs 0.46, R79 0.40 vs 0.32, but R43 0.14 vs 0.20 in favour of flat. Mean recall over the three synthetic cases rises from 0.33 to 0.36 at N = 100 and from 0.11 to 0.15 at N = 25.

**Sections against nodes.** At a comparable output size, listing the best sections beats the best nodes on R128 (14 nodes: 0.71 / 0.46 against 25 nodes: 0.24 / 0.27) and slightly on R79 (107 nodes F2 0.29 against 100 nodes 0.25); it is mixed on the dev case and fails on R43, where definitions take the top sections and where the gold sits in annexes that count as one section each (Annex 3 alone is one section of 263 nodes).

**Precision after choosing the right sections is not the dev case's 26%.** It is 0.26 (dev), 0.11 (R43), 0.59 (R128) and 0.15 (R79). R128 is one small, single-purpose regulation; R43 and R79 are large with many variants (R43 has 26 annex scopes; R79 has ACSF, full-power steering and trailers). The applicability filter has very different amounts of work per regulation.

**Rule 4.1 of `precision.md` does not carry over as written.** "Heading only" (under 60 characters, no verb, no digit) drops three of R128's gold paragraphs: `2.3.1.1 the trade name or mark of the applicant;`, `2.3.1.2 the rated voltage;` and `2.3.1.3 the designation of the relevant category;`. They are list items under the stem "shall bear on the cap:", which is why the oracle-sections recall is 0.86, not 1.0. In the four cases, 0 of the cited nodes are headings that have sub-paragraphs, and 3 are leaves. Dropping only the heading-only nodes **that have sub-paragraphs** restores the recall (R128 0.86 → 1.00, F2 0.79 → 0.89) and costs about one point of precision (dev 0.256 → 0.245; R43 0.109 → 0.105; R79 0.150 → 0.149). The rule is safe only if a lead-in stem's children stay citable, which 4.2 asks for.

## 6. What this means for the pipeline

1. **Choosing the regulation is the first thing to spend a model on**, and the card should lead with what the regulation approves, not its scope text. Use the product-type line more than the materials and parts lines, supersession and `CITES_REG`, and a model that can bridge "motor, ECU, 12 V" to "steering equipment". Everything downstream is zero when this fails (3 of 4 cases here).
2. **Definitions and scope are structure, not candidates.** Keep them out of the candidate sections and use them for `DEFINES` edges. On 121 expert-cited paragraphs this costs nothing, and it raised mean recall at N = 100 from 0.36 to 0.49.
3. **Amend rule 4.1:** a heading-only node is dropped only if it has sub-paragraphs.
4. **Keep the breadcrumb in the retrieval text of every node**, and select sections with a model, not with BM25: annex-sized sections need a finer unit, and R43's Annex 3 shows why.
5. **Do not read page-level or paragraph-level numbers as the requirement score.** The judge (`precision.md` M1) comes before any claim about a number; paragraph level is an upper bound and page level a generous one.
6. **Expect the filter's load to vary by a factor of five between regulations** (precision after the right sections 0.11 to 0.59), so calibrate the F2/5 bar per regulation shape before trusting the dev case's 26%.

## 7. Not measured, and risks

- **Nothing model-based:** obligation extraction, applicability filtering, the judge, requirement-level precision and recall, granularity per node. The baseline is a floor, not a forecast.
- **Synthetic gold, one author, three regulations.** No confidence interval is meaningful at n = 3. The held-out case uses other regulations.
- **The post hoc variants** (flat, no definitions, other queries, the heading rule) were chosen after seeing the failures, on the same cases. They show where the loss is; they are not tuned settings.
- **Parser health is not parser accuracy** on the 51 regulations without anchors. I opened the left-out lines of the worst PDFs, not every page. Tables were not exercised here, and the corpus has 243 captioned tables in the base versions (30 of 56 regulations have none).
- **Two decisions of mine in `eval/health.py`** (the `lost` flag replacing `left-out`, and `front` measuring the introduction) were made after the first run, and are disclosed there.

## 8. Reproduce

```
python tools/fetch_regulations.py --role base --out regulations/data     # and --role latest
python eval/anchors.py                         # the gate: 178/178
python eval/health.py --csv spec/testing/parse-health.csv
python eval/build_expected.py spec/testing/cases/<case>/authoring.json
python eval/run_cases.py cases/dev-rear-lamp spec/testing/cases/* --json spec/testing/results.json
python eval/diagnose.py cases/dev-rear-lamp spec/testing/cases/*
```

PyMuPDF is needed (`pip install pymupdf`; on a Windows path that is long, `pip install --no-deps pymupdf`). `tools/validate.py` needs `jsonschema`. Parses are cached in `regulations/data/_cache`.

Files in this folder: `report.md`, `parse-health.csv` (one row per PDF; regenerated in section 9, so its numbers are those of the parser after that round, not of sections 2 and 3), `results.json` (every number of sections 1-7, from the parser as it was then), `cases/` (spec, authoring file with quotes, and expected.json for each case).

## 9. Parser fidelity round: what the anchor gate could not see

Status: results, 2026-10-24, later the same day. Companion to `spec/finding/finding.md`; the changes are in `src/regcomp/parse.py`. PyMuPDF 2.0, Python 3.12, the 92 fetched PDFs.

### 9.1 The question

`eval/anchors.py` says that every expert label sits on the right page (178 of 178, unchanged by this round). It never reads a node's text, and the text is what a model rewrites into requirements. So the question here is not "are more anchors right" but "does the extractor read what the regulation says". Every number below was measured on the 56 base PDFs unless it says otherwise.

### 9.2 Four defects the gate passed

| Defect | Size | What the extractor would have read | Fix |
|---|---|---|---|
| A superscript fused into its base | 1,071 spans in the base PDFs (R149 748, R150 116, R148 91, R107 28, R49 15, R43 14, R123 14, R51 13) | `3.00∙102` for 3.00·10², `lx-1` for lx⁻¹; three dev gold requirements (G-0029, G-0218, G-0222) had numbers that were in no node | a superscript span is written with raised digits (`10²`), as the gold writes it; the space around a mark is kept |
| A table as one string in reading order | 243 captioned tables, plus tables with no caption line (R48 2.11: the colour boundaries; R10 6.9.1: the test pulses) | `... 20' 1.20∙103 8.00∙102 ... ------1°30' ...`: no way to tell which value is under which column | `Node.grid`: the cells cut out again from the ruling lines and written as a markdown grid (9.3) |
| A list dash glued to the next word | 1,461 of the 2,235 line-end hyphens of the base regulations are a `-` on a line of its own (R3 Annex 12) or follow a space | `-Heat: 48 h at 65°` | a hyphen joins only when it follows a word character (`Table A6-` / `1:`) |
| A wrapped reference taken for a paragraph | 244 numbered lines continue a reference (`... as set out in paragraph` / `6.4. of this Regulation, no value ...`); 13 of them had been made nodes (R19, R48, R49 x3, R53, R67, R83, R92, R123, R132, R148, R171) | a node that cuts the real paragraph in two, and a real paragraph pushed out of the chain (R19 Annex 2 2.3, R83 Annex 11 1.3, R92 Annex 3 5, R171 Annex 6 7 are nodes again) | a numbered line after a line that ends in `paragraph(s)` is not a start |

One more rule came out of the same look: a one-level heading without its dot and without a style (R10 Annex 5 `4 Test requirements`) was rejected as a figure legend. It is kept when its own first sub-paragraph (`4.1.`) follows it, which a legend never has. Net effect on the base nodes: 27,682 to 27,674 (13 out, 5 back in). The numbered lines that look like a lost paragraph (`lost` in `eval/health.py`) fall from 454 to 315 in the base PDFs, because most of them were wrapped references.

What is left and is not a parser error (`eval/health.py` `orphans`, a paragraph whose parent number is missing): numbers in form and table cells (`1.1.` alone on a line), headings the source leaves unnumbered (R131 "Scenario 1" over 1.1. and 1.2.), item numbers of a communication form (R156 `11.13.`), a typo of the source (R13H `5.2.1.24.16.`), one heading glued to the end of the previous sentence (R67 17.10), and seven `9.00∙102` that R149 types as plain digits in its own text layer. A rule for any of them would be written for one PDF.

### 9.3 Table grids

- **Where a grid goes.** To the node that holds the text inside the table, not to the node named by a caption: R10 6.9.1 has no caption line, and its two tables (3a and 3b) hold the seven test pulses of the dev gold. Over the 92 PDFs 1,583 nodes carry a grid (836 in the base versions); 418 of the 426 captioned tables are among them (237 of 243 in the base versions). No ruled table lies on no node, and `find_tables()` raised on no page.
- **A table cut by a page break is one grid** when the next piece starts near the head of the next page, has the same number of columns and the same vertical rulings (within 3 points); a header the next page repeats is dropped. R150 Table 3 is the header of page 12 on top of the 18 rows of page 13; R48 2.11.2.3 holds two tables that follow each other on pages 14 and 15 but share only their column count, and stays two grids.
- **Cell text comes from the spans, not from `Table.extract()`:** spans left to right inside a cell, a sign printed as its own span in front, exponents raised, a key cell that spans rows repeated on each row, a header that spans columns written once. R150 Table 3 reads `| IA, IB | Red | Angle of divergence α | 20' | 3.00∙10² | 2.00∙10² | 1.00∙10² | -- | -- | -- |` (G-0029); R10 6.9.1 reads `| 1 | -75 V | -450 V | 500 pulses | III | III |`; Table A6-1 is one grid over its two thermometers.
- **`find_tables()` of PyMuPDF 2 asks a neural layout model whenever `onnxruntime` is importable, and the parser switches that off (`use_layout=False`).** Without the switch a grid depends on the machine, a ruled page costs 4 to 5 times more (R150 10.3 s against 2.4 s for its 23 ruled pages; R10 26.7 s against 4.8 s), and real tables go missing: on the 132 ruled pages of R150, R10, R48 and R148 the two lists of tables differ on 36 pages; the model returned nothing for the coordinates A1 to A4 at the head of R48 page 15, which are binding colour limits. The parser passes the switch only if the installed PyMuPDF has it (not tried on other versions). `Page.find_tables` is a `(self, **kwargs)` wrapper, so the switch is looked up on `pymupdf.table.find_tables`; looked up on the wrapper it is silently off.
- **Only pages that draw rulings are tried.** 923 of the 3,029 base pages do; on none of the other 2,106 does `find_tables()` find a table (checked on every one). All 92 PDFs now parse with grids in 240 s (30 s without; `parse_pdf(path, grids=False)` for the label and page checks).
- **Not gridded (6 of the 243 captioned tables of the base versions; 8 of 426 over the 92 PDFs, the other two being the latest versions of R100 and R148):** two drawn as images (R100 Annex 3 Table 1, R148 Table A2-4); R171 Table 1, which has only horizontal rules; R123 Tables 4 and 6, on a page with five tables whose cell text splits the table nodes; R155 Table A1, where a cell that reads `4.3.1 Threats` starts a node of its own and takes the grid. Their text is still in the node, flattened.

### 9.4 The checks that now guard this

| Check | What it says now |
|---|---|
| `python eval/anchors.py` | 178/178 (its sources are globbed: the held-out `subgoal/*/requirements_old.json` joins the gate on Sunday without an edit) |
| `python eval/fidelity.py` | 281 of 284 expert requirements have every number in the text of their node, its parents, children and grids; 3 are allowed with a reason, one number each (G-0218 and G-0222 add `(60 cd)` and `(25 cd)` themselves; G-0232 names a sibling paragraph); the previous parser failed 3 of them. Content words: 260 of 284 have 80% of theirs in the node's own text, 274 in its family; the ten below are paraphrases (R175 R-028 "While ... occurring" for "During ..."), checked word by word and three by eye |
| `python eval/test_parse.py` | 39 tests: the chain, wrapped references, unstyled headings, the scope regexes, `page_of`, superscripts, the grid builder on synthetic cells, and on the PDFs R150 Table 3 and A6-1, R10 6.9.1, the R48 colour tables, the exponents of R150 and R148, R10 Annex 5, R19 |
| `python eval/test_xprovider.py` | 22 tests: both request formats, both reply formats, what a dry run does not send, a missing key, the context guard, `.env` loading, reading and scoring picks, grounding verdicts |
| `python eval/health.py --baseline spec/testing/parse-health.csv` | 14 of 92 flagged (11 before, with another set of flags): `lost` R13H, R107, R171, GTR 9; `orphans` R40, R51, R131, R155, R156 (latest); `front` R79, R131. R38 is no longer `lost`. New columns: `orphans`, `wrapped`, `grids`, `table_grids`, `loose_grids`, `grid_errors`; `--no-grids` skips the grids |

The tests were run against the parser with the fix they guard switched off, one fix at a time: superscripts, wrapped references, unstyled headings, the hyphen rule, the page-break merge, a merge on column count alone, and the neural layout gate each make at least two tests fail. Two tests passed with their fix off at first and were tightened: the R150 corpus test accepted separate tables (it now requires the header directly above the page 13 rows), and the R48 test found the A1 row in a second node that happens to hold it (it now pins node 2.11.2.3 and its two tables). The ruling prefilter is the exception: it only saves time, and the experiment of 9.3 guards it, not a test.

The three synthetic `expected.json` files rebuild byte for byte with the new parser (every quote still grounds, no page or paragraph moved). The lexical baseline of section 5 re-run on it, case by case: the regulation ranks, the chosen regulations and the oracle sections are the same, the best F2 of every case is the same, and 98 numbers of `results.json` move by a node or a hit (dev 56, R79 36, R43 6, R128 0): the dev 25-node runs find one paragraph fewer (11 to 10 with the gold regulations, 4 to 3 with the chosen), and two section runs list one node fewer (dev 242 to 241, R79 chosen 67 to 66). `results.json` and section 5 keep the earlier parse.

### 9.5 A second provider

`eval/xprovider.py` puts the pipeline's questions to a model from OpenAI or Gemini and scores the answers:

- `select CASE`: the model reads the case's spec and a catalogue of the 56 regulations (title, scope, replaced regulations, 3,896 section ids with their headings; about 100,000 tokens) and picks regulations and sections. The score is regulation, section and paragraph level against `CASE/expected.json`, which is read only after the answer is saved. `--variant plain` leaves the proposal's rules (strict on regulations, inclusive on sections) out of the prompt, to see what they contribute. No prompt, not even the example of an answer's format, names a regulation, section, label or word that the dev gold needed (a first draft did: `UN R48` and `6.10` as the example); a test keeps it so, and was checked to fail when such an example comes back.
- `author --id ID --brief TEXT`: the model invents a product, names the regulations, then reads their raw page text and writes requirements with page, paragraph and a verbatim quote. `ground` checks each quote against the raw page text and against our nodes: `hallucinated` (on no page), `other node` or `spans nodes` or `no node` (on the page but not in the node the model names: a defect of our parser or of its label, to open in the PDF), `wrong page`, `ok`. This is the only check of the parser on the 51 regulations without expert anchors that does not come from our own reading.
- `agree CASE`: the model writes its own gold for an existing case, the regulations given, and the two golds are compared at regulation, page and paragraph level.

Checked offline: the request bodies and reply shapes of both providers as documented, a `replay` provider that answers from files (select, author and agree ran end to end on it), the grounding verdicts on a clean and a corrupted real gold, and the scoring against `run_cases.Case`. **Not run:** there is no OpenAI or Gemini key in the environment or in `.env`, and `--send` puts a case's `spec.md` in a third party's hands (`LICENSE-DATA.md` limits `cases/` to the hackathon). The two HTTP endpoints are therefore untried. A model's gold is a second writer's opinion: use it for regulation and section choice, for parser triage and for the agreement figure, not as the requirement-level truth.

### 9.6 Reproduce

```
python eval/anchors.py && python eval/fidelity.py                      # the two gates
python eval/test_parse.py && python eval/test_xprovider.py             # add --unit to skip the PDFs
python eval/health.py --baseline spec/testing/parse-health.csv --csv spec/testing/parse-health.csv
python eval/xprovider.py catalogue                                     # offline: what select sends
python eval/xprovider.py select cases/dev-rear-lamp --provider openai --model <id>            # dry run
python eval/xprovider.py select cases/dev-rear-lamp --provider openai --model <id> --send     # calls the model
python eval/xprovider.py ground provider.json                          # offline triage of a model's requirements
```
