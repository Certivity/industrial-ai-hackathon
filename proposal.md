# Proposal: grounded regulation index and versioned requirement mapping

Status: revised v3, 2026-10-24. Merged with the data exploration in `spec/finding/finding.md` (parser prototype: 215/215 anchors). B4/B5/propagate.py dropped; FastAPI replaces Streamlit; phased checklist split into two workstreams.

## Context

The brief (`artifact/certivity-challenge-brief.pdf`) asks for an agent that takes a product spec and/or exploded view and returns atomic engineering requirements. Each requirement must cite a UN Regulation from `regulations/index.json`, with its **base** version label and the page. The paragraph is optional, and a citation counts if either the page or the paragraph is right. Scoring uses F2, which weights recall above precision. The optional sub-goal: given requirements derived from an old version of a regulation and a newer version, flag which requirements are modified, removed or added, and say why.

This design addresses two problems:

1. **Indexing the regulations** so the agent finds the right paragraph and where it sits in the document. Citations must be correct, and when nothing applies the system must say so instead of inventing a citation.
2. **Handling change.** When a regulation gets a new version, say which requirements change and why (the sub-goal). Re-parsing specs and adding regulations to a live system are out of scope for the hackathon.

## What the data tells us

- **The gold set is tree-shaped.** The rear-lamp gold has 190 requirements from only 4 regulations: R148 (63), R48 (56), R150 (39) and R10 (32). They sit in contiguous sections: R48 §5.x general, §6.4 reversing, §6.7 stop, §6.10 rear position, §6.14 retro-reflector; R150 §3.3 markings, §4–5, Annexes 2/4/5/6. The right approach is to pick the relevant subtrees, not to retrieve top-k chunks. A subtree is not the answer, though: listing every shall/must node in the gold-touched subtrees gives only 26–49% node-level precision (finding.md §2.8), so the applicability filter, not the subtree choice, decides precision.
- **Picking regulations by title gives false positives.** The spec mentions a reversing lamp, position/stop lamps and a retro-reflector, but the gold does **not** cite R23, R7 or R3. It cites the newer consolidated **R148/R150** instead. R48 itself says "type-approved to R7 *or* R148" (G-0087), so cross-regulation references help find candidates, but the final choice needs a supersession rule. R10 (electromagnetic compatibility) is in the gold because "LED modules on PCB" makes the lamp an electronic sub-assembly (ESA). Materials and electronics can pull in whole regulations.
- **One obligation per requirement.** A single paragraph can yield up to 10 requirements: R10 §6.9.1 is split into one per table row (pulse 1/2a/2b/3a/3b). The text is rewritten as a standalone "X shall Y [while/when/where Z]". The gold IDs have 44 gaps, which suggests rows that don't apply were dropped. For example, only the **red** row of R150 Table 3 appears, because the lens is red. So applicability is decided down to the table row.
- **Paragraph labels have a fixed format.** Examples: `5.1.4.4.1. Table 3`, `Annex 4 Part 1 1.2`, `Annex 6 Part 6 3. Table A6-1`. `tools/score_local.py::_paragraph_key` normalizes them. The platform scores pages against each gold paragraph's **full page range**.
- **The main goal leaves out admin obligations.** In the dev gold, R150 requirements start at §3.3 (markings). Approval-application paperwork is left out; test-procedure parameters (saline mist, ISO 4892 exposure) are kept.
- **The sub-goal is a paragraph diff.** `subgoal/dev` is UN R175: `old.pdf` and `new.pdf` have the same sha256 as R175 base and latest. Of 94 old requirements, 6 are modified, 1 is removed, and 17 requirements are added. The reasons read like a word diff ("'standstill.' became '…while creeping.'; 'both' was added"). Paragraphs get renumbered ("6.5.2 (formerly 6.5)"). Added items are counted per obligation: §6.6.2.2 alone gives 5 added requirements. The main risk is wrongly flagging the 87 unchanged requirements.

## What the parser prototype showed (finding.md)

