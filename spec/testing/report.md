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
- **Section 9 (later the same day): the anchor gate could not see the text.** Four defects reached the extractor with 178/178 still passing (fused exponents, tables flattened to one string, list dashes glued to words, wrapped references taken for paragraphs). They are fixed, `eval/fidelity.py` and 61 tests now guard them, and `eval/xprovider.py` is ready to put the pipeline's questions to a model from another provider (first live run, with DeepSeek: section 10).
- **Section 11 (that night): twenty more DeepSeek cases and the fixes they pushed.** 24 cases now cover 32 regulations, 28 without expert anchors. Generated before any change, they showed that DeepSeek's requirements ground in a node with the label it gave 84.3% of the time and 96.2% after the fixes: 76 of the 174 recovered through the parser (the R101 Annex 7 Appendix 3 scope, top-level `Part` dividers in R67, R89 and R163, a paragraph number with no space after the dot) and 98 through a tolerance for the `Table` clause a model writes into a label. The anchor gate is 193/193 (the sub-goal's new-version side joined it), `Node` carries its tree and hash, and each new rule has a test that fails with the rule off. Not fixed, with the evidence: R13H Annex 4's plain `A.`/`B.` headings and bare `Appendix N` inside an annex.

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
| `python eval/test_xprovider.py` | 29 tests (22 when written, 7 added in section 10): the request formats, the reply formats, what a dry run does not send, a missing key, the context guard, `.env` loading, reading and scoring picks, grounding verdicts, and for `--provider llm` the request, thinking off, a cut-off reply, the timeout |
| `python eval/health.py --baseline spec/testing/parse-health.csv` | 14 of 92 flagged (11 before, with another set of flags): `lost` R13H, R107, R171, GTR 9; `orphans` R40, R51, R131, R155, R156 (latest); `front` R79, R131. R38 is no longer `lost`. New columns: `orphans`, `wrapped`, `grids`, `table_grids`, `loose_grids`, `grid_errors`; `--no-grids` skips the grids |

The tests were run against the parser with the fix they guard switched off, one fix at a time: superscripts, wrapped references, unstyled headings, the hyphen rule, the page-break merge, a merge on column count alone, and the neural layout gate each make at least two tests fail. Two tests passed with their fix off at first and were tightened: the R150 corpus test accepted separate tables (it now requires the header directly above the page 13 rows), and the R48 test found the A1 row in a second node that happens to hold it (it now pins node 2.11.2.3 and its two tables). The ruling prefilter is the exception: it only saves time, and the experiment of 9.3 guards it, not a test.

The three synthetic `expected.json` files rebuild byte for byte with the new parser (every quote still grounds, no page or paragraph moved). The lexical baseline of section 5 re-run on it, case by case: the regulation ranks, the chosen regulations and the oracle sections are the same, the best F2 of every case is the same, and 98 numbers of `results.json` move by a node or a hit (dev 56, R79 36, R43 6, R128 0): the dev 25-node runs find one paragraph fewer (11 to 10 with the gold regulations, 4 to 3 with the chosen), and two section runs list one node fewer (dev 242 to 241, R79 chosen 67 to 66). `results.json` and section 5 keep the earlier parse.

### 9.5 A second provider

`eval/xprovider.py` puts the pipeline's questions to a model from OpenAI or Gemini and scores the answers:

- `select CASE`: the model reads the case's spec and a catalogue of the 56 regulations (title, scope, replaced regulations, 3,896 section ids with their headings; about 100,000 tokens) and picks regulations and sections. The score is regulation, section and paragraph level against `CASE/expected.json`, which is read only after the answer is saved. `--variant plain` leaves the proposal's rules (strict on regulations, inclusive on sections) out of the prompt, to see what they contribute. No prompt, not even the example of an answer's format, names a regulation, section, label or word that the dev gold needed (a first draft did: `UN R48` and `6.10` as the example); a test keeps it so, and was checked to fail when such an example comes back.
- `author --id ID --brief TEXT`: the model invents a product, names the regulations, then reads their raw page text and writes requirements with page, paragraph and a verbatim quote. `ground` checks each quote against the raw page text and against our nodes: `hallucinated` (on no page), `other node` or `spans nodes` or `no node` (on the page but not in the node the model names: a defect of our parser or of its label, to open in the PDF), `wrong page`, `ok`. This is the only check of the parser on the 51 regulations without expert anchors that does not come from our own reading.
- `agree CASE`: the model writes its own gold for an existing case, the regulations given, and the two golds are compared at regulation, page and paragraph level.

