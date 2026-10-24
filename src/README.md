# regcomp.parse: the regulation parser

`regcomp/parse.py` turns a UN Regulation PDF from `regulations/data/` into a list of **nodes**: one per numbered paragraph, table, or annex/appendix/part heading, each with its paragraph label and the physical page range the platform scores. It calls no model, so a citation can be filled in from a node instead of being written by one. `regcomp/corpus.py` finds the PDFs.

```python
from regcomp import corpus
from regcomp.parse import parse_pdf

pdf = corpus.pdf_path(corpus.entry_for("UN R150"), "base")   # regulations/data/UN_R150/base/UN_R150_base.pdf
doc = parse_pdf(pdf)                                          # R150: 2 s; parse_pdf(pdf, grids=False) takes 0.2 s
node = next(n for n in doc.nodes if n.label == "3.3.1.1")
node.page_start, node.page_end                                # (7, 7)
node.body                                                     # '3.3.1.1. Every device belonging to an approved type shall ...'
node.page_of("comprise a space of sufficient size")           # 7, the page of the line where the quote starts (None if absent)
```

`corpus.all_pdfs()` lists every fetched PDF as `(regulation, role, path)`; the role is `base` (the version the expected requirements are built on) or `latest`. Needs PyMuPDF (`pip install pymupdf`; on a long Windows path use a venv and `pip install --no-deps pymupdf`) and the PDFs (`python tools/fetch_regulations.py --out regulations/data`).

## What a node holds

| | |
|---|---|
| `kind` | `para`, `table`, or a heading: `annex`, `annex-appendix`, `appendix`, `part` |
| `label` | the gold's format: `3.3.1.1`, `Annex 4 Part 1 1.2`, `5.1.4.4.1. Table 3`. Compare labels with `tools/score_local._paragraph_key` |
| `scope`, `num` | where the numbering restarts (`""` in the body, else `Annex 4 Part 1`) and the number as a tuple |
| `page_start`, `page_end` | the physical PDF page, which is the page the footer prints on all 92 PDFs. A table's label and `page_start` are its caption's |
| `body` | the node's own text; sub-paragraphs are separate nodes. Exponents are written raised (`10²`) |
| `grid` | the ruled tables inside the node as markdown, else `None` |
| `figure_refs` | the figures the text mentions |

A grid has one table row per line and repeats a key cell over the rows it spans, so a requirement can be read off one line: `| IA, IB | Red | Angle of divergence α | 20' | 3.00∙10² | 2.00∙10² | 1.00∙10² | -- | -- | -- |`.

`ParsedDocument` also keeps what a health check needs: `left_out`, `lost_starts`, `orphans`, `wrapped`, `jumps`, `footer_mismatches`, `image_pages`, `grids`, `grid_errors`.

## How it finds the structure

1. **Lines.** The lines of every page come from PyMuPDF. Footers are dropped (their `page N of M` is checked against the physical page) and superscript spans are written as raised digits.
2. **Scopes.** `Annex 4`, `Annex 4 - Appendix 1` and `Part 1 - ...` are headings when they are bold and at least 1.15 times the body font. The renderer scales pages, so the size is always compared with the document's, never fixed.
3. **Paragraphs.** In each scope the paragraph starts are the longest increasing chain of the numbers found at line starts. That drops table cells, figure legends and wrapped references (`... paragraph` then `6.4. of this Regulation`) without needing the numbers to be consecutive. A heading without its final dot (`5.7 Title`) counts if it is nested, styled, or followed by its own first sub-paragraph.
4. **Tables.** A line `Table N Title` opens a table node, owned by the nearest paragraph that names the table.
5. **Grids.** Pages that draw ruling lines go to `find_tables(use_layout=False)`, the cell text is rebuilt from the spans, and each grid goes to the node that holds the text inside it. A table with no caption line (R10 6.9.1) is covered, and a table cut by a page break is one grid. `use_layout=False` matters: PyMuPDF 2's default asks a neural layout model that varies with the machine and dropped a real table.

## Limits

- Figures and formulas drawn as images are not read (`image_pages` lists the pages). "See Figure X" stays in the text.
- Tables without ruling lines, or drawn as images, get no grid (6 of the 243 captioned tables in the base versions). Their text is in `body`, flattened.
- Page footnotes are not separated: their text stays in the node above them.
- A paragraph whose parent number is missing in the source is listed in `orphans` and not repaired. Most are form cells or unnumbered headings.
- The rules were written from five regulations and widened after the first run over all 92 PDFs. `eval/health.py` flags 14 of them for a closer look, and a regulation not seen yet can still break a rule.

## After any change

```
python eval/anchors.py     # the 178 expert (page, paragraph) anchors are found
python eval/fidelity.py    # the numbers of the expert requirements are in the parsed text
python eval/test_parse.py  # unit tests, then tests on the PDFs (--unit: no PDFs needed)
python eval/health.py --baseline spec/testing/parse-health.csv   # what the change did to the other PDFs
```

The rules and the data behind them are in `spec/finding/finding.md`, and what went wrong and how it is guarded in `spec/testing/report.md` section 9.
