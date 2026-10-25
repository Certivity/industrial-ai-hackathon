# drift-r132-reagent-restructure

UN R132, base 1.0.0 -> latest 1.1.0; window: sections 7, 8.

What changed: Retrofit emission control devices: the approval conditions 7.9.1-7.9.4 become items (a)-(d) of a single paragraph 7.9; 7.5.1 'may interrupt' becomes 'shall include the detection of the interruption of'.

Trap: a list merged into one paragraph (five removals and one addition that say the same).

Alignment of the window (src/ai_agent/drift.py): {'SAME': 64, 'RENUMBERED': 1, 'MODIFIED': 4, 'REMOVED': 5, 'ADDED': 2}.

Old requirements: 55; gold changes: 4 modified, 0 removed, 4 added (4 of 55 old requirements flagged).

The gold was written by DeepSeek (provider.json); the reasons are built in code from the diff. It is a noisy gold.

Changed paragraphs sent to the provider:

- 7.5.1 (MODIFIED): R-007, R-008
- 7.9 (REMOVED): no requirement
- 7.9.1 (REMOVED): no requirement
- 7.9.2 (REMOVED): no requirement
- 7.9.3 (REMOVED): no requirement
- 7.9.4 (REMOVED): no requirement
- 8.3.2 (MODIFIED): R-037
- 8.5.2 (MODIFIED): R-046
- 8.6.2 (MODIFIED): R-050
