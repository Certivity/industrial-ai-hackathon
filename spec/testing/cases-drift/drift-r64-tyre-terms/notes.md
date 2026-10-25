# drift-r64-tyre-terms

UN R64, base 3.1.0 -> latest 3.2.0; window: sections Annex 3, Annex 4.

What changed: Run-flat/TPMS test procedure: 'ignition' becomes 'vehicle master control (switch)' in eight paragraphs, 'must' becomes 'shall', and an ADS sentence is added to 2.1 and 2.2.

Trap: terminology swap that changes the test trigger ('ignition' -> 'vehicle master control'), 'must' -> 'shall'.

Alignment of the window (src/ai_agent/drift.py): {'SAME': 35, 'RENUMBERED': 0, 'MODIFIED': 10, 'REMOVED': 0, 'ADDED': 0}.

Old requirements: 46; gold changes: 10 modified, 0 removed, 0 added (10 of 46 old requirements flagged).

The gold was written by DeepSeek (provider.json); the reasons are built in code from the diff. It is a noisy gold.

Changed paragraphs sent to the provider:

- Annex 3 2.2 (MODIFIED): R-009
- Annex 3 2.3 (MODIFIED): R-010, R-011
- Annex 4 2.1 (MODIFIED): R-030
- Annex 4 2.1.1.2 (MODIFIED): R-031
- Annex 4 2.1.1.3 (MODIFIED): R-032
- Annex 4 2.1.1.5 (MODIFIED): R-034
- Annex 4 2.1.1.6 (MODIFIED): R-035
- Annex 4 2.2 (MODIFIED): no requirement
- Annex 4 2.2.3 (MODIFIED): R-042
- Annex 4 2.2.4 (MODIFIED): R-043