- **The structural graph holds.** A deterministic PyMuPDF parser, no LLM, put 215 of 215 expert anchors on the right node and page (R150 31, R148 40, R48 35, R10 15, R175 94). Caveat: the rules were adapted on R150, R148 and R48 after they failed, so those are in-sample. R175 ran with frozen rules and is the only hold-out. Only 5 of 56 regulations have been seen.
- **Page numbering is resolved.** Gold `page` = physical PDF page = the footer `UN R150, version 1.2.1 | page 7 of 54`. The PDFs have no table of contents, no bookmarks, no page labels.
- **Numbering is dirty.** Dotless headings (`5.7 …`, `1 Scope`), table cells and figure legends that look like paragraphs, real gaps. A successor rule fails (R148 4/40, R48 23/35). The longest strictly increasing chain per scope works.
- **Tables are not rows.** One node per table; build cell text from spans inside `find_tables()` rectangles. `Table.extract()` loses spaces, fuses exponents and moves signs.
- **R48 is declarative.** 13 of 35 gold-cited R48 nodes have no shall/must/should, so never gate on modal verbs. R48 §6 is a template of 28 device sections with the same children in the same order.
- **Figures can be ignored in v1.** 0 of 190 gold requirements use figure content. Keep `figure_refs` / `has_image` and show the page image in the UI.
- **A whole regulation fits in one prompt** (the four dev ones are about 197K tokens together). The graph is for exact grounding and cheap re-diffing, not for retrieval.
- **The sub-goal is mostly deterministic.** 92% of old nodes are unchanged by hash; routing old requirements by their anchor node flagged 7 of 7 changed requirements in a review set of 18 of 94.

## Core idea

- **A structural graph, not an LLM-extracted knowledge graph.** Build a deterministic, versioned graph for each regulation version from the document's own structure.
  - Nodes are annexes/parts, paragraphs and tables (a table is one node, not one node per row). Each has an exact page range, a breadcrumb path and a content hash.
  - Edges are parent/child, cross-references, citations of other regulations, definitions and supersession.
  - An LLM-extracted knowledge graph would be harder to keep exact, harder to update, and adds nothing here.
- **The LLM never writes a location.** It selects and rewrites, but never produces a page or paragraph number. Every output requirement points to an `obligation_id` that exists in the store, and the citation is filled in from there.
- **Cache by hash.** Obligations are keyed by the node's `text_hash`. The same hash across two versions means no recomputation and no "change". This is what makes the sub-goal mostly deterministic.

---

## Part A: index and grounded retrieval

### A1. Parse each PDF into a node tree

Use PyMuPDF (`get_text("dict")` lines with font, size and bold flags). Two passes; the regexes are in finding.md §4.2 and its appendix.

- **Footer.** Every page ends `UN R150, version 1.2.1 | page 7 of 54`. One regex strips it; N is the physical page and the gold page.
- **Scopes first.** Numbering restarts inside every annex, part and appendix, so detect scope headings before paragraphs: `Annex N[A-Z]` (bold, ≥12.5 pt), `Annex N - Appendix M` (hyphen or en dash; test before plain annex), body `Appendix N`, `Part A|N` (bold). A label is `<scope> <number>`, e.g. `Annex 4 Part 1 1.2`.
- **Candidates.** Dotted `^\d+(\.\d+)*\.` and dotless `^\d+(\.\d+)*\s+[A-Z]` (≤120 chars, only if nested to depth ≥2 or bold/≥12 pt; without that rule figure legends get in).
- **Longest strictly increasing chain per scope** (tuple order, O(n²)), not a successor check. Log every left-out line.
- **What each node stores:** `kind`, `label`, `num`, `heading`, `scope`, a `path` breadcrumb (e.g. `R48 › 6 › 6.10 Rear position lamps › 6.10.4.2`), `text` (a line ending in `-` joins without a space) and `text_hash` (normalised, number removed), `page_start..page_end`, a line→page map so any quoted span resolves to its page, `figure_refs`, `has_image`. List items (a), (i) stay inside their paragraph.
- **Tables.** One node per captioned table (`^Table\s+([A-Z]?\d+[a-z]?(-\d+)?)`, plain with a title, or bold alone). The owner is the nearest open ancestor paragraph whose own text names the table; label `<owner>. Table <id>`; page = caption page; range runs to the last row. Grid: cell rectangles from `find_tables()`, cell text from the spans inside each rectangle, superscripts as `^x`, merged key cells forward-filled. Never `Table.extract()`. Splitting a table into requirements is the extractor's job.
- **Figures.** Ignore image content in v1. Keep `figure_refs` and `has_image`, and put a `[formula image]` placeholder where an inline image sits.
- **Gate (`eval/anchors.py`).** The 215 anchors (121 rear-lamp gold anchors across R150 31, R148 40, R48 35, R10 15, plus 94 R175 `requirements_old`; per finding.md §1) must all resolve: a node with the same label under `tools/score_local.py::_paragraph_key`, and the gold page inside that node's range. Print the left-out lines after every parser change. A health report over every PDF (A1 health, Phase 1) is the check for unseen regulations.

