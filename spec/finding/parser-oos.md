# Findings: does the parser scale to regulations it was not tuned on?

Status: results, 2026-10-25. Companion to `spec/finding/parser-scalability.md`. Offline, no model calls. Scripts: `runs/_oos/` (git-ignored; `measure.py`, `spot.py`, `grounding.py`, `ground_tables.py`).

## Summary

- **A true out-of-sample set could not be had.** unece.org answers every request from this machine (curl, WebFetch, Wayback) with a Cloudflare challenge; no UN Regulation outside the 56 could be downloaded, and the challenge was not worked around. `runs/_oos_pdfs/` stays empty. Fallback, as agreed: the corpus PDFs the marker parser was looked at least. Count of mentions in the parser docs, tests and anchors: 0 for R26, R32, R37, R39, R53, R64, R79, R94, R102, R114, R137, R152, R174. These are 13 regulations, 24 PDFs (base and latest), 743 pages, 1 to 77 pages each, old (R26, R32, R37, R39 base) and new (R152, R174), with tables (R53 13, R37 8, R79 11), annexes with appendices (R79, R94, R137, R114) and one 36-page annex-heavy test regulation (R152). **They are still in the 92-PDF silver the weights were set on**, so this is "never inspected", not "never seen". The honest out-of-sample evidence for the marker parser stays R175, R150, R148, R48 (matched from the first run) plus the DeepSeek grounding below, which the parser was never fitted to.
- **On these 24 PDFs the two parsers are nearly the same, and both are good.** Text coverage 0.9915 (both), labels monotone, the 18 label differences are three scope names per PDF on five PDFs. The marker parser is better where they differ (four scope labels instead of one repeated label, no approval-number "paragraph"), but not by much on easy regulations.
- **Both parsers fail the same way on the same structure** (a numbering that restarts inside an annex, R13H Annex 4 Part B; table row ids; unnumbered annex intros). That, not the choice of parser, is the scaling risk.
- **Grounding failures are the model's, not the parser's: 310 of 322 non-ok verdicts (96%).** 6 are parser faults (R89 2, R13H 4; section 4), 1 a harness rule, 5 table-row labels.
- **Verdict: it scales, with the marker parser the better default.** One generic fix made (section 5); anchors 258/259 unchanged, tests green.

## 1. Set and method

| | |
|---|---|
| PDFs | UN R26 b, R32 b/l, R37 b, R39 b/l, R53 b/l, R64 b/l, R79 b/l, R94 b/l, R102 b/l, R114 b/l, R137 b/l, R152 b/l, R174 b/l (24) |
| Coverage | per page, words of `get_text("text")` minus footer lines and header lines repeating on at least 40% of the pages, against the words of the lines in any node with that page (multiset per page); "after front" skips pages before the first node |
| Label sanity | paragraph nodes in document order: same-parent siblings must rise by 1 (`nonmono` = repeat or fall, `jump` = skip), first child of a parent should be 1 (`firstbad`), parent number with no node (`orphans`), annex numbers rising, appendices under an annex heading, duplicate labels |
| Agreement | label multiset (paragraph, table and scope nodes, the platform key) and (label, first page) |
| Spot check | seed 20261025; 9 PDFs (R37 b, R32 l/b, R152 l/b, R64 b, R39 b, R114 b, R94 l); 40 random paragraph nodes per parser; node label, first page, first 8 words against `get_text` of that page, and the scope heading on or before it |
| PyMuPDF trap | the parsers' own table code is used (`use_layout=False`); the measurement scripts never call `find_tables` |

## 2. Per-parser results (24 PDFs)

| | hand | marker |
|---|---|---|
| nodes (paragraph + table + scope) | 8,138 | 8,135 |
| text coverage, mean / min per PDF | 0.9915 / 0.978 | 0.9915 / 0.978 |
| coverage after the front matter | 0.993 | 0.993 |
| siblings not rising / skipping a number | 6 / 14 | 6 / 14 |
| first child of a parent not 1 | 32 | 29 |
| paragraphs with a parent number that has no node | 28 | 28 |
| annex order violations, appendix without its annex | 0, 0 | 0, 0 |
| duplicate paragraph or table labels | 0 | 0 |
| duplicate scope labels (`Annex 8` three times) | 15 (5 PDFs) | 0 |
| time, no grids: total / median / max | 3.4 s / 0.10 / 0.36 | 4.9 s / 0.14 / 0.54 |
| time, with grids: total / max | 10.9 s / 1.3 | 12.0 s / 1.5 |
| spot check, paragraphs | 40/40 | 40/40 |
| spot check, tables (10 each) | 9/10 usable | 9/10 usable |

