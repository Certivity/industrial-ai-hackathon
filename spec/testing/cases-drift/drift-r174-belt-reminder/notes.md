# drift-r174-belt-reminder

UN R174, base 1.0.1 -> latest 1.1.0; window: sections 5.

What changed: Safety-belt reminder: footnote 3 changes, the reminder now covers first-row occupants of category X vehicles, 'Whilst an ADSF-2 is active, paragraph 5.1.4 shall apply' is added, 5.1.4 is new.

Trap: footnote text changes and ADS sentences; a reference fixed (6.2.4.1.1 -> 5.2.4.1.1).

Alignment of the window (src/ai_agent/drift.py): {'SAME': 45, 'RENUMBERED': 0, 'MODIFIED': 7, 'REMOVED': 0, 'ADDED': 1}.

Old requirements: 51; gold changes: 2 modified, 0 removed, 1 added (2 of 51 old requirements flagged).

The gold was written by DeepSeek (provider.json); the reasons are built in code from the diff. It is a noisy gold.

Changed paragraphs sent to the provider:

- 5.1.1 (MODIFIED): R-001
- 5.1.2 (MODIFIED): R-002, R-003
- 5.2.3.1 (MODIFIED): R-011, R-012
- 5.2.4.1 (MODIFIED): R-015, R-016
- 5.3 (MODIFIED): no requirement
- 5.3.1 (MODIFIED): R-025
- 5.4.2 (MODIFIED): R-029, R-030, R-031