### A2. Edges

- `REFERS_TO`: one regex for the real forms: `paragraph 5.1.4.`, `paragraph 3 of Part 1 of Annex 4`, `Part 1 of Annex 4, paragraphs 1.1. and 1.2.`, `paragraph 2.11. of UN Regulation No. 48`, lists joined by and/or/to. A trailing dot belongs to the sentence. 1–9% of targets dangle in the source itself (legacy numbering), so a dangling target must not fail the build.
- `CITES_REG`: "UN Regulation No. 48". R48 6.4.2.3 itself says "type-approved … to UN Regulation No. 23, or … No. 148", so installation→device links are in the text.
- `DEFINES`: from §2, one `"term" means …` paragraph each. `IMPORTS_DEFINITIONS`: R150 §2.1 imports R48's definitions. `HAS_TABLE`: paragraph → table node.
- `SUPERSEDES`: a small hand-written table, checked against each regulation's own text:
  - R148 replaces R6, R7, R23, R38 (lamps);
  - R149 replaces R19, R123;
  - R150 replaces R3, R104 (its introduction also names Nos. 27, 69, 70, which are not in `regulations/index.json`, so nothing is lost).
- **Regulation card** for step A4.2: title, §1 scope text and a generated depth-2 table of contents (about 1–3K tokens). The PDFs contain no ToC, so it is built from headings. Per-node LLM summaries are only added if the heading-only ToC proves too thin.

### A3. Obligation layer

Obligations depend only on the node text, not on the product. Cache them by `text_hash`.

- **Unit.** One node's own text (children excluded) plus its breadcrumb, its table grid and its figure notes. The LLM splits it into atomic obligations in the gold style.
- **Never filter by modal verb.** R48 states many obligations declaratively (`In height: not less than 250 mm and not more than 1,200 mm above the ground.`); the gold rewrites them as "The height of the lamp shall be …" and may split one paragraph into three. Skip by scope only: Annex 1 communication forms, transitional provisions, §2 definitions (kept as DEFINES edges).
- **Fields:** `text`, `quote` (the verbatim source span), `condition`, `subject`, and `kind`, one of {design, performance, marking, installation, test-procedure, conformity-of-production, admin}.
- **Check in code.** `quote` must be a fuzzy (≥0.95) substring of the node text **or of the table grid**, otherwise reject and retry once. `page` comes from the quote's offset (for a table, the caption page).
- **Tables.** The unit differs per table: R10 §6.9.1 is one requirement per pulse row; R150 Table 3 is one for the whole red group; Table A6-1 combines paragraph 3's sentence with the table. The extractor decides the split.
- **When to run it (decision gate in Phase 3).** Measure the corpus with `count_tokens`. If affordable, Batch-extract every base version overnight. Otherwise extract on demand for the regulations and sections the pipeline selects (a case touches about 4–6 regulations, about 200K tokens), with parallel calls, and cache the results.

### A4. Pipeline for one spec

