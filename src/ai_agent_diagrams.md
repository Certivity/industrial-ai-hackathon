# Team DeepFry: AI agent diagrams

Diagrams for the pitch and the technical document. Colour code in every diagram: **orange = LLM step** (Claude Sonnet 5.5, unless stated), **blue = deterministic code**, **grey = data or files**.

```mermaid
flowchart LR
    L1["LLM step"]:::llm
    L2["Deterministic code"]:::code
    L3[("Data or file")]:::data
    classDef llm fill:#ffd9a8,stroke:#c46a00,color:#000
    classDef code fill:#cfe3ff,stroke:#1f5fbf,color:#000
    classDef data fill:#e6e6e6,stroke:#666,color:#000
```

*Legend.* The same three classes are used in all diagrams below.

## 1. Big picture: models decide, code verifies

```mermaid
flowchart LR
    subgraph IN["Inputs"]
        S[("Technical spec")]:::data
        D[("Exploded view")]:::data
        R[("Regulation PDFs")]:::data
    end
    P["Parser: regulation graph"]:::code
    A["AI agent: Claude Sonnet 5.5<br/>profile, select, walk, extract"]:::llm
    V["Verification in code<br/>quote in node, page and paragraph<br/>from node, emission policy"]:::code
    subgraph OUT["Outputs"]
        O1[("submission.json")]:::data
        O2[("changes.json, sub-goal")]:::data
    end
    S --> A
    D --> A
    R --> P
    P -->|graph| A
    A -->|candidates| V
    P -->|node text| V
    V --> O1
    V --> O2
    classDef llm fill:#ffd9a8,stroke:#c46a00,color:#000
    classDef code fill:#cfe3ff,stroke:#1f5fbf,color:#000
    classDef data fill:#e6e6e6,stroke:#666,color:#000
```

The agent reads the spec and drawing, and reads regulations through a graph that a deterministic parser built. The model makes the judgement calls: which regulations apply, which sections, which obligations. Code then checks every quote against the node text and writes page, paragraph, regulation and version itself, so the model never writes a citation. The same chain produces `submission.json` (main goal) and `changes.json` (sub-goal).

## 2. Main-goal pipeline

```mermaid
flowchart TD
    SP[("spec.md")]:::data
    IMG[("exploded_view.png")]:::data
    V1["Vision pass 1: read text blocks<br/>effort high"]:::llm
    V2["Vision pass 2: map callouts to parts<br/>effort medium, components"]:::llm
    PR["Product profile<br/>effort medium"]:::llm
    CARDS[("56 regulation cards")]:::data
    SEL["Regulation selection, one call<br/>effort high"]:::llm
    WALK["Section walk per regulation<br/>effort medium<br/>tools: get_toc, read_node, search,<br/>follow_refs, select_sections"]:::llm
    HOP["Citation hop: vet cited regulations<br/>then walk them too<br/>effort medium"]:::llm
    EXP["Expand selection to nodes<br/>cut into chunks of about 24K chars"]:::code
    EXT["Obligation extraction per chunk<br/>effort high"]:::llm
    GR["Quote grounding: quote must be in its node<br/>else rejected"]:::code
    EM["Emission policy precision-v2<br/>filters on modality, addressee,<br/>applies, kind, sparse possible pages"]:::code
    CIT["Citation written by code<br/>regulation, version, page, paragraph"]:::code
    SUB[("submission.json")]:::data
    CM[("component map")]:::data
    SP --> PR
    IMG --> V1 --> V2 --> PR
    PR --> SEL
    CARDS --> SEL
    SEL --> WALK
    WALK --> HOP
    HOP -->|approved| WALK
    WALK --> EXP
    EXP --> EXT --> GR --> EM --> CIT --> SUB
    V2 -.-> CM
    EM -.-> CM
    classDef llm fill:#ffd9a8,stroke:#c46a00,color:#000
    classDef code fill:#cfe3ff,stroke:#1f5fbf,color:#000
    classDef data fill:#e6e6e6,stroke:#666,color:#000
```

Vision reads the drawing in two passes and feeds the facts into a product profile. One call picks regulations from 56 cards. A walker per regulation reads the outline and selects sections. Regulations cited by the selected text are vetted and walked too. Extraction runs on chunks at high effort, and code then grounds each quote, applies the precision-v2 filters and writes the citation. The component map (requirement to part, `components`, medium effort) is a side artifact. Optional steps, such as the selection verifier (`verify`, medium), are off by default.

## 3. How the regulation graph is built

```mermaid
flowchart TD
    PDF[("Regulation PDF")]:::data
    LN["Text lines with font, size,<br/>bold, position, page"]:::code
    SH["Line-start shapes<br/>5.1.4. or Annex 2A or (b)"]:::code
    subgraph IND["Per-document induction, no built-in vocabulary"]
        direction TB
        I1["Number families: 1,2,3 / a,b,c / 5.1,5.1.1"]:::code
        I2["Discovered keywords: Annex if numbering restarts"]:::code
        I3["Nesting and typography levels"]:::code
        I4["Self-calibrated evidence<br/>headers and footers = repeated margin lines"]:::code
        I1 --> I2 --> I3 --> I4
    end
    DEC["Beam and stack decoding<br/>beam of 12 states, best whole path"]:::code
    TREE[("Node tree: label, pages, text,<br/>text hash, tables, cross-references")]:::data
    CONF{"Confidence under 0.55?"}:::code
    OK[("Graph used by the agent<br/>and drift: all 92 corpus PDFs")]:::data
    FB["Fallback: DeepSeek reads page windows<br/>returns only an outline<br/>label, page, first words, level"]:::llm
    VH["Headings verified at a line start<br/>in the text layer, unfound ones dropped"]:::code
    CUT["Text cut by code"]:::code
    PDF --> LN --> SH --> IND --> DEC --> TREE --> CONF
    CONF -->|"no, default path"| OK
    CONF -->|"yes, never happened"| FB --> VH --> CUT --> OK
    classDef llm fill:#ffd9a8,stroke:#c46a00,color:#000
    classDef code fill:#cfe3ff,stroke:#1f5fbf,color:#000
    classDef data fill:#e6e6e6,stroke:#666,color:#000
```

