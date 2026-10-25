# drift-r39-speedometer

UN R39, base 2.1.0 -> latest 2.2.0; window: sections 2, 5.

What changed: Speedometer: ADS sentences added to 5.1, 5.2, 5.5, 5.11; 'onboard' -> 'on-board' and 'UN' insertions that change nothing; a table caption removed.

Trap: ADS exemptions, one-word typography fixes.

Alignment of the window (src/ai_agent/drift.py): {'SAME': 49, 'RENUMBERED': 0, 'MODIFIED': 9, 'REMOVED': 0, 'ADDED': 2}.

Old requirements: 57; gold changes: 5 modified, 0 removed, 4 added (5 of 57 old requirements flagged).

The gold was written by DeepSeek (provider.json); the reasons are built in code from the diff. It is a noisy gold.

Changed paragraphs sent to the provider:

- 2.6 (MODIFIED): no requirement
- 2.7 (MODIFIED): no requirement
- 5.1 (MODIFIED): R-001, R-002, R-003
- 5.2 (MODIFIED): R-004, R-005, R-006
- 5.3.5 (MODIFIED): R-029, R-030, R-031, R-032
- 5.5 (MODIFIED): R-038, R-039, R-040
- 5.5.2 (MODIFIED): R-042, R-043
- 5.9 (MODIFIED): R-049, R-050
- 5.11 (MODIFIED): R-052