This is a workflow with fixed steps. The LLM makes the decisions inside each step.

1. **Profile.** spec.md plus a vision pass over the exploded view → parts, functions, vehicle category, colours, materials and electronics (LED/PCB → ESA). Each item gets a stable key.
2. **Pick regulations.** The LLM reads a card per regulation (title, §1 scope, short table of contents) against the profile.
   - It follows `CITES_REG` from installation regulations to device regulations (R48 → R148).
   - It applies `SUPERSEDES` to prefer R148/R149/R150 over the older regulations.
   - Be **strict** here, because a wrong regulation drags in dozens of false requirements.
3. **Pick sections.** The LLM walks the generated depth-2 table of contents once per profile item, and is **inclusive**. Use the structure explicitly:
   - R48-type regulations: pick the device sections from the 28 in §6 by function, then apply the template children (Presence, Number, Arrangement, Position, Geometric visibility, Orientation, Electrical connections, Tell-tale, Other) with the vehicle category as the condition.
   - R150/R148-type: pick the class branch (IA/IB against the other classes) and the table group by colour or class.
   - Annex test methods: pick the method that matches the product (R10 Annex 9 has 27 shall/must nodes; the gold cites 1).
   - BM25 over FTS5 is a safety net: hits outside the chosen sections go back to the LLM. No embeddings.
4. **List** every obligation in the chosen subtrees. This step is deterministic and uses no LLM.
5. **Check applicability** of each obligation against the profile. This is the core step: it decides precision.
   - Run in batches, with the profile and instructions cached.
   - Drop `admin` obligations, and drop table rows for other colours or classes. Do not drop by scope alone: conformity of production is cited occasionally (R148 6.1.3, R150 Annex 2 1.2).
   - Never gate on shall/must.
   - When in doubt, keep it (F2 rewards recall). Tune the keep threshold on the dev case, because node-level precision before this step is only 26–49%.
6. **Verify and emit.** Fill in regulation, version (base), page and label from the store, then validate with `tools/validate.py`.

### A5. Free-form agent variant (not building)

Give the agent tools instead of the raw graph:

- `list_regulations`
- `get_toc(reg, path, depth)`
- `read_node(id)`
- `search(q, reg?)`
- `follow_refs(id)`
- `get_obligations(id)`
- `submit(obligation_id, rationale)`, which rejects unknown IDs

The agent still walks the graph, but it cannot invent a location.

### A6. Three kinds of error, three policies

- **A wrong or made-up citation** cannot happen by construction: outputs are IDs only, and every quote is verified.
- **A real obligation that doesn't apply** costs a little precision. Because F2 rewards recall, be inclusive inside the regulations you selected.
- **No coverage.** The demo shows a coverage table with every profile item. Items with no match above the threshold show "no applicable provision found in indexed regulations (searched: …)", and nothing is emitted for them.

## Part B: versioning and change propagation

### B1. Never edit nodes in place

A new regulation version is a new set of nodes. Alignment edges link the two versions:

| Edge | Meaning |
|---|---|
| `SAME` | same hash |
| `RENUMBERED` | same hash, new label |
| `MODIFIED` | same label (or a similarity match above the threshold), different hash |
| `REMOVED` | old node has no match |
| `ADDED` | new node has no match |

Matching order (finding.md §4.8):

1. label and hash equal → `SAME`;
2. hash equal and unique, ≥25 characters → `RENUMBERED`;
3. word-level similarity ≥0.8, greedy one-to-one → moved or modified;
4. same label → `MODIFIED`;
5. similarity ≥0.5;
6. the rest → `REMOVED` / `ADDED`.

Label-first matching is wrong here: insertions shift labels (old 5.1.4.1 is now 5.1.4.2, old 6.6 is now 6.7; label-first pairs them with similarity 0.22 and 0.05) and old 6.5 splits across new 6.5.1–6.6.2.x. No embeddings and no Hungarian assignment. Never diff by page: 88% of unchanged nodes changed page.

### B2. Provenance

