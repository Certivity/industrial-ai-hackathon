# Findings: where the parser is weak, and how to strengthen it

Status: results, 2026-10-24, later the same day; **updated the same night with the fixes (section 6)**. Companion to `spec/finding/finding.md` (the rules), `spec/testing/report.md` sections 9 (the fidelity round) and 11 (the fix round and 20 more DeepSeek cases) and `spec/finding/mapping-simulation.md` (what limits the pipeline). Sections 1 to 5 review `src/regcomp/parse.py` as it was, against the specs, with eight small probes over the 56 base PDFs; the parser was not changed by that review. `spec/proposal.md` A1, the build order, verification and risks were updated from it, and again after the fixes.

## Summary

- **Fixed (section 6).** 4.1 (a scope heading on restart evidence), 4.2 (two health signals: `scope-rej` flags, `restarts` is a column), 4.3 (the new-version anchors in the gate, 193 of 193; the `Table` tolerance of `ground`; 24 DeepSeek cases over 32 regulations as the triage for the unanchored ones) and 4.4 (the tree and the hash in `parse.py`, read by `baseline.py` and `simulate_mapping.py`) are built and tested, each rule with a test that fails when the rule is switched off. 4.5 (a table fallback) was tried and dropped: it would only add false grids. The cases also found two things the probes had not: top-level `Part` headings that are only dividers (R67, R89, R163) and paragraph numbers with no space after the dot (R162, R48, R83, R49, R100). The defect of 2.2 was found independently by DeepSeek.

- **The parser holds up on every check we have; the weak spot is how it is checked.** `eval/anchors.py` passes 178 of 178 distinct anchors, but it compares a label with a page. It covers five regulations (four of them in-sample), reads no text, and says nothing about the other 51. The held-out main case will come with no anchors at all.
- **One real defect passes every gate.** R101 Annex 7 has "Appendix 3" set in bold at body size, while Appendices 1 and 2 are 13 pt. The size test rejects it, so Appendix 3's paragraphs are labelled `Annex 7 Appendix 2 1.1`, its `1. Introduction` falls out of the chain, and `eval/health.py` does not flag the PDF. It is the only confirmed miss among 17 bold lines that match a scope regex and were rejected (15 are item labels inside one appendix, 1 reads as a reference in running text).
- **Scope headings hang on one style test** (bold and at least 1.15 times the body size). A miss is silent and takes a whole appendix's numbering with it. The cheap fix is to accept a bold, short, regex-matching line as a scope when numbering restarts after it.
- **`Node` lacks what the proposal gives it.** No heading, parent, breadcrumb, hash or line breaks in `parse.py`; the eval scripts each rebuild their own tree. The sub-goal diff and the obligation stage need them.
- **Tables depend on ruling lines.** A table drawn with horizontal rules only is never tried (R171 Table 1); 8 of 426 captioned tables have no grid. A small share, but tables carry real gold (R150 Table 3, R10 6.9.1).
- **Four suspected weak points turned out fine.** Footnotes do not leak into the wrong node, the longest-chain rule fails gracefully, the new-version side of the sub-goal anchors passes 15 of 15, and geometry is no help (every text line starts at the same x).
- **The parser is not what limits the score.** `mapping-simulation.md` and `report.md` section 5 put the loss at regulation choice (three of four baseline cases score zero) and section choice. Fix the parser's blind spots because they are cheap, then spend the time on selection.

## 1. What was run

PyMuPDF 2.0 in the session venv, the 56 base PDFs of `regulations/data/`, `src/regcomp/parse.py` as committed. The probe scripts are in the session scratchpad, which is temporary; they are not in the repo (4.2 and 4.3 say what to add).

