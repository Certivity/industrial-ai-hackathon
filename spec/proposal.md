# Proposal: grounded regulation index and versioned requirement mapping

Status: proposal, 2026-10-24

## Context

The brief (`artifact/certivity-challenge-brief.pdf`) asks for an agent that takes a product spec and/or exploded view and returns atomic engineering requirements. Each requirement must cite a UN Regulation from `regulations/index.json`, with its **base** version label and the page. The paragraph is optional, and a citation counts if either the page or the paragraph is right. Scoring uses F2, which weights recall above precision. The optional sub-goal: given requirements derived from an old version of a regulation and a newer version, flag which requirements are modified, removed or added, and say why.

This design addresses two problems:

1. **Indexing the regulations** so the agent finds the right paragraph and where it sits in the document. Citations must be correct, and when nothing applies the system must say so instead of inventing a citation.
2. **Handling change.** When a regulation gets a new version, a spec is re-parsed, or a new regulation is added, the requirement↔spec mappings must be updated, marked stale or removed, and new material must be mapped.

## What the data tells us

- **The gold set is tree-shaped.** The rear-lamp gold has 190 requirements from only 4 regulations: R148 (63), R48 (56), R150 (39) and R10 (32). They sit in contiguous sections: R48 §5.x general, §6.4 reversing, §6.7 stop, §6.10 rear position, §6.14 retro-reflector; R150 §3.3 markings, §4–5, Annexes 2/4/5/6. The right approach is to pick the relevant subtree and extract every obligation in it, not to retrieve top-k chunks.
- **Picking regulations by title gives false positives.** The spec mentions a reversing lamp, position/stop lamps and a retro-reflector, but the gold does **not** cite R23, R7 or R3. It cites the newer consolidated **R148/R150** instead. R48 itself says "type-approved to R7 *or* R148" (G-0087), so cross-regulation references help find candidates, but the final choice needs a supersession rule. R10 (electromagnetic compatibility) is in the gold because "LED modules on PCB" makes the lamp an electronic sub-assembly (ESA). Materials and electronics can pull in whole regulations.
- **One obligation per requirement.** A single paragraph can yield up to 10 requirements: R10 §6.9.1 is split into one per table row (pulse 1/2a/2b/3a/3b). The text is rewritten as a standalone "X shall Y [while/when/where Z]". The gold IDs have 44 gaps, which suggests rows that don't apply were dropped. For example, only the **red** row of R150 Table 3 appears, because the lens is red. So applicability is decided down to the table row.
- **Paragraph labels have a fixed format.** Examples: `5.1.4.4.1. Table 3`, `Annex 4 Part 1 1.2`, `Annex 6 Part 6 3. Table A6-1`. `tools/score_local.py::_paragraph_key` normalizes them. The platform scores pages against each gold paragraph's **full page range**.
- **The main goal leaves out admin obligations.** In the dev gold, R150 requirements start at §3.3 (markings). Approval-application paperwork is left out; test-procedure parameters (saline mist, ISO 4892 exposure) are kept.
- **The sub-goal is a paragraph diff.** `subgoal/dev` is UN R175: `old.pdf` and `new.pdf` have the same sha256 as R175 base and latest. Of 94 old requirements, 6 are modified, 1 is removed, and 17 requirements are added. The reasons read like a word diff ("'standstill.' became '…while creeping.'; 'both' was added"). Paragraphs get renumbered ("6.5.2 (formerly 6.5)"). Added items are counted per obligation: §6.6.2.2 alone gives 5 added requirements. The main risk is wrongly flagging the 87 unchanged requirements.

## Core idea

- **A structural graph, not an LLM-extracted knowledge graph.** Build a deterministic, versioned graph for each regulation version from the document's own structure.
  - Nodes are sections, paragraphs and table rows. Each has an exact page range, a breadcrumb path and a content hash.
  - Edges are parent/child, cross-references, citations of other regulations, definitions and supersession.
  - An LLM-extracted knowledge graph would be harder to keep exact, harder to update, and adds nothing here.