> **Out of scope for this hackathon.** Only `obligation.node_text_hash` and `extractor_version` are kept, for caching.

### B3. Trigger: a regulation gets a new version (this is the sub-goal)

Mostly deterministic: on R175, 179 of 195 old nodes are unchanged by hash.

1. Parse both versions and align the nodes (B1).
2. **Route each old requirement by the status of its anchor node.** Its `source` page and paragraph point into the old PDF. `SAME` / `RENUMBERED` → unchanged, no LLM. On R175 this flags all 7 changed requirements in a review set of 18 of 94; 11 of the 87 unchanged still need the judge to clear them.
3. **Judge the flagged requirements.** Candidates are the new nodes in the same top-level section that are not `SAME`-matched to another old node (this catches the 6.5 split). An LLM judge returns unchanged, modified (with `new_text`) or removed, using the word diff as evidence.
4. **Additions.** Obligations of `ADDED` or `MODIFIED` new nodes that match no old requirement, after dropping definitions, headings, scope-only text, tables of contents and transitional provisions (26 of 34 `ADDED` nodes are not expected additions).
5. **Reason text.** Build `reason` from a deterministic word diff in the gold format (`Paragraph {new} (formerly {old}) of UN R{n} was amended in version {latest}: 'a' became 'b'; 'c' was added.`). `source` is the **new** version's page and paragraph (none for removed). `new_text` is the old requirement rewritten with the change.
6. **Figures.** Hash the embedded images per version; a changed figure is detected without vision.
7. Whether false flags are penalised is not stated in the README, so keep the unchanged requirements unflagged.

### B4. Trigger: a spec is re-parsed

> **Out of scope for this hackathon.**

### B5. Trigger: a new regulation is added to the database

> **Out of scope for this hackathon.**

## Storage

One SQLite file. Parent/child comes from `parent_id` and recursive CTEs; no NetworkX, no graph database, no vector store (about 55 regulations × 2 versions).

| Table | Columns |
|---|---|
| `doc` | reg, version, role, sha256, pages |
| `node` | id, reg, version, kind, scope, label, num, path, heading, text, text_hash, parent_id, ord, page_start, page_end, figure_refs, has_image, table_grid |
| `edge` | src, dst, kind (REFERS_TO, CITES_REG, DEFINES, IMPORTS_DEFINITIONS, SUPERSEDES, HAS_TABLE) |
| `node_fts` | FTS5 over node text |
| `obligation` | id, node_id, ordinal, text, quote, page, kind, condition, node_text_hash, extractor_version |
| `align` | old_node, new_node, kind, sim |

## LLM usage (Claude API, Python SDK)

- **Model.** Model IDs come from environment variables (one for bulk extraction, one for selection/judging), not hard-coded. Verify the IDs against the models list in Phase 0; they are not verified in this document.
- **Bulk extraction (A3)**, if the Phase 3 cost gate says to pre-extract, goes through the Message Batches API (cheaper, asynchronous). Otherwise it runs on demand with parallel calls. Measure tokens with `count_tokens` first and use a cheaper tier if quality holds on the dev anchors.
- **Structured outputs** for obligations, selections and diffs. The schema includes `quote`, which is verified in code.
- **Citations API (alternative).** Claude's native Citations feature can return the exact paragraph cited, if each paragraph is passed as its own content block. That fits the demo's explanation text. It can't be combined with structured outputs, so it is not the main path.
- **Prompt caching** for the shared system prompt and the product profile across the many applicability calls.
- **Vision input** for `exploded_view.png`.

## Code layout

New code:

```
src/regcomp/
  parse.py        # A1  PDF → nodes, tables, footers (PyMuPDF)
  graph.py        # A2  SQLite store, edges, supersession, regulation cards
  obligations.py  # A3  extraction + quote verification
  profile.py      # A4.1 spec + vision → profile
  pipeline.py     # A4.2–6 selection, filtering, emit main-goal JSON
  diff.py         # B1/B3 alignment, routing, judge, reason text → sub-goal JSON
src/backend/
  main.py         # FastAPI: POST /analyze, GET /changes, GET /page/{reg}/{n}.png
src/frontend/
  index.html      # single page: requirements table, page image, coverage, change view
eval/
  anchors.py      # parser gate (215 anchors) + health report over all PDFs
  judge.py        # optional: LLM 1:1 matcher approximating the platform (Phase 4)
```