What the numbers hide:

- **Coverage loss is the title block of page 1** (R79 page 1 0.0, R152 0.33 to 0.39, R102 and R39 0.89); every other page is above 0.9. No body text is outside a node.
- **Non-rising siblings, jumps, first child not 1, orphans are the documents'.** R152 Annex 3 Appendix 2 carries `1.1, 1.2, 2.1, 2.2 ...` under an unnumbered title (8 orphans, 3 non-rising); R39 Annex 4 starts at `2.0`; R174 has `3.1.1` with no `3.1`. Both parsers report the same.
- **Spot check.** The automated test flagged 2 marker nodes (R152 `Annex 3 Appendix 1 3.12`, R37 `2.1.2.2`); reading the PDF page shows a footnote mark inside the first words, the node is right. 40/40 by hand for both. Tables: 9 of 10 are a usable grid (at least 2 rows, one column count, at least 40% cells filled, 95% of the words on the page); the exception for both is a merged-cell table (R37 Annex 8 Table 1, R152 5.2.2.4) with ragged columns. The grids come from the same `parse.py` code in both parsers.

## 3. Agreement of the two parsers

Label P 0.997, R 0.997 (mean per PDF); (label, page) at least 0.975 for every PDF; 16 of 24 PDFs identical, the other 8 differ in 21 labels (hand only) against 18 (marker only).

| Difference | PDFs | Reading |
|---|---|---|
| hand `Annex N` x3 against marker `Annex N Appendix 1/2/3` | R114 l, R137 b/l, R32 l, R94 b/l | an Annex heading naming Appendix 1-3 at once; the marker label is the specific one (the hand parser repeats `Annex 8` three times) |
| hand `Annex 2 42439` / `051424` | R79 b/l, R94 l | the approval-mark example `042439. The approval number indicates ...` read as a paragraph number by the hand parser; the marker parser rejects it |

## 4. Grounding evidence: 50 DeepSeek cases, 6,386 requirements

`testing/ts-*` and `spec/testing/cases/ds-*` (26 and 24 folders; the 50 that have both `provider.json` and `ground.json`). Re-grounded with `eval/xprovider.ground` against the hand parser (identical to the saved verdicts: 6,064 ok) and the marker parser (6,080 ok, 16 more). A non-ok verdict is a parser fault only if the full quote is in the PDF page text and our parse misses or splits the node that holds it. Checked by: full quote (spaces and raised digits ignored) in the raw page text or across a page break; if it is not, only its first half matched (what the verdict "found on a page" used) and the quote is not verbatim; then the printed paragraph number before the quote against the model's label and ours; the rest read in the PDF.

| Verdict | n | model | parser | other |
|---|---|---|---|---|
| hallucinated (quote on no page) | 71 | 71 (51 not in the PDF, 20 differ in quote marks or a symbol, mostly R67 and R127 definitions) | 0 | |
| spans nodes | 40 | 40 (quote drops or changes words, `;` for a full stop; the node holds the printed text) | 0 | |
| wrong page | 57 | 57 (R10: the same sentence in Annex 7 and 8; the node and its page are right) | 0 | |
| no node | 19 | 19 (label not printed on the page, or only half the quote matches) | 0 | |
| other node | 135 | 123 (annex intro text labelled `1.`, table rows by row id `M10`, `A29.2`, figures `LW2/5`, a quote that appears in several nodes) | 6 | 5 table-row labels (R155 Annex 5 Part A Table A1, R40 tables), 1 harness |
| total | 322 | 310 | 6 | 6 |