- **The LLM never writes a location.** It selects and rewrites, but never produces a page or paragraph number. Every output requirement points to an `obligation_id` that exists in the store, and the citation is filled in from there.
- **Updates work like a build system.** Every derived row (obligation, mapping) records a hash of its inputs. When an input hash changes, the output is marked stale and only that output is recomputed.

---

## Part A: index and grounded retrieval

### A1. Parse each PDF into a node tree

Use PyMuPDF, which gives text plus font and position information.

- **Detect structure.** Paragraph starts match `^\d+(\.\d+)*\.\s`. Also detect `Annex N`, `Part N`, `Appendix N` and `Table X` headers. Strip running headers and footers (E/ECE/… document IDs, printed page numbers). Keep list items such as (a) and (i) inside their paragraph.
- **What each node stores:**
  - `label` in the gold format;
  - a `path` breadcrumb, e.g. `R48 › 6 › 6.10 Rear position lamps › 6.10.4.2`;
  - `text` and `text_hash`;
  - `page_start..page_end`;
  - character offsets plus a char→page map, so any quoted span resolves to its exact page.
- **Tables** become child nodes, one per row, labelled `<para>. Table N`.
- **Sanity check.** Numbering must go to a sibling, child or parent's sibling in order; log anything else.
- **Test against ground truth.** The 190 gold anchors and the 94 anchors in R175 `requirements_old.json` give (regulation, paragraph, page) triples. Target: at least 98% of them found, with the page inside the node's range ±1.

### A2. Edges

- `REFERS_TO`: regex on "paragraph 5.8.1", "Annex 4, Part 1, paragraph 1.1".
- `CITES_REG`: "UN Regulation No. 48".
- `DEFINES`: from the §2 definitions to the term.
- `SUPERSEDES`: a small hand-written table, checked against the R148/R149/R150 text:
  - R148 replaces R6, R7, R23, R38 (lamps);
  - R149 replaces R19, R123;
  - R150 replaces R3, R104.
- Each section node also gets a one-line LLM summary, used when walking the table of contents.

### A3. Obligation layer

Obligations don't depend on the product, so they are computed once per regulation version.

- **Extraction.** For each paragraph or table row, the LLM splits the text into atomic obligations in the gold style.
- **Fields:** `text`, `quote` (the verbatim source span), `condition`, `subject`, and `kind`, one of {design, performance, marking, installation, test-procedure, conformity-of-production, admin}.
- **Check in code.** `quote` must be a fuzzy (≥0.95) substring of the node text, otherwise the obligation is rejected and retried. `page` comes from the quote's character offset.
- **When to run it.** Run it over all base versions on Saturday with the Batch API, so on Sunday the held-out case only needs selection, not extraction.

### A4. Pipeline for one spec

This is a workflow with fixed steps. The LLM makes the decisions inside each step.

1. **Profile.** spec.md plus a vision pass over the exploded view → parts, functions, vehicle category, colours, materials and electronics (LED/PCB → ESA). Each item gets a stable key.
2. **Pick regulations.** The LLM reads a card per regulation (title, §1 scope, short table of contents) against the profile.
   - It follows `CITES_REG` from installation regulations to device regulations (R48 → R148).
   - It applies `SUPERSEDES` to prefer R148/R149/R150 over the older regulations.
   - Be **strict** here, because a wrong regulation drags in dozens of false requirements.
3. **Pick sections.** The LLM walks down the table of contents, using the section summaries, once per profile item, and is **inclusive**. A hybrid search per item (BM25 via FTS5 plus embeddings) is a safety net: hits outside the chosen sections are shown to the LLM so it can add them.
4. **List** every obligation in the chosen subtrees. This step is deterministic and uses no LLM.
5. **Check applicability** of each obligation against the profile.
   - Run in batches, with the profile and instructions cached.
   - Drop `admin` obligations, and drop table rows for other colours or vehicle categories.
   - When in doubt, keep it, because F2 rewards recall.
6. **Verify and emit.** Fill in regulation, version (base), page and label from the store, then validate with `tools/validate.py`.

### A5. If a free-form agent is preferred

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

Matching order: label and hash both equal; then hash only; then label only; then best match by embedding plus token Jaccard, assigned with the Hungarian algorithm. The last step catches cases like "6.5.2 (formerly 6.5)".