| # | Probe | Result |
|---|---|---|
| 1 | Footnote-like lines (under 0.92 times the body size, in the bottom fifth of a page, starting `N text`) that sit inside a node | R48: all 18 footnotes of the body (pages 1-84) are in the node whose text carries the mark. Footnote 2 of page 3 is repeated under 2.4.3, 2.4.4 and 2.4.5, each of which cites it. In R150, R148 and R48 none sits mid-node across a page break. R10 and R49 report 2 each, not opened |
| 2 | Lines at the start of which `Annex N` or `Appendix N` appears, short, not ending in a sentence mark, that the style gate rejected | 739 headings accepted over the 56 PDFs; 374 such lines rejected, 357 of them plain text (references, lists of annexes). The other 17 are bold: R101 1 (a miss), R49 15, R149 1 |
| 3 | The 15 bold rejects of R49 | all read `Appendix 3 - Item 1` to `Item 15` inside `Annex 9B - Appendix 3`: item labels, not scopes. The parser is right to ignore them |
| 4 | The R149 bold reject | `Annex 5 to this`, at 0.9 times the body size: a reference in running text (the page was not opened) |
| 5 | Annex and appendix numbers should run without a gap | flags R49 only (Annex 4 has Appendix 9 alone; Annexes 8, 10 and 11 have Appendix 2 alone). That looks like the source's own numbering, plus the probe reading `Annex 9B` as 9; not chased. It misses R101, because the missing appendix is the last one |
| 6 | x of the numbered line, accepted starts against left-out lines that carry a sentence, wrapped references excluded (R13H, R107, R171, GTR 9, R48, R101) | accepted starts are at x = 57 in 99.2-100% of cases (R13H 704 of 705, R107 1,599 of 1,601, GTR 9 600 of 600). Of the 191 left-out sentence lines, 178 are at an accepted x (R13H 23 of 23, R48 14 of 14, R101 21 of 21) |
| 7 | Why the chain drops R13H `5.1.4.1.3.` and `5.2.24.6.` | `5.1.4.1.3.` stands between `5.1.4.4.1.2.` and `5.1.4.5.` in the source: the source is out of order. `5.2.24.6.` at the start of a line reads `is activated. The different levels above…`, a reference wrapped from a line that ends in "…before the warning sign", not in "paragraph", so `wraps_reference` misses it and the chain catches it. The real `5.2.24.6.` on page 19 is kept. In both cases the text stays in the neighbouring node and the page stays right |
| 8 | The new-version side of the sub-goal: `source` (page, paragraph) of every modified and added entry of `subgoal/dev/expected.json`, against the parse of R175 latest | 15 of 15 distinct (page, paragraph) found with the page inside the node. `eval/anchors.py` does not include them |

## 2. The weak points

### 2.1 The gate says little outside five regulations

- Four of the five anchor sets are in-sample (`finding.md` section 1: the rules were generalised after R148 and R48 failed). R175 is the one hold-out, a 17-page document with simple structure.
- The gate compares a label with a page. It reads no text; `eval/fidelity.py` closes part of that for 284 expert requirements, again on the same five regulations.
- For the 51 other regulations "parses" means "passes `eval/health.py`". R101 passes it and is wrong (2.2).
- The held-out main case has no anchors. The only independent check of the parser there is a model's own gold (`xprovider.py ground`), and its verdicts are noisy: of 231 DeepSeek requirements, 4 were hallucinated and 30 more "not ok", 18 of those 30 because the model added a `Table (Class B)` suffix our node does not have, and the tolerance rule for that is not built (`report.md` 10.3).

### 2.2 Scope headings are style-gated, and a miss is silent