Parser faults (hand and marker alike): R89 Annex 5 `1.1.4.2.2.2 the rate of change ...` (a number without a final dot, lower case after it, joined into the previous paragraph; 2 rows, fixed in section 5), and R13H Annex 4 Part B `1.2.1`, `1.2.3.3` (numbering restarts after `2.1.3.1`; the Part B paragraphs sit in 2.1.3.1 across pages 38-40; 4 rows, the known restart limit). Harness: R48 `6.1.8` holds its quote, `baseline.heading_only` drops that heading paragraph as a candidate. The marker parse moves 16 non-ok rows to ok (R155 Table A1 rows 4, R161 6, R83 3, R157 2, R23 1) and none the other way.

By regulation (non-ok, model / parser): R10 74/0, R13H 31/4, R155 22/0 (+4 row labels), R67 19/0, R83 15/0, R48 11/0 (+1 harness), R150 12/0, R131 11/0, R79 11/0, R156 10/0, R149 9/0, R148 8/0, R107 8/0, R161 8/0, R127 8/0, R40 7/0 (+1), R163 5/0, R157 5/0, R152 4/0, R137 4/0, R89 0/2, 17 other regulations 1 to 3 each, all model. Limit: the model bucket was assigned by rule and checked by reading about 25 rows, not all 310; a rule error would move rows to the parser, not many (the one rule that was wrong at first, "split paragraph", was a quote with elided words).

## 5. Fix made

`src/regcomp/parse_marker.py`, `lex`: a dotted number of three or more parts with no final dot may be followed by a lower-case word (`1.1.4.2.2.2 the rate of change`); before it needed a capital. A measurement is not a three-part number. Not per regulation.

| | before | after |
|---|---|---|
| `anchors.py --parser marker` | 258/259 (R171 65/66) | 258/259 |
| `anchors.py` (hand) | 254/259 | unchanged, `parse.py` untouched |
| `test_parse_marker.py` / `test_parse.py` | 28 / 67 pass | 28 / 67 pass |
| `fidelity.py --parser marker` | 393/401 (5 failed) | 393/401 |
| silver micro P / R / F1 over 92 PDFs | 0.951 / 0.944 / 0.947 | 0.950 / 0.944 / 0.947 |
| nodes changed in the 92 PDFs | | +1 node each in R89 base and latest (`Annex 5 1.1.4.2.2.2`), +1 in R40 latest (`3.2.2`); no label removed |

The silver P drops by 0.001 because the hand parser lacks the three nodes. Changing the parser source changes the agent's parser hash: every cache keyed on it (`regulations/data/_cache`, the agent's cache) is rebuilt on the next run.

## 6. Verdict

- **It scales.** On 24 PDFs nobody inspected the structure is right: coverage 0.99, 40/40 paragraphs, 9/10 tables, all anomalies are in the source. On 50 DeepSeek cases (6,386 requirements) 95.0% of the requirements ground with the hand parser and 95.2% with the marker parser, and 96% of the rest is the model's quotes and labels.
- **Which: the marker parser.** Equal on easy regulations, better on annexes that name several appendices and on approval-mark examples, 393/401 against 382/401 on fidelity, 258 against 254 of 259 anchors, 0.14 s median against 0.10 s. Recommended as the default; not flipped here.
- **Where it breaks (both parsers).** A numbering that restarts or repeats a scope id (R13H Annex 4 Part B, R164, R3), table row ids as labels, unnumbered intro text of an annex. Generic fix: a third relation, "same signature restarting at its first value, closing the old family", with the evidence that separates it from R49's `Appendix 3 - Item 7` (the same shape; see `parser-scalability.md` section 4); and nodes for table rows when a table's first column is an id. Neither is a per-regulation rule; neither is done.
- **What this does not show.** No regulation outside the 56 was parsed. The first item of any follow-up is to put real UNECE PDFs (R1, R8, R20, R31, R45, R98, R112, R113, R119, R122, R144) into `runs/_oos_pdfs/` by hand from a browser and run the script below on that folder.

## 7. How to run

```
python runs/_oos/measure.py                 # tables of section 2 and 3 (results.json), edit REGS/PDFS for a folder of PDFs
python runs/_oos/spot.py                    # section 2 spot checks
python runs/_oos/grounding.py               # section 4, both parsers, writes runs/_oos/grounding.json
python runs/_oos/ground_tables.py           # the adjudicated table of section 4
python eval/anchors.py --parser marker; python eval/test_parse_marker.py; python eval/test_parse.py
```