`src/backend/main.py` and `src/frontend/` already exist in the repo (empty), so the UI goes there instead of `src/api/`. Dropped: `propagate.py` (B4/B5 out of scope).

## Build phases

Held-out case releases Sunday 08:00; uploads close 13:00; 5 uploads/hour. **For the held-out case, the last valid upload counts — do not upload unless it is better than the previous.**

---

Two people. **P1 = parser/graph/diff/UI (SWE-leaning). P2 = LLM steps: obligations, profile, pipeline (AI-leaning).** P2 can write prompts and the selection logic against the parser's output schema while P1 finishes the parser; agree the `node` schema first.

### Phase 0 — Setup (both)

- [x] Page numbering verified: gold `page` = physical PDF page = footer `page N of M` (finding.md §2.1). No offset.
- [ ] Download every PDF while the links work: `python tools/fetch_regulations.py` (92 files, 223 MB, base and latest; the earlier `--role base` run only fetched the base versions into `regulations/pdf/`). `**/pdf/` is already git-ignored; if you use `--out regulations/data` as finding.md did, add `regulations/data/` to `.gitignore`. Pick one folder and tell both people.
- [ ] Commit the prototype parser and the experiment scripts from finding.md (they live in a temporary scratchpad) into `src/regcomp/` and `eval/`. Do not rewrite from scratch.
- [ ] `pip install pymupdf anthropic fastapi uvicorn jsonschema` (no networkx, no sqlite-vec).
- [ ] Set the Anthropic key and put the model IDs in env vars (one bulk, one reasoning). Make one test call per ID; the IDs are not verified in this document.
- [ ] `python tools/score_local.py cases/dev-rear-lamp/expected.json` scores 100% against itself.
- [ ] Agree the `node` and `obligation` schemas (Storage section) so P1 and P2 can work in parallel.

---

### Phase 1 — Parser health on the whole corpus (P1)

The 215/215 result is on 5 of 56 regulations, and four of those were used to tune the rules. The held-out case will use regulations nobody has parsed. This phase is the cheap answer.

- [ ] Run the parser over all 92 PDFs. Print per PDF: pages, nodes, nodes per page, left-out candidates (%), scope kinds, text before the first heading, footer-N mismatches, table captions found against `Table` mentions, image pages (%).
- [ ] Inspect by eye the outliers: left-out above 5%, fewer than 3 or more than 25 nodes per page, any footer mismatch, zero nodes. Fix the rule, rerun, repeat; stop when outliers are explained.
- [ ] Implement the table grid (finding.md §4.5): `find_tables()` rectangles, cell text from spans, superscripts as `^x`, merged key cells forward-filled. Check R150 Table 3, Table A6-1 and R10 §6.9.1 against the gold texts. Check one R48 table: `find_tables()` was only validated on ruled tables.
- [ ] `eval/anchors.py`: all 215 anchors resolve under `_paragraph_key` with the gold page inside the node's range. Run it after every parser change.
- [ ] `graph.py`: SQLite store, edges (`REFERS_TO` with the extended grammar, `CITES_REG`, `DEFINES`, `IMPORTS_DEFINITIONS`, `HAS_TABLE`), `SUPERSEDES` table, regulation cards (title + §1 + depth-2 ToC). Dangling references must not fail the build.
- [ ] Check `SUPERSEDES` against the text of R148, R149 and R150 (finding.md §2.7 already confirms R148 and R150; R149 is unchecked).
- [ ] Parse R175 `latest` into the store as well (no anchors exist for it; check node count and footer N only), since Phase 4 needs it.

---

### Phase 2 — Obligation extraction (P2)