The submission uses the marker parser with per-document induction, which learns the numbering scheme, keywords and nesting from each document itself. A confidence check follows. Only a low score (under 0.55) triggers the DeepSeek outline fallback, and it never did on the 92 corpus PDFs. In the fallback the model writes only an outline: code verifies each heading in the text layer and cuts the text itself.

Example tree (R148 style):

```mermaid
flowchart TD
    R5["5 Specifications"]:::data --> R51["5.1"]:::data --> R511["5.1.1 para, p. 17"]:::data
    A3["Annex 3"]:::data --> A311["1.1 para<br/>numbering restarts inside the annex"]:::data
    R511 -.->|refers_to| T4["Table 4"]:::data
    classDef data fill:#e6e6e6,stroke:#666,color:#000
```

## 4. What the agent reads from the graph

```mermaid
flowchart LR
    G[("Regulation graph, one per regulation")]:::data
    OL["Outline in first message<br/>every section with page range and size"]:::code
    W["Section walker, LLM"]:::llm
    T1["get_toc: sub-sections, 1-3 levels"]:::code
    T2["read_node: node text or subtree<br/>cut at 14,000 chars, tables as grid rows"]:::code
    T3["search: BM25 hits, optionally inside a node"]:::code
    T4["follow_refs: points to, pointed at by,<br/>other regulations cited"]:::code
    T5["select_sections: ends the walk<br/>node, category, reason, excludes"]:::code
    CK["Unknown label: closest real labels offered,<br/>select_sections refuses it"]:::code
    G --> OL --> W
    W <--> T1
    W <--> T2
    W <--> T3
    W <--> T4
    W --> T5
    T1 --- G
    T2 --- G
    T3 --- G
    T4 --- G
    T5 --- CK
    classDef llm fill:#ffd9a8,stroke:#c46a00,color:#000
    classDef code fill:#cfe3ff,stroke:#1f5fbf,color:#000
    classDef data fill:#e6e6e6,stroke:#666,color:#000
```

The walker starts with the outline already in its first message, so it often selects straight away. Five tools, each bound to one regulation, let it look inside when titles are unclear. The agent names nodes by label, and code answers every tool call from the graph. Code rejects any label that does not exist.

## 5. Drift pipeline (sub-goal)

```mermaid
flowchart TD
    OLD[("Old version PDF")]:::data
    NEW[("New version PDF")]:::data
    REQ[("Old requirements")]:::data
    PO["Parse old to graph"]:::code
    PN["Parse new to graph"]:::code
    AL["Alignment: same label and same text hash = SAME<br/>Hungarian matching on token similarity<br/>MODIFIED or RENUMBERED, rest REMOVED or ADDED"]:::code
    MAP["Map old requirements to old nodes<br/>by label, then BM25"]:::code
    GATE["Gate: only changed nodes carrying requirements<br/>wording-only changes dropped"]:::code
    J["LLM judge, medium effort<br/>modified, removed or unchanged"]:::llm
    AD["Added extraction, 20K chars per call<br/>old requirements as examples"]:::llm
    RS["Reasons built in code from the word diff"]:::code
    CH[("changes.json")]:::data
    OLD --> PO --> AL
    NEW --> PN --> AL
    REQ --> MAP
    PO --> MAP
    AL --> GATE
    MAP --> GATE
    GATE --> J --> RS
    AL -->|ADDED nodes| AD --> RS
    RS --> CH
    classDef llm fill:#ffd9a8,stroke:#c46a00,color:#000
    classDef code fill:#cfe3ff,stroke:#1f5fbf,color:#000
    classDef data fill:#e6e6e6,stroke:#666,color:#000
```

Both versions are parsed and aligned by code, so renumbering and page shifts never reach the model. Old requirements are mapped to nodes, and only a changed node that carries requirements is sent to the judge. Added paragraphs go to an extraction call. Code writes the reasons from the word diff. This keeps a run at $0.00 to $0.08, and the held-out R171 case at $0.42.

## 6. Evaluation setup

```mermaid
flowchart LR
    DEV[("Dev expert case<br/>rear lamp, 190 requirements")]:::data
    DS[("26 DeepSeek cases")]:::data
    TUNE["Tune split: 10 cases"]:::code
    HELD["Held-out split: 16 cases<br/>reported once"]:::code
    AUD[("Audited regulation reference<br/>3 DeepSeek votes, majority")]:::data
    CHEAP["Cheap bench mode<br/>selection only, replay cache"]:::code
    SC["Scores: P, R, F1, F2<br/>local judge strict and lenient"]:::llm
    DS --> TUNE
    DS --> HELD
    TUNE --> CHEAP
    HELD --> CHEAP
    AUD --> CHEAP
    DEV --> SC
    CHEAP --> SC
    classDef llm fill:#ffd9a8,stroke:#c46a00,color:#000
    classDef code fill:#cfe3ff,stroke:#1f5fbf,color:#000
    classDef data fill:#e6e6e6,stroke:#666,color:#000
```

The expert dev case is the one trustworthy yardstick. The 26 DeepSeek cases have a noisy gold, so we split them: tune on 10, report 16 held out. An audited regulation reference, built from three DeepSeek votes per candidate, corrects the noisiest gold labels. The cheap bench mode scores regulation selection without running extraction.
