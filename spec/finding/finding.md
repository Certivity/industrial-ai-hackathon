# Findings: what the regulation PDFs look like, and what the graph has to do about it

Status: results of the data exploration, 2026-10-24. Companion to `spec/proposal.md`; section 3 lists where the data disagrees with it, section 4 is the build order.

## Summary

- **The structural graph holds up.** A deterministic parser (PyMuPDF, no LLM) put **178 of 178** distinct expert anchors on the right node and page: R150 31, R148 40, R48 35, R10 15 (rear-lamp gold) and R175 57 (the 94 old requirements of the sub-goal case sit on 57 distinct paragraphs). The gold `page` is the physical PDF page, which the printed footer confirms, so the proposal's main open risk is closed.
- **Caveat on those numbers.** The rules were written on R150, then generalised after they failed on R148 (4/40) and R48 (23/35). R150, R148, R48 and R10 are therefore in-sample. R175 (57/57 paragraphs) ran with the rules frozen, so it is the only hold-out.
- **Three proposal rules must change:** paragraph numbering (use the longest increasing chain, not a successor check), tables (not one node per row, and never trust extracted cell text), and "pick the subtree and extract every obligation" (a subtree gives only 26-49% node-level precision, so the applicability filter is where precision is decided).
- **Figures can be ignored in v1.** 0 of 190 gold requirements use figure content. Some images do carry binding numbers, so keep the references and show the page image in the UI.
- **The sub-goal is mostly deterministic.** Hash alignment leaves 8% of nodes to examine, routing the old requirements by their anchors catches 7 of 7 changed requirements in a review set of 18 of 94, and the expected `reason` strings come out of a word diff.
- **Do first:** download all 92 PDFs (223 MB) while the links work and run the parser over every one of them. Only 5 of 56 regulations have been seen.

## 1. What was tested

| Regulation | pages | text (about) | anchors | rules at the time | found, page right |
|---|---|---|---|---|---|
| UN R150 base 1.2.1 | 54 | 33K tokens | 31 | written here (in-sample) | 31/31 |
| UN R148 base 1.6.0 | 48 | 27K | 40 | R150 rules unchanged: 4/40, then generalised (in-sample) | 40/40 |
| UN R48 base 9.3.0 | 122 | 74K | 35 | R150 rules unchanged: 23/35, then generalised (in-sample) | 35/35 |
| UN R10 base 7.2.0 | 148 | 63K | 15 | R150 rules unchanged: 15/15 | 15/15 |
| UN R175 base 0.1.0 (sub-goal `old.pdf`) | 17 | 13K | 57 (for 94 requirements) | frozen (hold-out) | 57/57 |

An anchor is a (page, paragraph) pair from `cases/dev-rear-lamp/expected.json` (R150, R148, R48, R10) or from `subgoal/dev/requirements_old.json` (R175). It counts as found when a parsed node has the same label, compared with the platform's own `_paragraph_key`, and the gold page lies inside that node's page range. The four rear-lamp regulations together are about 197K tokens of text.

PDFs are in `regulations/data/<reg>/<role>/` (R150, R148, R48, R10 base; R175 base and latest). The prototype parser (about 150 lines) and the experiment scripts (anchor test, R175 diff, figure inventory, table cells) are in the session scratchpad, which is temporary; they are not in the repo.

## 2. What the data looks like

### 2.1 The files

- Every PDF is a Chrome/Skia render of Certivity's HTML (A4, created 2026-10-23). Page 1 says "Cite pages of THIS file". There are no bookmarks, no PDF page labels, and **no table of contents in the text** (checked on R150, R148, R48, R10).
- Every page has a footer line `UN R150, version 1.2.1 | page 7 of 54`. Checked on every page of R150, R148, R48, R10 and both R175 versions: N always equals the physical index. A single regex strips it.
- The text layer is complete except for images: R150 18 of 54 pages have an image, R148 16/48, R48 29/122, R10 76/148, R175 2 of 17 and 2 of 19.
- Fonts: body Times 10.5 pt, annex headings Helvetica-Bold 13 pt, part headings bold Times 10.5, table text 9.5, exponents 7.9 with the superscript flag.

