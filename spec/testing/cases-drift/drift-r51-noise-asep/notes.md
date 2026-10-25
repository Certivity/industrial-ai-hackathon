# drift-r51-noise-asep

UN R51, base 3.10.0 -> latest 3.11.0; window: sections Annex 7.

What changed: Noise, Annex 7 (ASEP): the control range moves into a table, the evaluation formulas change (3 dB(A) -> 2 dB, new term delta L), purely electric vehicles get a separate method.

Trap: formulas and a new table; wording of calculations.

Alignment of the window (src/ai_agent/drift.py): {'SAME': 25, 'RENUMBERED': 0, 'MODIFIED': 7, 'REMOVED': 0, 'ADDED': 2}.

Old requirements: 74; gold changes: 3 modified, 1 removed, 7 added (4 of 74 old requirements flagged).

The gold was written by DeepSeek (provider.json); the reasons are built in code from the diff. It is a noisy gold.

Changed paragraphs sent to the provider:

- Annex 7 2.3 (MODIFIED): R-010, R-011, R-012, R-013, R-014, R-015, R-016
- Annex 7 3.1 (MODIFIED): no requirement
- Annex 7 3.2 (MODIFIED): R-039
- Annex 7 3.3 (MODIFIED): R-043
- Annex 7 3.4 (MODIFIED): R-044
- Annex 7 3.5 (MODIFIED): R-045, R-046, R-047, R-048
- Annex 7 5.2 (MODIFIED): R-063, R-064, R-065, R-066
