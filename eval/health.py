#!/usr/bin/env python3
"""Parser health over every fetched PDF. It needs no gold, only signs that the layout rules hold on a regulation.

    python eval/health.py                        # one row per fetched PDF, outliers flagged
    python eval/health.py --csv health.csv       # also write the rows as CSV
    python eval/health.py --only "UN R13H"       # a single regulation (repeatable)
    python eval/health.py --baseline spec/testing/parse-health.csv   # list the PDFs a parser change touched
    python eval/health.py --no-grids             # skip the table grids: about 5x faster, the grid columns stay empty

A PDF is flagged when
  footer     a footer is missing, or its page number is not the physical page
  lost       more than 3% of the numbered lines were left out although a sentence follows the number (probable real paragraphs)
  density    fewer than 3 or more than 25 nodes per page
  no-nodes   nothing was parsed
  front      more than 3,000 characters sit before the first heading or paragraph (a long introduction also does this)
  gaps       numbering gaps larger than 3 inside a chain, more than 2% of the nodes
  orphans    more than 3% of the paragraphs have no parent paragraph in their scope (a heading was lost)
  grid-err   find_tables() raised on a page
  no-grid    fewer than half of the captioned tables got a grid (3 or more of them): drawn as images, or the rulings are unusual
  no-1       the body has no section numbered 1 (usually the scope heading was not recognised)
  scope-rej  a bold line that reads as an Annex or Appendix heading, is short, has a title and sits at body size or above, differs in
             id from the scope it sits in, and still was not taken for a heading: neither the numbering restarts after it nor does
             its id follow the scope's (the restart rule of parse.py takes in the ones that do: R101 Annex 7 Appendix 3)
A flag means "look at a page or two", not "wrong". The `restarts` column (the `rst` column of the table) is a count, not a flag: a "1."
left out of the chain, with a sentence after it, after the chain had passed 1, and a "2." or "1.1." behind it, so numbering started over
under a heading the parser does not know (R13H Annex 4: plain "A." and "B." headings over paragraphs 1, 2, 3; R49's "Item N"). The text
stays in the neighbouring node and the page stays right; the label does not. Over the 92 PDFs it is mostly not a defect (a
communication form's "1. Additional information: see addendum" in R107 and R116, the items of a table in R171, a list in R101, a figure
note in R48), which is why it does not raise a flag; read it where `lost` or `orphans` is also set.
The remaining orphans are mostly not lost headings: numbers in table and
form cells ("1.1." on a line of its own), headings the source leaves unnumbered ("Scenario 1" over R131's 1.1., 1.2.), a typo of
the source (R13H "5.2.1.24.16."), and one heading glued to the end of the previous sentence (R67 17.10). The first run flagged "left-out" (more than 5% of the numbered lines not
accepted); that turned out to count table cells and figure legends as much as lost text (R51's symbol table), so `lost`
replaced it and `left_out_pct` stays in the table for information. `wrapped` counts numbered lines that only continue a
reference ("... in paragraph" / "6.4. of this Regulation"); they are not candidates. --baseline compares nodes, tables, lost,
orphans, wrapped, scope_rejects, scope_open, restarts and the grid counts with an earlier CSV of this script, so a rule written for one PDF shows what it did to the other 91.
`grids` is the number of nodes that got a grid, `table_grids` how many of the `tables` (captioned) are among them, `loose_grids` the
ruled tables on no node's text.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from regcomp import corpus  # noqa: E402
from regcomp.parse import ParsedDocument, parse_pdf  # noqa: E402

MODAL = re.compile(r"\b(shall|must|should|is required|are required)\b", re.I)
COLUMNS = ["regulation", "role", "version", "pages", "chars", "nodes", "tables", "scopes", "nodes_per_page", "candidates",
           "left_out", "left_out_pct", "lost", "lost_pct", "orphans", "wrapped", "scope_rejects", "scope_open", "restarts", "grids", "table_grids", "loose_grids", "grid_errors", "gaps", "max_gap", "footers", "footer_mismatches", "image_pages", "image_pct",
           "front_chars", "sections", "modal_pct", "seconds", "flags"]


def measure(regulation: str, role: str, path: Path, grids: bool = True) -> dict:
    started = time.perf_counter()
    doc: ParsedDocument = parse_pdf(path, grids=grids)
    seconds = time.perf_counter() - started
    content = [n for n in doc.nodes if n.kind in ("para", "table")]
    sections = [n for n in content if n.kind == "para" and not n.scope and len(n.num) == 1]
    row = {
        "regulation": regulation,
        "role": role,
        "version": corpus.version_label(corpus.entry_for(regulation), role),
        "pages": doc.pages,
        "chars": sum(len(n.body) for n in doc.nodes),
        "nodes": len(content),
        "tables": sum(1 for n in content if n.kind == "table"),
        "scopes": sum(1 for n in doc.nodes if n.kind not in ("para", "table")),
        "nodes_per_page": round(len(content) / doc.pages, 1),
        "candidates": doc.candidates,
        "left_out": len(doc.left_out),
        "left_out_pct": round(100 * len(doc.left_out) / max(1, doc.candidates), 1),
        "lost": len(doc.lost_starts),
        "lost_pct": round(100 * len(doc.lost_starts) / max(1, doc.candidates), 1),
        "orphans": len(doc.orphans),
        "wrapped": len(doc.wrapped),
        "scope_rejects": len(doc.scope_rejects),
        "scope_open": len(doc.unexplained_rejects),
        "restarts": len(doc.restarts),
        "grids": doc.grids if grids else "",
        "table_grids": sum(1 for n in content if n.kind == "table" and n.grid) if grids else "",
        "loose_grids": doc.loose_grids if grids else "",
        "grid_errors": len(doc.grid_errors) if grids else "",
        "gaps": len(doc.jumps),
        "max_gap": max((j[3] for j in doc.jumps), default=0),
        "footers": doc.footers,
        "footer_mismatches": len(doc.footer_mismatches),
        "image_pages": len(doc.image_pages),
        "image_pct": round(100 * len(doc.image_pages) / doc.pages),
        "front_chars": doc.front_chars,
        "sections": len(sections),
        "modal_pct": round(100 * sum(1 for n in content if MODAL.search(n.body)) / max(1, len(content))),
        "seconds": round(seconds, 1),
    }
    flags = []
    if doc.footers != doc.pages or doc.footer_mismatches:
        flags.append("footer")
    if row["lost_pct"] > 3:
        flags.append("lost")
    if not content:
        flags.append("no-nodes")
    elif row["nodes_per_page"] < 3 or row["nodes_per_page"] > 25:
        flags.append("density")
    if doc.front_chars > 3000:
        flags.append("front")
    if content and len(doc.jumps) > 0.02 * len(content):
        flags.append("gaps")
    if not any(n.num == (1,) for n in sections):
        flags.append("no-1")
    if row["orphans"] > 0.03 * max(1, sum(1 for n in content if n.kind == "para")):
        flags.append("orphans")
    if doc.unexplained_rejects:
        flags.append("scope-rej")
    if grids and doc.grid_errors:
        flags.append("grid-err")
    if grids and row["tables"] >= 3 and row["table_grids"] < 0.5 * row["tables"]:
        flags.append("no-grid")
    row["flags"] = " ".join(flags)
    return row


def compare(rows: list[dict], baseline: str) -> None:
    """Print the PDFs whose counts differ from an earlier run (a column the earlier CSV lacks shows as '?')."""
    with open(baseline, newline="", encoding="utf-8") as handle:
        before = {(r["regulation"], r["role"]): r for r in csv.DictReader(handle)}
    fields = ("nodes", "tables", "lost", "orphans", "wrapped", "scope_rejects", "scope_open", "restarts", "grids", "table_grids", "loose_grids")
    changed = []
    for row in rows:
        old = before.get((row["regulation"], row["role"]), {})
        diffs = [f"{f} {old.get(f, '?')} -> {row[f]}" for f in fields if str(old.get(f, "?")) != str(row[f])
                 and (f in old or row[f])]
        if diffs:
            changed.append(f"  {row['regulation']} {row['role']}: " + ", ".join(diffs))
    print(f"\nagainst {baseline}: {len(changed)} of {len(rows)} PDFs changed")
    print("\n".join(changed))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parser health over the fetched regulation PDFs.")
    parser.add_argument("--csv", help="also write the rows to this CSV file")
    parser.add_argument("--only", action="append", default=[], help="only this regulation (repeatable)")
    parser.add_argument("--baseline", help="an earlier CSV of this script: list the PDFs whose counts changed")
    parser.add_argument("--no-grids", action="store_true", help="skip the table grids (about 5x faster; the grid columns stay empty)")
    args = parser.parse_args(argv)

    pdfs = [p for p in corpus.all_pdfs() if not args.only or p[0] in args.only]
    if not pdfs:
        print("error: no PDFs found; run tools/fetch_regulations.py --out regulations/data", file=sys.stderr)
        return 2
    print(f"{'regulation':<10}{'role':<7}{'pages':>5}{'nodes':>6}{'n/pg':>6}{'cand':>6}{'left%':>6}{'lost':>5}{'lost%':>6}{'orph':>5}"
          f"{'rej':>4}{'rst':>4}{'gaps':>5}{'tbl':>5}{'grid':>5}{'img%':>5}{'front':>6}{'sect':>5}{'modal%':>7}  flags")
    rows = []
    for regulation, role, path in pdfs:
        row = measure(regulation, role, path, grids=not args.no_grids)
        rows.append(row)
        print(f"{row['regulation']:<10}{row['role']:<7}{row['pages']:>5}{row['nodes']:>6}{row['nodes_per_page']:>6}"
              f"{row['candidates']:>6}{row['left_out_pct']:>6}{row['lost']:>5}{row['lost_pct']:>6}{row['orphans']:>5}{row['scope_open']:>4}{row['restarts']:>4}{row['gaps']:>5}"
              f"{row['tables']:>5}{row['table_grids']:>5}{row['image_pct']:>5}{row['front_chars']:>6}{row['sections']:>5}{row['modal_pct']:>7}  {row['flags']}", flush=True)
    flagged = [r for r in rows if r["flags"]]
    print(f"\n{len(rows)} PDFs, {len(flagged)} flagged: " + (", ".join(f"{r['regulation']} {r['role']} [{r['flags']}]" for r in flagged) or "none"))
    if args.baseline:
        compare(rows, args.baseline)
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
