# drift-r149-lamp-uid-removed

UN R149, base 1.6.0 -> latest 1.7.0; window: sections 3.2, 3.3.

What changed: Road illumination devices, marking: the Unique Identifier section 3.3.3 is deleted, so 3.3.4-3.3.6 become 3.3.3-3.3.5 (14 renumbered), and 'the Unique Identifier or' is cut from several paragraphs.

Trap: a removed section shifts the numbering below it ('formerly 3.3.4'); removal of a phrase in many paragraphs.

Alignment of the window (src/ai_agent/drift.py): {'SAME': 28, 'RENUMBERED': 14, 'MODIFIED': 10, 'REMOVED': 2, 'ADDED': 0}.

Old requirements: 74; gold changes: 9 modified, 2 removed, 1 added (11 of 74 old requirements flagged).

The gold was written by DeepSeek (provider.json); the reasons are built in code from the diff. It is a noisy gold.

Changed paragraphs sent to the provider:

- 3.2.6. Table 2 (MODIFIED): no requirement
- 3.3.1.1 (MODIFIED): R-034
- 3.3.2.4.8 (MODIFIED): R-049
- 3.3.2.4.9 (MODIFIED): R-050
- 3.3.3 (REMOVED): no requirement
- 3.3.3.1 (REMOVED): R-054, R-055
- 3.3.4 (MODIFIED): R-056
- 3.3.4.7.1 (MODIFIED): R-063
- 3.3.5.1 (MODIFIED): R-068
- 3.3.5.2 (MODIFIED): R-069
- 3.3.5.3 (MODIFIED): R-070
- 3.3.6.1 (MODIFIED): R-072, R-073, R-074