### 2.2 Structure

Numbering restarts inside every annex, part and appendix. The gold labels are `3.3.1.1`, `Annex 4 Part 1 1.2`, `5.1.4.4.1. Table 3` and `Annex 6 Part 6 3. Table A6-1`, i.e. `<scope> <number>` and `<owning paragraph>. Table <id>`.

| Form | Example | Seen in |
|---|---|---|
| Annex | `Annex 4 Photometric…` (bold, 13 pt) | all |
| Annex with a letter | `Annex 2A …`, `Annex 3B …` | R10 |
| Appendix inside an annex | `Annex 4 - Appendix 1`, `Annex 22 – Appendix 1` (hyphen or en dash) | R10 |
| Appendix in the body | `Appendix 1 List of standards…` | R10 |
| Part | `Part 1 - Photometric…`, `Part A: Position, …` (bold) | R150, R48 / R148 |
| Paragraph | `3.3.1.1. Every device…` | all |
| Heading without the final dot | `5.7 Grouped, combined…`, `1 Scope`, `6.1 General` | R48, R148, R150, R10 |
| Table caption | `Table 3 Requirements…` (plain, with title), `Table 2a` (bold, alone), `Table A6-1 …` | R150, R10 |

### 2.3 Numbering is dirty

What looks like a paragraph start but is not: 16 table cells in R150 (`5.1.`, `5.2.`, `5.3.`), wrapped lines that begin with a reference (R48 `4.4.1. need not to be repeated…`), figure legend items (R10 `12 RF absorber material`, 24 nodes), and values (`60 V/m`). What is missing: R48 has no `2.5.18`; R150 goes from `6.` straight to `6.1.1.` because the `6.1` heading has no final dot.

The proposal's successor rule fails on this. R150 with the strict rule rejected 28 candidates, 10 of them a real section (`6.1.1`-`6.2.7`). R48 scored 23/35 because the dotless `5.7 …` heading broke the chain for everything under it. R148 scored 4/40 because `1 Scope` has no dot, so nothing ever started.

What works: per scope (annex, part, appendix), take the **longest strictly increasing chain** of candidate numbers (tuple order, O(n²), n up to about 1,200). Candidates accepted, per document: R150 502 of 520, R148 386/431, R48 1181/1200, R10 782/808. Every left-out line I inspected was junk of the kinds above. A strict successor rule would have failed 0, 1, 3 and 4 times on the accepted chain (R150, R148, R48, R10), each time on a real gap. A dotless line is a candidate only if it is nested (depth 2 or more) or styled (bold or 12 pt and up); without that rule the legend items get in.

### 2.4 How obligations are written

- R150, R148 and R10 use "shall/must". **R48 often does not**: `6.4.4.2. In height: not less than 250 mm and not more than 1,200 mm above the ground.`, `6.10.5.1. Horizontal angle: 45° inwards and 80° outwards…`. 13 of the 35 gold-cited R48 nodes have no shall/must/should. The gold rewrites them as "The horizontal angle of the lamp shall be …" and splits one paragraph into up to three requirements.
- Requirements per cited paragraph: R150 1.26, R148 1.58, R48 1.60, R10 2.13 (R10 §6.9.1 gives one per test pulse).
- **R48 §6 is a template.** It has 28 device sections (6.1 Main-beam headlamp … 6.28 Reversing projection) with the same children in the same order: 1 Presence, 2 Number, 3 Arrangement, 4 Position, 5 Geometric visibility, 6 Orientation, 7 Electrical connections, 8 Tell-tale, 9 Other requirements (the retro-reflector section has no Electrical connections or Tell-tale, so its 7 is Other requirements). Checked on 6.4, 6.7, 6.10, 6.14.

### 2.5 Tables