### B2. Provenance

- An `obligation` stores `node_text_hash` and `extractor_version`.
- A `mapping` (obligation ↔ spec item) stores `inputs_hash`, a hash of the obligation text, the spec item text and the prompt/model version.
- A mapping's status is `active`, `stale`, `superseded` or `removed`. Nothing is hard-deleted.
- A mapping is stale when its stored hash differs from the current one.

This gives an audit trail of what changed and why, which is also the strongest impact argument for Certivity.

### B3. Trigger: a regulation gets a new version (this is the sub-goal)

1. Parse the new version and align its nodes (B1).
2. **`SAME` and `RENUMBERED` nodes:** carry the obligations over and update only the citation. A page shift is **not** a change, which avoids false "modified" flags.
3. **`MODIFIED` nodes:** re-extract obligations and match old to new within the paragraph. An LLM judge decides whether the meaning changed, using the word diff as evidence: modified, unchanged or removed. New obligations with no match are added.
4. **`REMOVED` and `ADDED` nodes:** their obligations are removed or added. Only count additions inside sections the old requirement set covered.
5. **Reason text.** Build `reason` from a deterministic token diff in the gold format ("Paragraph X (formerly Y) … 'a' became 'b'; 'c' was added"). `new_text` is the old requirement rewritten with the change.
6. **Propagate to specs.** For every spec mapped to this regulation:
   - mappings on removed obligations become `removed`;
   - mappings on modified obligations are re-checked for applicability;
   - added obligations go through step 5 of A4 against the spec profile.
7. **Indirect changes.** If a paragraph or definition that an obligation refers to changes, mark its mappings `stale (review)` without changing them automatically. If the §1 scope changes, re-run regulation selection.

### B4. Trigger: a spec is re-parsed

1. Re-run the profile and match items to their previous keys: by normalized name, with LLM help for renamed parts.
2. Diff the items:
   - **unchanged items** keep their mappings;
   - **changed items** re-run applicability. A red→amber lens or LED→filament change swaps the matching colour or light-source rows;
   - **removed items** lose their mappings, unless another item still supports them;
   - **added items** run A4 for that item only.
3. A change to a global attribute such as vehicle category re-runs everything.

### B5. Trigger: a new regulation is added to the database

1. Index it (A1–A3).
2. Run the regulation-level check against every stored profile. This is cheap: one call per spec.
3. If it applies, run sections → obligations → mappings, with status "added (new regulation)".
4. If it `SUPERSEDES` a regulation that is already mapped, mark the old mappings `superseded`.

## Storage

One SQLite file, loaded into NetworkX for traversal and for the demo's graph views. Neo4j is not worth it at this scale (about 55 regulations × 2 versions).

| Table | Columns |
|---|---|
| `doc` | reg, version, role, sha256 |
| `node` | id, reg, version, kind, label, path, heading, text, text_hash, parent_id, ord, page_start, page_end, char_start, char_end, summary |
| `edge` | src, dst, kind |
| `node_fts` | FTS5 over node text; embeddings stored alongside (numpy or sqlite-vec) |
| `obligation` | id, node_id, ordinal, text, quote, page, kind, condition, node_text_hash, extractor_version |
| `align` / `obl_align` | old, new, kind, sim |
| `spec` | id, case_id, rev, profile_json |
| `spec_item` | id, spec_id, key, kind, text, text_hash |
| `mapping` | id, spec_item_id, obligation_id, status, rationale, inputs_hash, run_id |

## LLM usage (Claude API, Python SDK)

- **Model.** `claude-opus-5-5` by default, with `effort` set explicitly.
- **Bulk extraction (A3)** goes through the Message Batches API, which is 50% cheaper and runs asynchronously. Measure tokens on a sample with `count_tokens` first. Sonnet 5.5 or Haiku 5.5 are options for bulk extraction if quality holds on the anchor tests.
- **Structured outputs** for obligations, selections and diffs. The schema includes `quote`, which is verified in code.
- **Citations API (alternative).** Claude's native Citations feature can return the exact paragraph cited, if each paragraph is passed as its own content block. That fits the demo's explanation text. It can't be combined with structured outputs, so it is not the main path.
- **Prompt caching** for the shared system prompt and the product profile across the many applicability calls.
- **Vision input** for `exploded_view.png`.