- [ ] `obligations.py`: unit = one node's own text + breadcrumb + table grid + figure notes. Structured output (`text`, `quote`, `condition`, `subject`, `kind`). No modal-verb filter; skip by scope only (Annex 1 forms, transitional provisions, §2 definitions).
- [ ] Prompt rules: rewrite declaratives as "X shall Y" (R48 `In height: not less than 250 mm…`); one obligation per requirement; keep "see Figure X" instead of inventing numbers.
- [ ] Verify `quote` is a fuzzy ≥0.95 substring of the node text or the table grid; reject and retry once. Page from the quote's offset, never from the LLM.
- [ ] Dry run on the nodes of R48 §6.4 and R150 §3.3. Read the output against the gold requirements for those paragraphs. Count obligations per paragraph (gold: 1.26 R150, 1.58 R148, 1.60 R48, 2.13 R10).
- [ ] **Cost gate:** `count_tokens` over all base versions. Decide: batch-extract everything overnight, or extract on demand per selected regulation and cache by `text_hash`. Record the decision here: ______
- [ ] Run extraction for the four dev regulations (R150, R148, R48, R10) first, then for the rest if the gate says so.
- [ ] Log the rejection rate; spot-check 10 obligations against the source text.

---

### Phase 3 — Main pipeline and first submission (P2, P1 helps)

- [ ] `profile.py`: `spec.md` + `exploded_view.png` (vision) → structured profile (parts, functions, vehicle category M1, colours, materials, electronics → ESA flag).
- [ ] Regulation picker: LLM reads a card per regulation against the profile; applies `SUPERSEDES`; follows `CITES_REG` from installation to device regulations. Strict. The dev case must end on R48, R148, R150, R10 and not on R3, R7, R23.
- [ ] Section picker: depth-2 ToC walk, inclusive, using the structure (R48 device sections + template children, R150/R148 class branch and colour group, matching annex test method). FTS5 safety net.
- [ ] Obligation list from the chosen subtrees (deterministic).
- [ ] Applicability filter: batched, cached prompt; drop `admin` and rows for other colours/classes; keep when in doubt. Log node-level precision before and after the filter.
- [ ] Emit: regulation, **base** version label, page, paragraph from the store; one ID per requirement; `python tools/validate.py` passes.
- [ ] `python tools/score_local.py out.json` on the dev case. Record regulation-level and page-level scores here: ______
- [ ] Upload once. Compare with the local score. Note the platform's requirement-level result here: ______
- [ ] Iterate on the picker and the filter while the gain per iteration stays above about 5%. Uploads are limited to 5 per hour per challenge, so do not use them as a debugger.
- [ ] Optional, if time remains: `eval/judge.py` (LLM one-to-one matcher) to measure requirement-level precision and recall locally. Otherwise use the platform score.

---

### Phase 4 — Sub-goal diff (P1, can start as soon as Phase 1 parses R175 latest; independent of Phases 2–3)

- [ ] `diff.py` alignment in the order of B1 (hash+label, unique hash ≥25 chars, similarity ≥0.8 greedy, same label, similarity ≥0.5, rest). Check on R175: 179 of 195 old nodes SAME, 15 modified, 1 moved, 34 ADDED.
- [ ] Route each old requirement by its anchor node's status (`requirements_old.json` `source`). Expect 18 of 94 flagged, containing all 7 changed requirements.
- [ ] Judge step (P2 writes the prompt): for flagged requirements, candidates = unmatched new nodes in the same top-level section; return unchanged / modified (with `new_text`) / removed. The 11 unchanged-but-edited requirements (5.1.4.1, 5.1.5, 5.1.6, 5.1.6.1, 6.5) are the test of this step.
- [ ] Additions: obligations of ADDED/MODIFIED new nodes matching no old requirement, after dropping definitions, headings, scope-only text, transitional provisions.
- [ ] `reason` from the word diff in the gold format; `source` = new version's page and paragraph.
- [ ] Emit JSON; `python tools/validate.py my_changes.json --requirements-old subgoal/dev/requirements_old.json`.
- [ ] Compare with `subgoal/dev/expected.json`: recall of the 24 changes, type accuracy, false flags among the 87. Record: ______
- [ ] Upload once.