The gate is `raw.bold and raw.size >= 1.15 * body_size` ([parse.py:213](../../src/regcomp/parse.py#L213)), and bold and size come from the first span of the line ([parse.py:194](../../src/regcomp/parse.py#L194)). The 1.15 ratio already replaced a fixed 13 pt once, because the renderer scales pages (`report.md` 2.2: 22 of 92 PDFs parse differently after that round). The next surprise is a source that is inconsistent inside one document.

R101, the confirmed case (body 10.5 pt, gate 12.07 pt):

| Line | Bold | Size | Page | Accepted |
|---|---|---|---|---|
| `Annex 7 - Appendix 1 Determination of the total road load power…` | yes | 13.0 | 63 | yes |
| `Annex 7 - Appendix 2 Alternative procedure for determination of the to…` | yes | 13.0 | 69 | yes |
| `Annex 7 - Appendix 3 Determination of REESS current and REESS voltage of PEVs` | yes | 10.5 | 72 | **no** |

What happens next: the lines of Appendix 3 stay in the scope `Annex 7 Appendix 2`. The node holding "1.1. This Appendix defines the method and required instrumentation to determine the REESS current…" is labelled `Annex 7 Appendix 2 1.1`; Appendix 3's `1. Introduction` is left out; `2.2.4.` of Appendix 2's own text (page 71) is left out too; node `Annex 7 Appendix 2 1` spans pages 69-72, so it holds text that follows it from both appendices. Two numbering runs compete for one chain and the shorter loses.

Cost: the page stays right, so a page-or-paragraph citation survives. The label is wrong, which shows in the UI, and text of two appendices is mixed in the extractor's input. One PDF of 56 (1.8%) with one scope; the held-out regulations may have more or fewer.

### 2.3 `Node` does not carry what the proposal assumes

`Node` holds `kind`, `label`, `scope`, `num`, `page_start`, `page_end`, the node's own `text` lines with the page of each, `grid`, and the properties `body`, `figure_refs` and `page_of(quote)`. The proposal's A1 also lists a heading, `parent_id`, a `path` breadcrumb, `text_hash`, character offsets, and the char-to-page map; `precision.md` 4.2 needs a lead-in stem and its children as one unit. None of that is in `parse.py`. Parent and breadcrumb are derived separately in `eval/baseline.py` and `eval/simulate_mapping.py`, so every script holds its own tree.

Two more things for the diff (B1) and the extractor:

- `join_lines` joins the lines of a paragraph with a space, so `(a)`, `(i)` and dash lists become one run-on string. The extractor can split it, but the structure is gone and a hash cannot tell a re-flowed list from an edited one.
- Footnote text is inline and binding: R48 6.22.7.4.5 carries footnote 15, "This provision does not apply for passing-beam lighting when bend lighting is produced for a right turn…". It must reach the extractor and the hash. It begins with its number glued on (`15This provision…`), and a footnote number renumbers when a footnote is added in a new version.

### 2.4 Tables depend on ruling lines

- `_ruled` ([parse.py:399](../../src/regcomp/parse.py#L399)) needs at least two horizontal and two vertical rulings before `find_tables()` is tried. A table drawn with horizontal rules only is never tried; R171 Table 1 is one (`report.md` 9.3).
- 8 of 426 captioned tables over the 92 PDFs have no grid (2 drawn as images, R171 Table 1, R123 Tables 4 and 6, R155 Table A1, and the latest versions of R100 and R148). Their text stays in the node, flattened.
- A grid is also a second copy of text that is still in `node.text` flattened, so the extractor sees the table twice.
- Tables without a ruling and without a caption are unseen by construction.

### 2.5 The proposal had drifted

`spec/proposal.md` A1 still described the strict-successor sanity check, per-row table nodes, and stripping E/ECE headers. `finding.md` section 3 lists the corrections; the proposal's status line said they were not merged. Someone building from the proposal would have implemented the rules that failed on R148 (4 of 40) and R48 (23 of 35). A1, the build order, verification and risks are now merged; the rest of section 3 (REFERS_TO grammar, B1 matching order, sub-goal) is not.

## 3. What held up

- **Footnotes do not leak.** I expected footnote text at the foot of a page to be appended to whatever node was open when the page ended. It is not: Certivity's render puts the text inline under the paragraph that cites it (probe 1).
- **The chain rule fails gracefully.** What it drops is a source anomaly or a wrapped reference (probe 7). The text stays attached to the previous node, so the page is right and only the label can be a neighbour's. The 315 left-out lines that carry a sentence in the base PDFs are a review queue, not a silent loss of text.
- **The sub-goal's new side is already fine** (probe 8). It is only missing from the gate.
- **Geometry cannot help** (probe 6). The Chrome render puts every text line at x = 57, indentation included, so there is no layout signal for paragraph starts beyond the number's text.

## 4. Fixes, in order of value per hour

The plan as written before the fixes; **4.1 to 4.4 are built and 4.5 was dropped, each item ends with what became of it** (section 6 has the numbers).

**4.1 Accept a scope heading on restart evidence, not on size alone** (`_scope_lines`, about an hour).

- A candidate is a line that starts with the Annex, Annex-Appendix or Appendix pattern, is at most 110 characters, does not end in `.`, `,` or `;`, and is bold at any size.
- It opens a scope when numbering restarts after it (the next numbered candidate is a depth-1 `1`, while the scope it would leave has already passed 1), **or** when its id is the successor of the previous scope's id (Appendix 3 after Appendix 2).
- It never opens a scope whose id equals the id of the scope it sits in: R49's `Appendix 3 - Item N` repeats the id of its own appendix.
- Keep the size gate as it is for headings that pass it; the new rule only rescues the ones that fail it.
- **Built**, with two additions that came out of testing it: a rescued line must also be at body size or above and have a title that does not start in lower case (R149 `Annex 5 to this` is a footnote-sized reference), and the restart has to follow a scope that has had a number above 1. R101 base and latest changed, no other PDF because of this rule.
- Acceptance: a node whose body starts "1.1. This Appendix defines the method and required instrumentation to determine the REESS current" has scope `Annex 7 Appendix 3`; `python eval/anchors.py` stays 178 of 178; a node-label diff over the 56 base parses (cached in `regulations/data/_cache`) differs for R101 and for no other PDF, and `python eval/health.py --baseline spec/testing/parse-health.csv` moves no other PDF's counts; a test in `eval/test_parse.py` that fails with the rule switched off (the mutation check of `report.md` 9.4).

**4.2 Two health signals for what the gate cannot see** (`eval/health.py`, an hour).

- `scope_rejects`: bold lines that match a scope regex and were rejected. Over the 56 base PDFs that is 17 lines for one real miss, which is cheap to review by eye.
- `restarts`: left-out candidates that are a depth-1 `1` after the chain passed 1. R101 has one (page 72). The noise level, form fields numbered from 1, is not measured.
- Not worth adding: the gap check on annex and appendix numbers (probe 5): one flag I could not turn into a defect, and it misses a missing last appendix.
- **Built.** `scope_rejects` (all refused lines, each with its reason) and `scope_open` (the ones with no reason: a flag, `scope-rej`); over the 92 PDFs the only lines refused are R49's 15 `Appendix 3 - Item N` (same id) and R149's one. `restarts` is a column, not a flag: the noise the plan left unmeasured is large (a communication form's `1. Additional information: see addendum` in R107, R116, R161, R162; 21 PDF versions had one under the first definition), so it counts only a `1.` with a sentence after it, no dotted leader and a `2.` or `1.1.` behind it, and raises no flag.

**4.3 Widen the gate** (an hour).

- Add the `source` of `subgoal/dev/expected.json` (new version) to `eval/anchors.py`: 15 anchors, passing now, and unguarded.
- Build the `ground` tolerance for a `Table` suffix on a paragraph that has a grid and no caption (`report.md` 10.3), then run `xprovider.py author` and `ground` over regulations that have no anchors. Its "other node", "spans nodes" and "no node" verdicts are the parser triage list for the 51 regulations. It sends regulation page text to the model's provider, so confirm before the first `--send`.
- On Sunday the held-out `subgoal/*/requirements_old.json` joins the gate with no edit (already globbed).
- **Built.** `eval/anchors.py` checks the 15 new-version pairs against R175 latest (193 of 193). `ground` reads a label as the node that holds the quote without a `Table` clause or row id, as the table of a paragraph, as a table by its caption, and without trailing words that carry no digit; annex and appendix headings are nodes a quote may sit in; `xprovider.py regrade` re-grounds saved cases with the current parser. The 24 cases over 32 regulations are the triage list (`report.md` section 11).

**4.4 Move the tree into `parse.py`** (half a day; the obligation stage and B1 need it anyway).

- Add to `Node`: `heading`, `parent`, `path` (breadcrumb), `children`, a line-preserving text for the model next to `body`, and `text_hash`.
- `text_hash`: the body without its number prefix (`NUMBER_PREFIX`), footer already dropped, footnote text included (it is binding). Ignore raised footnote marks and a footnote's own number prefix when hashing, because they renumber between versions. That last choice is a design decision, not a measurement.
- Make `eval/baseline.py` and `eval/simulate_mapping.py` use it, so there is one tree.
- **Built.** `heading`, `title(width)`, `parent`, `children`, `path`, `structured`, `model_text`, `note` and `text_hash`. The hash ignores line breaks and list layout as well as footnote numbers and marks (a layout change is not a changed paragraph), and keeps exponents. `Node.parent` equals the tree `simulate_mapping.py` built on 52 of 56 regulations and differs, for the better, on four where a Part heading had taken the body's paragraphs as children; both scripts now read it, and `run_cases.py` writes the same `results.json` content as before.

**4.5 A fallback for captioned tables without a grid** (later; about 2% of tables).

- Where a caption has no grid, try `find_tables(strategy="text")` on that page, or leave the page image to the extractor. `eval/health.py` already counts captions without a grid; use that count as the trigger.
- Show the grid and the flattened text as one block to the extractor, not twice.
- **Fallback dropped, one block built.** `find_tables(strategy="text")` on R171 Table 1 returns the whole page as an 83 by 12 grid (9 by 12 with only the horizontal rules); the other five captioned tables without a grid hold a caption and at most two lines. `Node.model_text` is the one block: the lines outside the ruled tables, then each table once.

## 5. Not measured, and risks

- **One confirmed defect in 56 base PDFs (fixed; see section 6).** Its effect on the score is probably small while the page stays right; it grows where text from two appendices lands in one node and the extractor or the diff reads it. The 36 latest PDFs were not probed.
- **The reject filter is crude.** Probe 2 drops lines that end in a sentence mark and keeps the rest; a heading that ends in a full stop would be missed by the probe, as it would by the 4.1 candidate rule.
- **4.1 was untested on the other PDFs when this was written.** The label diff over the 92 PDFs was its acceptance test, because a rescue rule can open false scopes in a document nobody has read: it fired on R101 only.
- **Probe 5's R49 flag was not chased.** It may be a source quirk or a probe artefact.
- **Probe scripts are not in the repo.** 4.2 and 4.3 turn the useful ones into checks.
- **Nothing here measures extraction.** Obligations, the applicability filter and requirement-level scores are still unmeasured (`finding.md` section 5).

## 6. What the fix round did

Status: results, 2026-10-24, night. The fixes of section 4 were built against the parser as committed (`HEAD`), checked against twenty DeepSeek cases that had been generated *before* any change (so the fixes were not fitted to them), and are written up in `spec/testing/report.md` section 11. PyMuPDF 2.0, the 92 fetched PDFs.

### 6.1 What was built

| Weak point of section 2 | Change | What guards it |
|---|---|---|
| 2.2 a scope heading hangs on one style test | `_rescued` in `parse.py`: a bold, short, titled line at body size or above that matches an annex or appendix pattern opens a scope when the numbering restarts after it or its id follows the scope's, never when it repeats the scope's id | 10 unit tests (accepted by restart, by successor, by restart alone; refused with each reason; a restart needs a scope that has passed 1; the labels and the tree of a rescued appendix) and a corpus test on R101; each fails with the rule off; the label diff over the 92 PDFs changes R101 (base and latest) and no other PDF because of it |
| 2.1 the gate says little outside five regulations | the 15 new-version pairs of the sub-goal in `eval/anchors.py` (193 of 193); `scope-rej` in `eval/health.py`; 20 new DeepSeek cases and `xprovider.py regrade` over 24 | `anchors.py` exit status; `report.md` 11 |
| 2.3 `Node` lacks what the proposal gives it | `heading`, `title(width)`, `parent`, `children`, `path`, `structured`, `model_text`, `note`, `text_hash`; both eval scripts read the tree | 9 unit and corpus tests; `Node.parent` against the old derivation on 56 regulations; `run_cases.py` writes the same `results.json` content as before the switch |
| 2.4 tables depend on ruling lines | **dropped**: the text-position fallback only adds false grids (4.5); `model_text` shows a gridded table once | test on R10 6.9.1 and a unit test |
| 2.1 the verdicts of `ground` are noisy | readings of a label (`Table` clause, row id, caption, trailing words), annex headings as nodes | 6 tests, each fails with its rule off |

### 6.2 What the twenty cases found that the probes had not

- **A top-level `Part` is not always a scope.** R163 numbers 1-4 in the body, 5-8 in Part I and 9-18 in Part II; R89 runs through Parts I-III as 3-10, 11-18, 19-26; R67 the same. The parser labelled `Part III 21.1.2.1` for the paragraph printed `21.1.2.1`, and DeepSeek, which reads the printed number, cited 70 of them without the prefix. A Part now opens a scope only when the next number goes back. This is a convention no gold settles.
- **A paragraph number with no space after the dot is text of the paragraph before it.** R162 `5.1.2.An immobilizer ...` (the model cited 5.1.2 and our node was 5.1.1), R48 `6.3.6.1.2.2.The initial downward inclination ...` (R48 is anchored, and none of the 178 anchors cites it), three paragraphs of R83 Annex 7 Appendix 2, one each in R49 and R100. 47 lines of the base PDFs start `<number>.<letter>`; the form with a capital and a lower-case letter made 8 nodes.
- **The defect of 2.2 is real**: `ds-phev-reess` cited `Annex 7 Appendix 3 1.2`, `2.1.2` and `3.1`, and our nodes were `Annex 7 Appendix 2 ...`.
- **Left as they are, with the evidence:** R13H Annex 4 has plain `A.` and `B.` headings over paragraphs numbered from 1 (the model wrote `Annex 4 A 1.2.1`); the label the gold would use is not known, and `lost` already flags R13H. R131, R157 and R171 head the appendices of an annex `Appendix N` alone and are labelled so; no gold cites an appendix. R89 `1.1.4.2.2.2 the rate of change ...` has no final dot and a lower-case word after the number: the other four lines of that shape in the base PDFs (R103 1, R157 2, R171 1) read as wrapped references (`5.4.2.1 or 5.4.2.2`, `3.2.12.2.6.4.1 of the information document`), so a rule for it would add four candidates that are references for one that is a paragraph, and leave the chain to drop them (not tried).

### 6.3 Numbers

| Check | Before | After |
|---|---|---|
| `python eval/anchors.py` | 178/178 | 193/193 |
| `python eval/fidelity.py` | 281/284, 3 allowed | 281/284, 3 allowed |
| `python eval/test_parse.py` | 39 tests | 67 tests |
| `python eval/test_xprovider.py` | 29 tests | 35 tests |
| requirements of the 24 DeepSeek cases kept (quote in the node with the label the model gave) | 1,232 of 1,461 (84.3%) | 1,406 (96.2%): 76 through the parser, 98 through the readings of `ground` |
| label diff of 92 PDFs against the committed parser | | 14 PDF versions differ (R101 x2, R67 x2, R89 x2, R163, R48, R49 x2, R83, R100 x2, R162), all explained |
| `python eval/health.py` flags | 14 of 92 | 14 of 92, the same set; `scope-rej` fires on none (R49's 15 lines repeat their scope's id, R149's one is footnote-sized) |
| `restarts` (a column, no flag) | | 20 in 16 PDF versions: R13H Annex 4 (real), R49 Item 1, R101, R48, R83 (a list or a figure note), R107 and R116 (mostly a communication form's field), R171 Table 1, GTR 9 Part IX |

### 6.4 Still open

- **Label conventions that nothing settles:** the `Part` prefix (now dropped where numbering carries on), a bare `Appendix N` inside an annex, R13H Annex 4's `A.`/`B.`. A page is enough for a citation to count, so these only matter where the page is also wrong. The held-out regulations will have their own; the new signals (`scope-rej`, `restarts`) and `xprovider.py author` / `regrade` are the way to find them quickly.
- **24 regulations are in no DeepSeek case** (R3, R6, R7, R23, R38, R40, R42, R43, R49, R51, R62, R67, R92, R103, R107, R116, R123, R127, R128, R132, R164, R171, R175, GTR 9); R171, R49, R107 and R43 are the large ones.
- **Extraction is still unmeasured.** Nothing here says anything about obligations, the applicability filter or requirement-level scores; the parser is not what limits the score (`mapping-simulation.md`).