Checked offline: the request bodies and reply shapes of both providers as documented, a `replay` provider that answers from files (select, author and agree ran end to end on it), the grounding verdicts on a clean and a corrupted real gold, and the scoring against `run_cases.Case`. **Not run:** there is no OpenAI or Gemini key in the environment or in `.env`, and `--send` puts a case's `spec.md` in a third party's hands (`LICENSE-DATA.md` limits `cases/` to the hackathon). The two HTTP endpoints are therefore untried. (The `llm` provider, an OpenAI-compatible endpoint, was run live against DeepSeek: section 10. `author` sends no file of `cases/`.) A model's gold is a second writer's opinion: use it for regulation and section choice, for parser triage and for the agreement figure, not as the requirement-level truth.

### 9.6 Reproduce

```
python eval/anchors.py && python eval/fidelity.py                      # the two gates
python eval/test_parse.py && python eval/test_xprovider.py             # add --unit to skip the PDFs
python eval/health.py --baseline spec/testing/parse-health.csv --csv spec/testing/parse-health.csv
python eval/xprovider.py catalogue                                     # offline: what select sends
python eval/xprovider.py select cases/dev-rear-lamp --provider openai --model <id>            # dry run
python eval/xprovider.py select cases/dev-rear-lamp --provider openai --model <id> --send     # calls the model
python eval/xprovider.py ground provider.json                          # offline triage of a model's requirements
python eval/xprovider.py author --id ds-x --brief "..." --provider llm --timeout 900 --send   # section 10; LLM_* lines in .env
```

## 10. First live run: DeepSeek writes four cases

Status: results, 2026-10-24, later the same day. Companion to 9.5. `author` was run with `deepseek-flash` for four one-line briefs; the cases are in `spec/testing/cases/ds-*`.

### 10.1 Setup