---

### Phase 5 — Minimal UI (P1, starts once Phase 3 emits a file)

- [ ] `src/backend/main.py` (exists, empty): `POST /analyze` (spec → requirements JSON), `GET /changes` (sub-goal JSON), `GET /page/{reg}/{n}.png` (`page.get_pixmap`).
- [ ] `src/frontend/index.html`: requirements table (regulation, paragraph, page, text, breadcrumb) with the cited page image beside it; coverage table, one row per profile item, "no applicable provision found" where nothing matched; change view with the word diff.
- [ ] End-to-end on the dev spec. Open 10 random citations and confirm the quoted text is on the page.
- [ ] Pitch material: stage-wise numbers (regulations chosen, node-level precision before/after the filter, requirement-level score).

---

### Sunday contingency (08:00–13:00)

- [ ] `git pull` to get the held-out case; `python tools/fetch_regulations.py` again (it downloads the new PDFs).
- [ ] Run the Phase 1 health report on any regulation not seen before; fix outliers.
- [ ] Extract obligations for the regulations the pipeline selects (on demand, parallel, cached).
- [ ] Run the pipeline on the held-out spec. `validate.py`. Upload.
- [ ] Use remaining upload slots only for changes you believe are better. **The last valid upload counts, not the best.**

## Verification

- **Parser (Phase 1):** 215/215 anchors via `python eval/anchors.py`, plus the corpus health report with no unexplained outliers.
- **Stage-wise recall on the dev case (Phase 3).** Shows where the pipeline is weak, which is useful for the pitch.
  - Regulation level: `python tools/score_local.py out.json` (expect R48, R148, R150, R10; nothing else).
  - Section recall: share of gold paragraphs inside the chosen subtrees.
  - Obligation ceiling: share of gold requirements matched by any extracted obligation in those subtrees.
  - Node-level precision before and after the applicability filter (26–49% before, per finding.md).
  - Requirement-level score: on the platform after upload (or `eval/judge.py` if built).
- **Grounding audit:** 100% of emitted requirements pass quote verification in code; 10 random citations opened by hand.
- **Sub-goal (Phase 4):** compare with `subgoal/dev/expected.json`: recall of the 24 changes, change-type accuracy, false flags among the 87 unchanged.
- **Before every upload:** `python tools/validate.py submission.json` — a file that fails here will be rejected by the platform.

## Risks and assumptions

- **Parser generality.** 5 of 56 regulations seen; R150, R148, R48 and R10 are in-sample. R175 (94/94, frozen rules) is the only hold-out, and it is small and simple. Mitigation: Phase 1 corpus health report.
- **Nothing LLM-based has been measured yet:** obligation extraction, the applicability filter, the sub-goal judge, requirement-level precision and recall. The node-level proxy is not a score.
- **Precision/recall policy.** The scorer is F2 (recall-weighted); the team leans 60/40 toward precision. Decision: be strict at regulation level and inclusive within selected sections, then tune the applicability threshold on the dev case and the first platform score, not by instinct.
- **Table conventions in the gold are inconsistent** (R150 cites `<para>. Table N`, R10 cites just `<para>`). Emitting the caption page with the table label is a hedge, not a certainty. `find_tables()` was validated on ruled tables only; R48 tables are unchecked.
- **Figures:** binding numbers in images (R150 A5-I, Figure I, three equation pages; R148 Annex 3) are lost in v1. The dev gold does not need them; the held-out case might.
- **Overfitting.** One dev case. Keep selection rules generic (supersession, dropping `admin`, filtering table rows by colour/class). Do not hard-code R48/R148/R150/R10.
- **Sub-goal scoring:** false-flag penalty is not stated in the README.
- **Footer format** is assumed constant across the corpus (true for the six files checked); the health report tests it.
- **Stack.** Python + Anthropic API + FastAPI. Model IDs unverified until Phase 0.