## Code layout

New code:

```
src/regcomp/
  parse.py        # A1  PDF → nodes (PyMuPDF)
  graph.py        # A2  edges, supersession table, SQLite/NetworkX
  obligations.py  # A3  extraction + quote verification (batch)
  profile.py      # A4.1 spec + vision → profile
  pipeline.py     # A4.2–6 selection, filtering, emit main-goal JSON
  diff.py         # B1/B3 version alignment, obligation diff, reason text → sub-goal JSON
  propagate.py    # B2–B5 provenance, staleness, triggers
  app.py          # Streamlit demo: spec → requirements (breadcrumb, PDF page link/highlight), coverage table, change view
eval/
  anchors.py      # parser test vs gold + requirements_old anchors
  judge.py        # local LLM 1:1 requirement matcher (approximates the platform), stage-wise recall, F2
```

Reused from the package:

- `tools/fetch_regulations.py` downloads the PDFs to `regulations/pdf/<reg>/<role>/`.
- `tools/validate.py` checks output files.
- `tools/score_local.py` provides `score()` for regulation- and page-level scores, and `_paragraph_key` for normalizing labels when matching anchors.

## Build order

The held-out cases are released Sunday at 08:00, uploads close at 13:00, and the platform accepts 5 uploads per hour.

1. **Fetch the PDFs and inspect them:** text layer, headers, tables, annex numbering. **Check whether the gold `page` is the physical PDF page index or the printed page number.**
2. **Parser and anchor test (A1)** until at least 98% of anchors are found.
3. **Obligation extraction (A3)** for all base versions plus R175 latest, via batch. Check extraction recall against the 94 R175 `requirements_old` entries, which are an independent, expert-written requirement set.
4. **Main pipeline (A4)** on dev-rear-lamp, iterating on the stage-wise metrics below. Upload one dev file to the platform to calibrate the local judge.
5. **Diff and sub-goal (B1/B3)** on `subgoal/dev`.
6. **Propagation triggers (B4/B5) and the demo UI.** Do a dry run on a hand-written front-bumper spec. Likely regulations: R42, R127/GTR 9 and R26, plus R48/R148/R149/R150 and R10 if the bumper carries lamps, reflectors or sensors.

## Verification

- **Parser:** anchor hit rate (the paragraph exists and the gold page is within its range ±1) over the 190 + 94 anchors.
- **Stage-wise recall on the dev case.** This shows where the pipeline is weak, which the brief asks teams to present in the pitch.
  - Regulation level: `python tools/score_local.py out.json`.
  - Section recall: the share of gold paragraphs inside the chosen subtrees.
  - Obligation ceiling: the share of gold requirements matched by any extracted obligation in those subtrees.
  - Final requirement-level precision, recall and F2 from `eval/judge.py`.
- **Grounding audit:** 100% of emitted requirements pass quote verification, and 20 random page links are opened and checked by hand.
- **Sub-goal:** compare with `subgoal/dev/expected.json`. Measure recall of flagged IDs, accuracy of the change type, and false flags among the 87 unchanged requirements.
- **Propagation tests:**
  - change the lens from red to amber in a copy of the spec; only the R150 colour rows should swap;
  - delete "Reversing lamp"; its R48 §6.4 mappings should become `removed`;
  - swap R175 base for latest under a stored mapping set; the result should equal the sub-goal answer.
- **Before every upload,** run `python tools/validate.py` on the output file.

## Risks and assumptions

- **Page numbering is unverified.** Until the PDFs are fetched, we don't know whether pages are physical or printed.
- **Overfitting.** There is only one dev case, so selection rules could overfit to the rear lamp. Keep them generic: supersession, dropping admin obligations, filtering table rows by colour or vehicle category.
- **The supersession table is hand-written** and must be checked against the R148/R149/R150 text.
- **Stack.** This assumes Python and the Claude API; both are easy to swap.