- Counts of captioned tables parsed: R150 11, R148 16, R10 33. R48 has none with a caption, but its pages draw ruled tables all the same (the colour boundaries of 2.11 among them): 26 of its nodes carry a grid since `spec/testing/report.md` section 9. R10 6.9.1 holds its test pulses in two tables that have no caption line, so a grid belongs to the node whose text lies inside it, not only to a captioned table.
- A table can span pages: R150 Table 3 has its header on p12 and its rows on p13, and the gold cites p12 (the caption page). Table A6-1 runs p46-47.
- `page.find_tables()` finds the grids (Table 3: 10 columns by 18 rows). **`Table.extract()` text cannot be used**: spaces are lost (`Thetwosamples`), exponents fuse into digits (`1 .20∙103` for 1.20·10³), and signs move (R10 pulse 1 reads `75V -` for `-75 V`).
- What works, and was checked on both tables: take the cell rectangles from `find_tables()`, build each cell's text from the spans inside it (`get_text("dict", clip=cell)`), render superscript spans as `^x`, and forward-fill merged key cells. R10 then reads `1 | -75 V | -450 V | 500 pulses | III | III`; R150 Table 3 reads `IA, IB | Red | 20' | 3.00∙10^2 | 2.00∙10^2 | 1.00∙10^2 | -- | -- | --`, the same values as gold G-0029.
- **The unit of a requirement differs per table**, so the parser cannot fix it: R10 §6.9.1 is one requirement per pulse row; R150 Table 3 is one requirement for the whole red group (both divergence angles, every column); R150 Table A6-1 combines paragraph 3's sentence with the table (G-0053); G-0036 comes from the note under Table 3.
- Labels differ too: R150 cites `<para>. Table N`, R10 cites just `<para>` for its tables. Emit the table label with the **caption page**; the page is then right under both conventions.

### 2.6 Figures and equations

R150 has 18 image pages, of four kinds (viewed pages 3, 8, 32, 34, 50; the others identified from caption and image size):

| Kind | Pages | What it is | Binding numbers only in the image? |
|---|---|---|---|
| Annex 5 drawings, Figures A5-I…A5-X | 34-41 | shapes and dimensions of reflectors, marking, plates, triangles | yes, sometimes: A5-I has `150 mm ≤ A ≤ 200 mm`, `B ≥ A/5`, `C ≤ 15 mm` |
| Figure I | 8 | Unique Identifier mark with proportions and `a ≥ 8 mm` | yes; the text says only "follow the format in the example shown below" |
| Annex 4 geometry, A4-I…A4-III | 29-30 | CIE angle system, goniometer | no, explanatory |
| Annex 10 mark examples, A10-I…A10-V | 51-53 | approval mark layouts | no, informative |
| Equations as images (7, plus one inline symbol) | 3, 32, 50 | `R_I = I/E⊥`, `β = L/L₀`, `HS = 4/π · 25/D² · 10³ mm` | yes, but each is introduced in words ("results from the formula:") |
| Logo (not viewed) | 23 | one 96 x 96 pt image in the Annex 1 communication form, probably the approval mark | no |

**Contribution to the project goal**, measured on the dev gold:

- 0 of 190 gold requirement texts use figure content. One mentions a figure only by reference (R148 G-0212: "the pertinent light distribution figure reproduced in Annex 3").
- 2 of 121 gold-cited paragraphs contain a figure (R150 3.3.3.1 and R148 3.3.1.2, both the approval or UI mark). The R150 requirement (G-0004) reads "shall follow the format in the example shown below" and does not use the figure's content.
- Few paragraphs mention a figure at all: R150 18 of 513, R148 31/402, R48 3/1181, R10 42/815.
- Citations come from the text layer. Images do not change page numbers.

**Verdict: ignore image content in v1.** The graph and the citations lose nothing the gold rewards. The images are not purely decorative, though, so keep four cheap hedges:

1. Store `figure_refs` and `has_image` on each node, and put a `[formula image]` placeholder where an inline image sits.
2. Keep "see Figure X" in an obligation rather than inventing its numbers (this is what the gold does).
3. Show the cited PDF page as an image in the UI; that explains the regulation to a reader without parsing the figure.
4. Later, optional: vision on demand, only for selected nodes that reference a figure (2 in the dev case, about 3K tokens), formulas first.

For the sub-goal, hash the embedded images per version: R175's two images are byte-identical across versions (only the page moved, 11-12 to 13-14), so a changed figure would be detected without vision.

### 2.7 References, definitions, supersession

- Reference forms: plain `paragraph 5.1.4.` (most), `paragraph 3 of Part 1 of Annex 4`, `Part 1 of Annex 4, paragraphs 1.1. and 1.2.`, `paragraph 2.11. of UN Regulation No. 48`, and lists joined by `and`/`to`. A trailing dot belongs to the sentence.
- One regex finds 116 mentions in R150, 99 in R148, 343 in R48, 149 in R10. Plain targets that do not exist: R150 11 of 119 (9%), R148 8 of 99 (8%), R48 23 of 417 (6%), R10 1 of 171 (1%). Some dangle in the source itself (R150 `paragraph 5.9`, `5.7.6.1`, `3.2.3.2`, legacy numbering from the merged regulations), so a dangling target must not fail the build.
- §2 definitions are one `"term" means …` paragraph each, so DEFINES is a regex. R150 §2.1 imports R48's definitions, which is a cross-regulation edge.
- R150's introduction says it combines Nos. 3, 27, 69, 70 and 104. The proposal's table lists R3 and R104; R27, R69 and R70 are not in `regulations/index.json`, so nothing is lost. R48 6.4.2.3 itself says "type-approved … to UN Regulation No. 23, or … No. 148", so the installation-to-device links are in the text.

### 2.8 What the experts cite

- **Contiguous subtrees, chosen by device class or function.** R150: §3.3 markings, §4.1-4.2, §5.1 (Class IA/IB) but not 5.2/5.3; Annex 2, Annex 4 Part 1, Annex 5, Annex 6 Parts 1/2/4/6 but not 3/5; nothing from Annexes 1, 3, 7-11. R48: the four device sections for the lamp functions (6.4, 6.7, 6.10, 6.14) plus individual §5 items. Not cited: administrative paragraphs (3.1-3.2), transitional provisions, definitions, forms. Conformity of production is cited occasionally (R148 6.1.3, R150 Annex 2 1.2), so it cannot be skipped by scope.
- **Density.** If every shall/must node in the gold-touched subtrees were listed, node-level precision and recall would be:

| | R150 | R148 | R48 | R10 |
|---|---|---|---|---|
| precision | 26% | 44% | 49% | 27% |
| recall | 94% | 92% | 63% | 93% |

  The roots are depth-2 body sections or annex/part scopes, so the numbers depend on that granularity. The dilution is worst inside annexes (R150 Annex 5: 1 of 33 shall/must nodes; R10 Annex 9: 1 of 27). R48's low recall is the declarative style in 2.4.

  Without the shall/must gate the same subtrees hold 568 nodes, 121 of them cited (21%); 96 of the uncited ones are bare headings. `spec/precision.md` §3 sorts the rest into buckets with their match rates.

### 2.9 The sub-goal (R175, old 0.1.0 to new 1.0.0)

| Question | Result |
|---|---|
| Old requirements anchored on the old PDF | 94/94 found, 94/94 on the right page |
| Old nodes unchanged (label and text hash equal) | 179 of 195 (92%) |
| Of those, nodes whose start page changed | 158 of 179 (88%), so never diff by page |
| Changed old nodes | 15 modified, 1 moved; none removed at node level (the removed requirement is a sentence inside a restructured paragraph) |
| New nodes with no old counterpart | 34 ADDED: 8 hold the expected additions (a ninth label sits in a MODIFIED node, so all 17 expected additions are inside flagged nodes); 20 are definitions, scope, headings, tables or transitional provisions (droppable by rule); 6 need the judge (three paragraphs moved from old 5.1.4.1, 5.1.6.1 and 6.6, the continuation of old 6.5, and two new paragraphs the experts did not count) |
| Routing each old requirement by the status of its anchor node | 7 of 7 changed requirements flagged; review set 18 of 94; 11 of the 87 unchanged need the judge to clear them (nodes 5.1.4.1, 5.1.5, 5.1.6, 5.1.6.1, 6.5, whose text really was edited) |
| Old 6.5 (7 requirements: 3 modified, 1 removed, 3 unchanged) | split across new 6.5.1-6.5.5, 6.6, 6.6.1.x, 6.6.2.x; label matching cannot follow it |
| Insertions shift labels | old 5.1.4.1 is now 5.1.4.2 and old 6.6 is now 6.7; label-first matching pairs them with the wrong nodes (similarity 0.22 and 0.05) |
| `reason` from a word diff of the paragraph text | R-015 identical; R-018 same two clauses in the other order; R-021 first three clauses same, tail differs on list item (ii) |
| Figures | 2 per version, byte-identical |
| `source` in `expected.json` | page and paragraph in the **new** version for modified and added; none for removed |
| Scoring (README) | recall of the flagged requirements and accuracy of the stated change; a penalty for false flags is not mentioned |

## 3. Where the data disagrees with the proposal

| Proposal says | Data says | Change |
|---|---|---|
| Paragraph starts match `^\d+(\.\d+)*\.\s` | Headings come without the dot (R48 `5.7`, R148 `1 Scope`, R150 `6.1`, R10 many) | Accept dotless candidates if nested or styled |
| Sanity check: next child, sibling or ancestor's sibling, else log | Strict rule cascades on a gap or skipped level (R148 4/40, R48 23/35) | Longest increasing chain per scope; log the left-out lines |
| Detect `Annex N`, `Part N`, `Appendix N` | `Annex 2A`, `Annex 4 - Appendix 1` (also en dash), body `Appendix N`, `Part A:` | Use the regexes in the appendix; gate on bold/size |
| Strip E/ECE document IDs from headers | The footer is `UN R.., version .. \| page N of M` | One regex; page = physical = footer |
| Tables become child nodes, one per row | A row is not the unit; header may be on the previous page; `extract()` damages signs, spaces, exponents | Table node, grid from `find_tables()`, text from spans, split decided by the extractor |
| REFERS_TO from `paragraph 5.8.1` and `Annex 4, Part 1, paragraph 1.1` | Real forms differ (2.7); 1-9% of targets dangle | Extend the grammar, tolerate dangling, add `of UN Regulation No. M` |
| Pick the subtree, extract every obligation in it | Tree shape confirmed, but node-level precision is 26-49%; R48 obligations often have no modal verb | Applicability filter is the core step; never gate on shall/must |
| Match order: label and hash, hash, label, similarity | Insertions shift labels; old 6.5 splits | Hash, then similarity (0.8), then label, then similarity (0.5) |
| Count additions only in sections the old set covered | 26 of 34 ADDED nodes are not expected additions | Also drop definitions, scope-only text, headings, transitional provisions |
| Deterministic token diff for `reason` | Confirmed on 3 of 3 same-label modifications | Use it; the LLM only judges meaning |
| Page numbering unverified | Resolved | Remove the risk |
| An LLM-extracted knowledge graph is not needed | Confirmed: structure, labels, pages and references all come from the text | Keep |
| (not in the proposal) | A regulation fits in one prompt; the four dev ones are about 197K tokens together | Pitch the graph as exact grounding and cheap re-diffing, not as retrieval |

## 4. What to build, in order

**4.1 Ingest and parser health (first).** Run `python tools/fetch_regulations.py --out regulations/data` (92 files, 223 MB) and add `regulations/data/` to `.gitignore`. The links stop working after the event. Then run the parser over all of them and print per PDF: pages, nodes, nodes per page, left-out candidates (%), scope kinds, text before the first heading, footer N mismatches, table captions found against `Table` mentions, image pages (%). Look by eye at the outliers (left-out above 5%, fewer than 3 or more than 25 nodes per page, any mismatch, zero nodes). The held-out case will use regulations not seen so far.

**4.2 `parse.py`.** Two passes over `get_text("dict")` lines.

1. Drop footers. Detect scope headings gated on style: `Annex N[A-Z]?` and `Appendix N` (bold, ≥ 12.5 pt), `Annex N - Appendix M` (hyphen or en dash), `Part (A|N)[-–:]` (bold). A scope label is `Annex 4 [Appendix 1] [Part 1]`.
2. Collect candidates per scope: dotted `^(\d+(\.\d+)*)\.(\s|$)`, and dotless `^(\d+(\.\d+)*)\s+[A-Z]` (≤ 120 characters; nested or styled only).
3. Per scope, keep the longest strictly increasing chain (`best[i] = 1 + max(best[j]: num[j] < num[i])`, ties prefer dotted). Log the rest.
4. Build nodes: `kind` (annex, appendix, part, para, table), `label` (`<scope> <number>`), `num`, `heading`, `text` (lines joined; a line ending in `-` joins with no space), `text_hash` (normalised body without the number), `page_start/end`, `parent` (from the number prefix), `figure_refs`, `has_image`, and a line-to-page map so any quote resolves to a page.
5. Tables: caption `^Table\s+([A-Z]?\d+[a-z]?(-\d+)?)` (plain with a capitalised title, or bold alone). The owner is the nearest open ancestor paragraph whose own text names the table (Table A6-1 belongs to paragraph 3, not to the latest sub-item 3.2); the label is `<owner>. Table <id>`, the page is the caption page, the page range runs to the last row.

**4.3 `eval/anchors.py`: the gate.** Load the five anchor sets, compare with `_paragraph_key`, require 178/178, and print the diff of left-out lines for every parser change. Add the unlabelled health report from 4.1 to the same command.

**4.4 Graph store.** The proposal's tables plus `node.scope`, `node.kind`, `figure_refs`, `has_image`. Edges: parent (implicit), REFERS_TO (with a target regulation when `of UN Regulation No. M`), CITES_REG, DEFINES, IMPORTS_DEFINITIONS, SUPERSEDES (hand-written, checked against each new-series text), HAS_TABLE. A regulation card is its title, the §1 scope text and the generated depth-2 table of contents (about 1-3K tokens each).

**4.5 Tables.** Build a markdown grid per table node (header rows kept and repeated across pages, merged key cells filled, exponents as `^x`). Splitting into requirements is the extractor's job (2.5). Built as `Node.grid` in `src/regcomp/parse.py`, with raised digits instead of `^x` and the grid given to whichever node holds the text inside the table; what it does and where it stops is in `spec/testing/report.md` section 9.

**4.6 Obligations (LLM, batch).** Unit = one node's own text (children excluded) plus its breadcrumb, its table grid, and its figure notes. Do not filter by modal verb. Skip by scope only (Annex 1 communication forms, transitional provisions, §2 definitions apart from DEFINES edges) and let the model tag `kind` (design, performance, marking, installation, test-procedure, conformity, admin). Normalise declarative fields to "X shall Y" (R48). Verify each `quote` against the node text or the table grid (fuzzy ≥ 0.95) and take the page from the quote's offset. Ceiling check against the gold needs the local judge.

**4.7 Selection pipeline.** As the proposal's A4, with the data's structure used explicitly:

- Regulations: strict. Follow CITES_REG from installation to device regulations (R48 → R23/R148) and apply SUPERSEDES.
- R48-type regulations: choose device sections from the 28 by profile function, then apply the template children (Presence, Number, Position, Electrical connections…) with the vehicle category as the condition.
- R150/R148-type regulations: choose the class branch (IA/IB against the other classes) and the table group by colour or class.
- Annex test methods: choose the method that matches the product (R10 Annex 9 has 27 shall/must nodes and the gold cites 1).
- Applicability per obligation: keep when the match probability is above F2/5 (`spec/precision.md` §2, 4.3-4.5); drop by addressee, modality and profile facets, and rows for other colours or classes. Emit obligation ids only; fill regulation, base version, page, label from the store.

**4.8 `diff.py` (sub-goal), validated on R175.**

1. Parse both versions. Align nodes in this order: label and hash equal (SAME); hash equal and unique, 25+ characters (RENUMBERED); word similarity ≥ 0.8, greedy one-to-one (moved or modified); same label (modified); similarity ≥ 0.5; the rest REMOVED or ADDED.
2. Route each old requirement by the status of its anchor node (its `source` page and paragraph point into the old PDF). SAME or RENUMBERED: unchanged, no LLM.
3. For flagged requirements, take candidates from the new nodes in the same top-level section that are not SAME-matched to another old node (this catches the 6.5 split); an LLM judge returns unchanged, modified (with `new_text`) or removed.
4. Additions: obligations of ADDED or MODIFIED new nodes that match no old requirement, after dropping definitions, headings, scope-only text and transitional provisions.
5. `reason`: `Paragraph {new} (formerly {old}) of UN R{n} was amended in version {latest}: {clauses}.` with clauses `'a' became 'b'`, `'x' was added`, `'y' was removed` from a word diff. `source` is the new version's page and paragraph.
6. Check: `subgoal/dev/expected.json` (recall of the 24 changes, type accuracy, false flags among the 87).

**4.9 UI.** Render the cited page (`page.get_pixmap`), with the figure when there is one; the breadcrumb path; the coverage table; the change view with the word diff.

**4.10 Evaluation harness.** `eval/judge.py` approximates the platform's one-to-one requirement matching. Upload one dev file to calibrate it; the platform allows 5 uploads an hour per challenge.

**Not building now:** vision on figures, embeddings for alignment, a graph database, an LLM-extracted graph, per-row table nodes.

## 5. Not tested, and risks

- **5 of 56 regulations seen.** Other layouts may break a rule (4.1 is the cheap answer).
- **In-sample numbers.** R148, R48 and R10 rules were adapted after failures. R175 57/57 is the only hold-out, and R175 is a small, simple document.
- **Nothing LLM-based has been measured:** obligation extraction, the applicability filter, the sub-goal judge, requirement-level precision and recall. The node-level proxy in 2.8 is not a score.
- **Section choice has not been measured either.** Every precision figure here and in `spec/precision.md` uses the gold-touched subtrees, so the real figures will be lower.
- **Table conventions in the gold are inconsistent** (2.5); the caption-page rule is a hedge, not a certainty.
- **Sub-goal scoring:** whether false flags are penalised is not stated.
- **Figures:** binding numbers in images (R150 A5-I, Figure I, three equation pages; R148 Annex 3 light distributions) are lost in v1. The dev gold does not need them; the held-out case might.
- **Tables:** `find_tables()` reads ruled tables only. Over the 92 PDFs 98% of the captioned tables got a grid; the rest are drawn as images, or have only horizontal rules, or sit on a dense page (`spec/testing/report.md` section 9.4).
- **Footer format** is assumed constant across the corpus (true for the six files checked).

## Appendix: the regexes in one place

```
footer      ^UN (?:R|GTR )\d+[A-Z]?, version [\d.]+ \| page (\d+) of (\d+)$
annex       ^Annex\s+(\d+[A-Z]?)\b                          bold, size >= 12.5
annex-app.  ^Annex\s+(\d+[A-Z]?)\s*[-–]\s*Appendix\s+(\d+)\b  bold, size >= 12.5   (test before annex)
appendix    ^Appendix\s+(\d+)\b                             bold, size >= 12.5
part        ^Part\s+([A-Z]|\d+)\s*[-–:]                     bold, inside an annex or appendix
dotted      ^(\d+(?:\.\d+)*)\.(?:\s+|$)
dotless     ^(\d+(?:\.\d+)*)\s+(?=[A-Z])                    <= 120 chars; depth >= 2 or bold/size >= 12
table       ^Table\s+([A-Z]?\d+[a-z]?(?:-\d+)?)(?:\s+(?=[A-Z])|\s*$)   plain with title, or bold alone
reference   \bparagraphs?\s+(\d+(?:\.\d+)*)\.?((?:\s*(?:,|and|or|to)\s*\d+(?:\.\d+)*\.?)*)
            (\s+of\s+(?:Part\s+\d+\s+of\s+)?Annex\s+\d+|\s+of\s+(?:this\s+)?UN\s+Regulation\s+No\.?\s*\d+)?
```