- **`--provider llm`** is any OpenAI-compatible endpoint set by four `.env` lines: `LLM_API_KEY`, `LLM_BASE_URL` (here `https://api.deepseek.com`), `LLM_MODEL` (here `deepseek-flash`, which the API lists as DeepSeek-V4.1-Flash, 1M-token context) and `LLM_TIMEOUT_S`.
- **Thinking is off.** DeepSeek's default is on: a one-line test came back with 18 of its 24 output tokens as reasoning. `thinking: {"type": "disabled"}` returned none (same test, checked live), and the provider sends it unless `--thinking` is given.
- **`LLM_TIMEOUT_S=15` is enough for the first call and not for the second.** The spec call (about 940 tokens) answers within 15 s. The requirements call carries the page text of the chosen regulations (74K-107K tokens) and stayed silent for longer, so the first attempt ended after four timed-out tries. The runs use `--timeout 900` on the command line; `.env` is unchanged. The front-bumper case took 50 s from brief to `expected.json` (the other three were not timed).
- **Two defects of `post` and `reply_text` came out of this and are fixed.** A read that stalls raises `TimeoutError`, which is not a `URLError`, so it ended in a traceback; and a reply cut off at the output limit (`finish_reason: length`) or with empty content went on to the JSON reader as if it were whole. Both are now errors with a message.
- **What was sent:** the brief, the specification template, the 56 regulation ids and titles from `regulations/index.json`, and the page text of the UNECE PDFs the model chose. No `spec.md`, `expected.json` or other file of `cases/` or `subgoal/` went out, and `select` and `agree` (which send a case's `spec.md`) were not run. The key's value is in no text, JSON, Markdown, Python or CSV file under `spec/`, `eval/` or `regulations/data/_xprovider/` (the saved prompts and replies); it is in `.env`, which git ignores.

### 10.2 The four cases

| Case | Brief | Regulations DeepSeek chose | Written | Kept (grounded) | Paragraphs | Per paragraph |
|---|---|---|---|---|---|---|
| `ds-front-bumper` | front bumper assembly with four ultrasonic parking sensors and two front fog lamps, M1 | R19 (71), R26 (14), R10 (6) | 116 | 91 | 78 | 1.17 |
| `ds-speedometer` | electronic instrument cluster with speedometer and odometer, M1 | R39 (28), R10 (11) | 43 | 39 | 27 | 1.44 |
| `ds-belt-reminder` | seat-belt reminder with a warning lamp and an acoustic signal for the front seats, M1 | R174 (33), R10 (8) | 46 | 41 | 36 | 1.14 |
| `ds-spare-wheel` | temporary-use spare wheel and tyre unit, M1 | R64 (26) | 26 | 26 | 20 | 1.30 |

Each case folder has `spec.md`, `provider.json` (what the model wrote), `ground.json` (the verdict per requirement), `authoring.json` and `expected.json`. All four `expected.json` pass `tools/validate.py`, and `eval/run_cases.py` loads them. `results.json` was not regenerated, so the baseline numbers of section 5 do not include them.

### 10.3 What grounding says

- **197 of 231 requirements are kept (85%).** The kept ones have a quote that sits on the page the model gave, in a parsed node with the label the model gave.
- **4 are hallucinated** (all in `ds-belt-reminder`: R174 5.1.1 and 5.2.3.2, R10 6.7 Table 1 and 6.9 Table 3b): the quote is on no page of the regulation. They are left out, which is what the check is for.
- **30 more are not ok, and most are the model's label.** In `ds-front-bumper` 18 of the 25 carry a label such as `6.3.5. Table (Class B)` or `6.4.3. Table (Class F3)` where our node is the bare paragraph; I opened R19 page 9 and 6.3.5 has no caption there, so the suffix is the model's. 5 more put R10's Tables 3a/3b under `6.9.2`, and on page 12 of the PDF they sit under `6.9.1`. The other pages were not opened. A tolerance rule (match on the paragraph when a `Table` suffix is added to a paragraph that has a grid and no caption) would recover most of them; it is not built.
- **The gold's regulations are DeepSeek's choice and differ from the proposal's expectation for a bumper.** For `ds-front-bumper` it chose R19, which the introduction of R149 lists as replaced by it (`spec/finding/mapping-simulation.md` section 6), and R26 and R10; it did not choose R42, R127 or R148. Read the case as a second writer's opinion (9.5), not as what an expert would approve.
- **Not measured:** how good the requirements are as requirements (no expert and no local judge). What `select` and `agree` measure on these cases is in 10.4.

### 10.4 `select` and `agree` on the four cases

Same setup as 10.1 (thinking off, `--timeout 900`; no temperature or seed is set). `select` sent the case's `spec.md` and the catalogue (about 99,600 tokens); `agree` sent the same spec and the same regulation texts as `author`'s requirements call, with the regulations in another order (`author`: as the model named them; `agree`: sorted, so R10 comes first), except in `ds-spare-wheel`, which has one regulation and whose prompt is byte for byte the same. Both sent only the model-invented `spec.md` of a `ds-*` case, no file of `cases/dev-rear-lamp`. Picks, prompts and replies are in `regulations/data/_xprovider/` (ignored by git).

**The gold here is DeepSeek's own.** "Gold regulations" below are the ones DeepSeek chose when it wrote the case, so a regulation it picks now and did not pick then counts as wrong even when it is a fair choice. The same model reads the same spec on both sides, so the numbers say how stable one model is, and little about how well another would do.

**`select`** (variant `strategy`: the proposal's rules in the prompt; regulation, section and paragraph level as in 9.5):

| Case | Chosen | Gold | Regulations P / R / F2 | Sections picked / gold / hit, P / R | Paragraphs: nodes, found of gold, P / R / F2 | Requirements reachable |
|---|---|---|---|---|---|---|
| `ds-front-bumper` | R19, R26, R42, R48, R149 | R10, R19, R26 | 0.40 / 0.67 / 0.59 | 45 / 40 / 11, 0.24 / 0.28 | 461, 32 of 78, 0.07 / 0.41 / 0.21 | 38 of 91 |
| `ds-speedometer` | R10, R39, R155 | R10, R39 | 0.67 / 1.00 / 0.91 | 28 / 18 / 12, 0.43 / 0.67 | 193, 20 of 27, 0.10 / 0.74 / 0.33 | 30 of 39 |
| `ds-belt-reminder` | R174 | R10, R174 | 1.00 / 0.50 / 0.56 | 6 / 11 / 5, 0.83 / 0.46 | 51, 28 of 36, 0.55 / 0.78 / 0.72 | 33 of 41 |
| `ds-spare-wheel` | R64 | R64 | 1.00 / 1.00 / 1.00 | 4 / 3 / 3, 0.75 / 1.00 | 40, 20 of 20, 0.50 / 1.00 / 0.83 | 26 of 26 |

- **Front bumper:** R42 and R48 are the regulations `spec/proposal.md` (Build order, step 6) expects for a bumper; `author` had not chosen them, so they count as errors here. `select` chose both R19 and R149 although its rules say to choose the regulation that replaces the other, and its own reason for R149 reads "replaces UN R19". The F2 falls from 0.59 at regulations to 0.27 at sections and 0.21 at paragraphs.
- **R10 is the unstable one.** It was in the gold of three cases (written by `author`) and `select` chose it in one of them (`ds-speedometer`), with the reason "electronic sub-assembly with microcontroller, CAN transceiver and display". For the belt reminder, whose spec lists a control unit and a PCB, it did not. It chose R155 (cyber security) for the speedometer, which the gold does not have.
- **Paragraph precision tracks the number of regulations:** 0.50-0.55 for one regulation and 0.07-0.10 for three or five (the regulations also differ in size, so this is not a controlled comparison).

**`agree`** (DeepSeek writes the requirements again from the same prompt; the two golds are compared on paragraphs; `P` is the share of the new paragraphs that the first gold cites, `R` the share of the first gold's paragraphs that the new one cites):

| Case | First run wrote (kept) | Second run wrote (grounded) | Paragraphs | P / R / F2 | Page-level P / R | Hallucinated |
|---|---|---|---|---|---|---|
| `ds-front-bumper` | 116 (91) | 28 (26) | 25 against 78 | 0.80 / 0.26 / 0.30 | 1.00 / 0.37 | 0 |
| `ds-speedometer` | 43 (39) | 33 (28) | 22 against 27 | 0.91 / 0.74 / 0.77 | 0.91 / 0.91 | 1 |
| `ds-belt-reminder` | 46 (41) | 54 (47) | 42 against 36 | 0.74 / 0.86 / 0.83 | 0.92 / 1.00 | 2 |
| `ds-spare-wheel` | 26 (26) | 18 (18) | 14 against 20 | 0.93 / 0.65 / 0.69 | 1.00 / 1.00 | 0 |

- **The same model writes noticeably different golds.** `ds-spare-wheel` is a pure re-run (identical prompt): 26 requirements became 18, and 0.65 of the first run's paragraphs are in the second. In the other three the order of the regulations also changed, so run-to-run variation and order are mixed and I cannot separate them: the front bumper went from 116 requirements to 28 (paragraph recall 0.26), the speedometer from 43 to 33 (0.74) and the belt reminder from 46 to 54 (0.86). A gold written by one model run is one draw; a score against it should carry that spread, and the platform's judge will have another.
- **The regulation level is 1.00 by construction:** the regulations are in the prompt and requirements the model writes for another regulation are discarded.
- **Hallucination is about 2% of the requirements written** (4 of 231 in the first runs, 3 of 133 in the second), always caught by grounding.
- **What this does not show:** how a second provider or an expert would write the same gold. For that, run the same three commands with another model in `.env`; `author`, `select` and `agree` need no change.

## 11. Twenty more DeepSeek cases, and the parser fixes they pushed

Status: results, 2026-10-24, later the same day. Companion to section 10 and to `spec/finding/parser-weak-points.md` (section 6 there says what was built). PyMuPDF 2.0, Python 3.12, DeepSeek `deepseek-flash` with thinking off.

### 11.1 Setup

- **Twenty briefs, one `author` call each** (`--provider llm --timeout 900 --send`, five at a time). A brief names a product and a vehicle category and no regulation: a plug-in hybrid with a traction battery, a high-voltage battery pack, frontal-impact structure and restraints, a brake system, two AEBS (light and heavy vehicle), ALKS, DCAS, a telematics unit, a software update manager, an immobilizer, a vehicle alarm, a speed limiter, a rear-impact structure, a replacement airbag, a motorcycle's lighting, an H7 bulb, conspicuity tape, a close-coupling device and an adaptive headlamp. DeepSeek chose the regulations (three at most, from the 56 titles), wrote the requirements and quoted each one.
- **What was sent:** the brief, the specification template, the 56 ids and titles, and the page text of the UNECE PDFs the model chose; about 2.1 million tokens for the 20 cases (4 characters a token; 11K to 182K a case). No file of `cases/` or `subgoal/`, no `spec.md` of ours. The key is in no file of the repository.
- **The cases were generated with the parser as committed, before any change of this round**, so they are a test set the fixes were not fitted to. The four cases of section 10 are graded with them: 24 cases, 1,461 requirements, 32 regulations (R10, R13H, R19, R26, R32, R37, R39, R48, R53, R64, R79, R83, R89, R94, R100, R101, R102, R104, R114, R131, R137, R148, R149, R150, R152, R155, R156, R157, R161, R162, R163, R174); 28 of them have no expert anchor. No case reached R3, R6, R7, R23, R38, R40, R42, R43, R49, R51, R62, R67, R92, R103, R107, R116, R123, R127, R128, R132, R164, R171, R175 and GTR 9. R171, R49, R107 and R43 are the large ones among them, and a next round should brief for them.
- **`python eval/xprovider.py regrade`** is new. It grounds the saved `provider.json` of every case again with the current parser and prints how the verdicts moved against the `ground.json` kept when the case was written; `--write` keeps the new verdicts and rebuilds `authoring.json` and `expected.json`. It needs no key and no network.

### 11.2 Before and after

"Kept" is `ok` plus `wrong page`: the quote is in the parsed node that carries the label the model gave (the page within one is `ok`). "Before" is the parser and the grounding of section 10; "after" is the parser as fixed and the tolerance rules of 11.4.

| Case | Regulations (requirements written) | Written | Kept before | Kept after | Hallucinated |
|---|---|---|---|---|---|
| `ds-aebs-light` | R152 (46), R10 (7), R13H (5) | 58 | 47 | 54 | 0 |
| `ds-aebs-truck` | R131 (53), R13H (1), R10 (1) | 55 | 46 | 49 | 0 |
| `ds-afs-headlamp` | R149 (40), R48 (17) | 57 | 52 | 57 | 0 |
| `ds-airbag-module` | R114 (18), R10 (7), R94 (4) | 29 | 27 | 27 | 1 |
| `ds-alks` | R157 (104), R155 (12), R156 (12) | 128 | 126 | 128 | 0 |
| `ds-belt-reminder` | R174 (35), R10 (11) | 46 | 41 | 41 | 4 |
| `ds-bev-battery` | R100 (42), R155 (11), R10 (10) | 63 | 50 | 61 | 0 |
| `ds-brake-system` | R13H (80), R10 (10) | 90 | 76 | 76 | 6 |
| `ds-close-coupling` | R102 (57) | 57 | 55 | 57 | 0 |
| `ds-conspicuity-tape` | R150 (31), R104 (26), R48 (5) | 62 | 60 | 61 | 0 |
| `ds-cybersecurity` | R10 (33), R155 (17), R156 (13) | 63 | 44 | 62 | 1 |
| `ds-dcas` | R79 (36), R155 (16), R156 (10) | 62 | 59 | 61 | 0 |
| `ds-front-bumper` | R19 (91), R26 (14), R10 (11) | 116 | 91 | 109 | 0 |
| `ds-frontal-impact` | R94 (21), R137 (10) | 31 | 31 | 31 | 0 |
| `ds-halogen-bulb` | R37 (25) | 25 | 24 | 24 | 1 |
| `ds-immobilizer` | R162 (47), R10 (9) | 56 | 52 | 56 | 0 |
| `ds-motorcycle-lighting` | R53 (99), R148 (18), R149 (18) | 135 | 131 | 134 | 0 |
| `ds-ota-update` | R155 (21), R156 (14), R10 (10) | 45 | 44 | 45 | 0 |
| `ds-phev-reess` | R100 (20), R101 (20), R83 (16) | 56 | 47 | 52 | 1 |
| `ds-rear-impact` | R26 (16), R32 (14) | 30 | 28 | 29 | 0 |
| `ds-spare-wheel` | R64 (26) | 26 | 26 | 26 | 0 |
| `ds-speed-limiter` | R89 (29), R10 (10), R155 (10) | 49 | 26 | 47 | 1 |
| `ds-speedometer` | R39 (28), R10 (15) | 43 | 39 | 42 | 0 |
| `ds-vehicle-alarm` | R163 (66), R10 (11), R161 (2) | 79 | 10 | 77 | 0 |
| **24 cases** | 32 regulations | **1461** | **1232** (84.3%) | **1406** (96.2%) | **15** |

All 24 `expected.json` pass `tools/validate.py` (1,406 requirements after; they were rebuilt, so `ds-vehicle-alarm` has 77 where it had 10). The counts of sections 10.2 and 10.3 are those of the old parser and old grounding, and are left as they were.

- **Of the 229 requirements not kept before, 174 are kept now and 55 are not.** 76 came back through the parser: R163 59 and R89 11 (the `Part` prefix, 11.3), R101 3 (Annex 7 Appendix 3), R162 1 (5.1.2 had no space after its number), and R152 1 and R131 1 (the text under an annex heading is a node a requirement may cite). 98 came back through the grading tolerance (11.4): 63 `6.9.1. Table 3b` read as 6.9.1, 15 `7.3.4. Table B1 M10` read as Table B1 by its caption, 12 with a row id (`Annex 5 Part B 1. Table B1 M10`), 5 a table named as its paragraph, 3 a descriptor after an annex (`Annex 2 Model A`). Seven of the 1,406 kept carry `wrong page` (3 of them came back with the tolerance): the quote is in the right node and the page the model gave is more than one off.
- **The parser alone is worth 5.2 points** (76 of 1,461) **and the tolerance 6.7 points** (98). The tolerance does not make the parser better: it stops counting a model's habit of writing the table into the label as a parser fault. The gate for the parser is the 76.
- **The 55 that are left:** 15 hallucinated (the quote is on no page: 1.0% of what was written, as in section 10); 9 cite front matter that has no node by design (`0.` of R131 five times, `Introduction` of R152 four times); 4 are R13H Annex 4 (a defect of ours, 11.3); 6 are R10 `6.9.2. Table 3b` or `6.9. Table 3b` for 6.9.1, and 3 are R83 `2.4`, `2.5`, `3.5` for `Annex 7 2.4` and so on (the model's own label); 6 are quotes the model did not copy (R100 5.1.1.3 leaves out the middle of the sentence, R114 5.2.2.1 joins two paragraphs, R13H Annex 6 4.4 leaves out the footnote mark inside the sentence, and R10 6.7.1 `Positive +75 V Negative -100 V` and two rows of R163 Annex 7 Table 2 join cells across columns, which the page text does not have in a row; the grid has the rows right); and 12 single cases (R19 `Annex 5 1.` for the text under the Annex 5 heading, R26 `5.1.` for 5.1.1, R89 `1.1.4.2.2.2` whose source line has no final dot and so sits in 1.1.4.2.2.1, R131 `Annex 3 Appendix 2`, R104, R13H, R149, R155, R79, and two R10 labels without a node).

### 11.3 What the cases showed about the parser

| Finding | Where | What it was | What was done |
|---|---|---|---|
| A scope heading the size test refused | R101 `Annex 7 - Appendix 3` (3 requirements of `ds-phev-reess`: `Annex 7 Appendix 3 1.2`, `2.1.2`, `3.1` against our `Annex 7 Appendix 2 ...`) | the defect found by reading the PDF in `parser-weak-points.md` 2.2; DeepSeek met it without being told | the restart rule: a bold, short, titled line at body size or above, with the numbering restarting after it or its id following the scope's; never when it repeats the scope's id. It changed R101 (base and latest) and no other PDF |
| A top-level `Part` that is only a divider | R163 (Part I holds 5-8, Part II 9-18), R89 (3-10, 11-18, 19-26), R67 | the numbering runs on across the parts, so `Part III 21.1.2.1` is the printed `21.1.2.1` with a prefix nobody prints: 70 requirements of `ds-vehicle-alarm` and `ds-speed-limiter` read as "other node" | a Part opens a scope only when the number after it goes back (a `1.` after 8.x); otherwise it is a node of its own (`Part I`, no scope, no parent) and its paragraphs keep the scope of the text before it. 353, 235 and 167 labels changed in R67, R89 and R163. **This is a convention, not a verified defect:** no gold cites a top-level part; the model and the printed number agree, the platform's experts may not |
| A paragraph number with no space after the dot | R162 `5.1.2.An immobilizer`, R48 `6.3.6.1.2.2.The initial downward inclination`, R83 Annex 7 Appendix 2 (`1.Formal Documentation Package`, three paragraphs), R49 Annex 13 2.2.10, R100 Annex 9K Appendix 1 1.5 | the line was text of the paragraph before it | `DOTTED` accepts a capital and a lower-case letter right after the dot. 47 lines of the base PDFs start `<number>.<letter>`; this form made 8 nodes, the others (`4.a. Detected`, `2.x.`, `3.1.(A)`) stay out |
| Plain `A.` and `B.` headings that restart the numbering | R13H Annex 4 (`Annex 4 A 1.2.1` four times) | the parser has no scope for them and the chain keeps A's paragraphs; B's text sits in the previous node | **not fixed**: the label the gold would use (`Annex 4 A`? `Annex 4 Part A`?) is not known. The `restarts` column of `eval/health.py` counts it |
| Appendices headed `Appendix N` alone inside an annex | R131 (`Annex 3 Appendix 2` by the model), R157, R171; R10's are body appendices and correctly bare | the parser labels them `Appendix N ...` and drops the annex | **not changed**: no gold cites an appendix, so nothing settles it |

### 11.4 The grounding tolerance

`ground` used to read a label exactly. Now a label is also read, most literal first, as the node that holds the quote: without a row id (`... Table B1 M10`), without the `Table` clause (`6.9.1. Table 3b` is node 6.9.1, whose tables have no caption line), as the table of a paragraph (`Annex 5 Part B 1. M10`), as the table by its caption when the owner differs (`7.3.4. Table B1`), and without trailing words that carry no digit (`Annex 2 Model A`, `Annex 3 a`). A number is never dropped (`Annex 4 Part 1 1.2` is not `Annex 4 Part 1`) and a label is never cut to one word. The verdict stays "other node" when no reading finds a node that holds the quote, so a wrong paragraph number is not forgiven (`6.9.2. Table 3b`). Annex, appendix and part headings are nodes a quote may sit in (their own text: a communication form, the model of an approval mark). A requirement read as the node's gets that node's label in `authoring.json` and `expected.json`. Each rule is guarded by a test that fails with the rule switched off.

### 11.5 The checks after the fixes

| Check | Result |
|---|---|
| `python eval/anchors.py` | 193/193 (178 as before, and the 15 new-version anchors of the sub-goal against R175 latest) |
| `python eval/fidelity.py` | 281/284 with 3 allowed, unchanged |
| `python eval/test_parse.py` | 67 tests (39 before; 28 new: the rescue and its refusals, restarts, dividers, tree, hash, footnotes, model text, and corpus cases for R101, R89, R163, R162, R48, R13H, R10, R150) |
| `python eval/test_xprovider.py` | 35 tests (29 before; 6 new: label readings, the table readings on R10 and R155, the annex heading, the descriptor, `regrade`) |
| mutation checks | each new rule was switched off in turn and the tests that guard it fail: rescue off (4 tests), same-id rule, successor rule, restart rule, old `DOTTED`, dividers off and always on, footnote marks and footnote numbers kept in the hash, exponents dropped from the hash, a structure-aware hash, table lines kept in `model_text`, footnote flags off, a table under its scope's heading, the restart signal and each of its three filters; for `ground`: no readings, no table by caption, no table of the paragraph, no heading nodes, no trailing words, the label left out of `authoring.json`. Two tests passed with their rule off at first and were tightened: the restart rule (the R101 case also satisfies the successor rule, so a case with a restart and no successor was added) and the sentence and leader filters of the restart signal (the follower rule excluded the same lines) |
| label diff, committed parser against the new one, all 92 PDFs | 14 PDF versions differ: R101 x2 (the rescue), R67 x2, R89 x2, R163 (dividers), R48, R49 x2, R83, R100 x2, R162 (the missing space). Every change is explained above |
| `Node.parent` against the tree `simulate_mapping.py` derived by itself | identical on 52 of 56 regulations; R67, R89, R163 and GTR 9 differ where the old derivation hung body paragraphs under a Part or Text-of-the-Regulation heading (79 parent edges fewer among the ten regulations of the simulation); `simulate_mapping.py` otherwise prints the same funnel, and now reads the parser's tree |
| `eval/baseline.py` on the same tree | `run_cases.py` on the dev case and the three synthetic cases writes the same `results.json` content as before the switch (a table is matched with its owner's breadcrumb, not its own text, as before) |
| `python eval/health.py --baseline spec/testing/parse-health.csv` | 14 of 92 flagged, the same 14 as before and no new flag (`lost`: R13H x2, R107 x2, R171, GTR 9; `orphans`: R40, R51, R155, R156 latest; `front`: R79 x2; `front orphans`: R131 x2). 21 PDF versions changed a count: nodes of R48 +1, R49 +1 (x2), R83 +3, R100 +1 (x2), R101 +8 (x2), R162 +2, and `lost` of R101 15 to 9 (Appendix 3's paragraphs are nodes now). New columns: `scope_rejects` R49 15 and R149 1 (each in base and latest; none unexplained, so `scope-rej` fires nowhere) and `restarts` 20 in 16 PDF versions. Parse time is unchanged without grids (R49 2.0 s against 2.0 s) and 6 to 13% more with them (R10 5.9 to 6.3 s, R49 22.5 to 25.4 s). `parse-health.csv` is regenerated with the new columns |

### 11.6 Not measured, and risks

- **The 24 cases are one writer's opinion.** A model that cites `Annex 7 Appendix 3 1.2` and a parser that now labels it so agree; neither is the platform's gold. Where a label is a convention (the `Part` prefix, the appendices of an annex) the agreement is no evidence.
- **Hallucination is 15 of 1,461.** They are dropped, which is the check's job; a gold built from the kept 96% is a gold of what DeepSeek chose to write, in the sections it chose.
- **24 regulations are in no case,** among them R171, R49, R107 and R43. A parser defect there would still pass every gate.
- **The restart rule was written from one case.** It fired on R101 alone in the 92 PDFs, which is why the label diff is its acceptance test; a regulation whose bold appendix heading is followed by a restart for another reason would open a false scope. `scope_rejects` lists what it refused (R49's 15 `Appendix 3 - Item N` lines, same id; R149's `Annex 5 to this`, too small).
- **The `restarts` column is mostly noise** and raises no flag (21 of the 92 PDF versions had one under the first definition, and a communication form's `1. Additional information: see addendum` was the commonest; the stricter one in `parse.py` keeps a sentence after the number, no dotted leader and a `2.` or `1.1.` behind it). It is for reading where `lost` or `orphans` is also set.
- **The Part rule moves R67, R89 and R163** from a convention without evidence to one with a second writer's.
- **The text-position fallback for tables without a grid was tried and dropped.** `find_tables(strategy="text")` on R171 Table 1, a two-column list set between horizontal rules, returns a grid of 83 rows by 12 columns for the whole of page 27 (or 9 by 12 with the horizontal rules only), not the table; and the other five captioned tables of the base versions without a grid hold their caption and at most two more lines (R100 Annex 3 Table 1 and R148 Table A2-4 are images; the text of R123 Tables 4 and 6 and R155 Table A1 sits in other nodes). `Node.model_text` shows a gridded table once instead of twice.
- **Not run:** `select` and `agree` on the 20 new cases (they send a `spec.md`, which a model wrote here, but the run adds nothing to the parser question); the lexical baseline of section 5 on them; `results.json` is as before.

### 11.7 Reproduce

```
python eval/xprovider.py author --id ds-x --brief "..." --provider llm --timeout 900 --send   # one case, DeepSeek in .env
python eval/xprovider.py regrade                       # offline: all cases, current parser, what moved
python eval/xprovider.py regrade --write               # keep the verdicts, rebuild authoring.json and expected.json
python eval/anchors.py && python eval/test_parse.py && python eval/test_xprovider.py
python eval/health.py --baseline spec/testing/parse-health.csv --csv spec/testing/parse-health.csv
```
