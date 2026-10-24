# Frontend proposal: mock-first UI for document upload and compliance results

Status: draft v2, 2026-10-24. Companion to the root `proposal.md` (backend and pipeline). Conventions come from `src/frontend/AGENTS.md`: shadcn/ui, Lucide icons, TypeScript, no extra UI libraries.

Changes from v1: S3 and the upload-transport comparison are gone (local only); regulation PDFs are no longer a frontend concern; the structure now covers the future results screens (analysis run, met/unmet requirements, evidence), not only upload.

## Goal

Build a **clickable mock** of the whole product loop before the backend logic exists, so the team shares one mental model:

1. The user uploads technical documentation of a car component (spec, exploded view, drawings, datasheets).
2. The user starts an analysis. The backend reads the files and returns a list of regulatory requirements for the component, each marked met, unmet, or not assessable.
3. The user browses the results and checks each against the cited regulation page.

Only step 1 is built for real in the first iteration. Steps 2 and 3 are built against the mock, using the same contract the backend will later implement, so the screens survive the switch.

## Assumptions

- **Local only.** One user, one machine, frontend on `localhost:5173`, backend on `localhost:8000`. No auth, no CORS (the Vite dev server proxies `/api`), no cloud storage.
- **Files go to the backend, the backend writes them to disk.** A browser cannot write to an arbitrary folder, so the frontend sends each file with `multipart/form-data` to `POST /api/.../documents`, and FastAPI saves it under `data/uploads/<case_id>/<doc_id>/<name>`. The analysis code reads from that path. This is cheap for local files; receiving a file and processing it stay separate steps (upload returns at once, analysis is a later explicit action).
- **Regulations are the backend's job.** It retrieves and indexes the PDFs on its own schedule. The frontend never uploads, lists or manages them. It only displays citations and fetches page images for them (`GET /api/regulations/{reg}/pages/{n}.png`, root proposal Phase 5).
- **A case is one car component.** v1 has a single implicit case, pre-named "Rear lamp", but every URL and type carries `caseId` so more cases need no redesign.

## First stint (built): requirements browser

Before upload and analysis, the first page lets the user pick a product and browse the regulatory requirements of that product. It reads straight from `cases/<case-id>/expected.json`; there is no backend call.

- **Data access.** `src/lib/cases.ts` uses `import.meta.glob` over `cases/*/expected.json` (lazy, so a case is only loaded when selected) and `cases/*/spec.md` (the first heading, e.g. `# spec: Rear Lamp`, is the product name; the folder name is the fallback). Adding a case folder adds a product to the picker with no code change. `vite.config.ts` allows the dev server to read the repo root, because `cases/` is outside the frontend folder.
- **Filters** (all client-side; the dev case has 190 requirements, so no performance concern): product, free-text search over requirement text and ID, regulation, version (options narrow to the chosen regulation), and paragraph prefix (`6.4` matches `6.4.2.3` but not `16.4`). A "Clear" button and a "Showing N of M" counter.
- **Table:** ID, regulation + version, paragraph, page, requirement text. States: loading skeleton, error, no match.
- **Code:** `features/requirements/` (`requirements-page`, `requirements-table`, `filter-select`, `filters.ts`, `use-requirements`). `Requirement` and `Citation` in `lib/cases.ts` are the same shape as the `Finding` below minus `status`, so the later findings screen reuses them.
- **Expected format.** Each case's `expected.json` has `requirements: [{ id, text, source: { regulation, version, page, paragraph } }]`. A file without a `requirements` list shows an error instead of an empty table.
- **Limit.** When filtering needs to move to a server (thousands of rows), the filter function is the only thing to replace.

## Mental model

```
Case ── has many ──▶ Documents
  │
  └── has many ──▶ Analysis runs ── produce ──▶ Findings (one per regulatory requirement)
                                                  │   status: unmet | met | not-assessable
                                                  └── cites: regulation, version, page, paragraph
                                                      evidence: where in the uploaded documents
```

The three screens map to these nouns:

```
Documents ──▶ Analysis ──▶ Findings
 (upload)     (run + progress)   (table, filters, detail with page image)
```

An **analysis run** is immutable: it records which documents (by `sha256`) it read. Changing or adding a document does not rewrite old results; it makes the latest run "stale", and the UI offers to run again. This also matches the hash-based caching in the root proposal.

## The met/unmet question

The root proposal's pipeline (A4) returns the requirements that **apply** to the product, each with a citation. It does not yet decide whether the product **meets** them. The documents may not contain the evidence (a spec saying "red PMMA lens" cannot show that photometric values pass). So the result model has three states, not two:

| Status | Meaning |
|---|---|
| `unmet` | the documents show the product fails or contradicts the requirement |
| `met` | the documents show the product satisfies it |
| `not-assessable` | applies, but the uploaded documents have no evidence either way (expected to be the most common) |

Each finding carries `rationale` and optional `evidence` (document, location, quote). The UI must not present `not-assessable` as "failed" or "passed". It is a to-do for the user: "provide a test report for this". The backend team confirms this model before it is built, because it adds an assessment step beyond the root proposal. The UI works the same if the backend starts by returning only `not-assessable` for everything.

## Screens

### 1. Documents (`/cases/:caseId/documents`), live in iteration 1

```
┌───────────────┬──────────────────────────────────────────────────────────┐
│ ◇ RegComp     │  Rear lamp                                [Run analysis] │
│               │  Upload the technical documentation of this component.   │
│ ▣ Documents   │ ┌──────────────────────────────────────────────────────┐ │
│ ○ Analysis    │ │        ⬆  Drop files here or  [Browse files]         │ │
│ ○ Findings    │ │   PDF, MD, TXT, images, CSV, JSON, DOCX, XLSX · ≤50 MB│ │
│               │ └──────────────────────────────────────────────────────┘ │
│               │  Name                 Type    Size    Status      Actions │
│               │  spec.md              MD      1 KB    ● Uploaded   👁 🗑   │
│               │  exploded_view.png    Image   212 KB  ● Uploaded   👁 🗑   │
│               │  datasheet.pdf        PDF     3.1 MB  ▓▓▓░░ 62%    ✕     │
└───────────────┴──────────────────────────────────────────────────────────┘
```

States: empty, drag-over, uploading (progress, cancel), uploaded, failed (retry), rejected by validation, delete confirmation. "Run analysis" is disabled with a tooltip while there are no uploaded documents or the backend reports it is unavailable.

Upload rules (shared constants in `lib/documents.ts`; the backend repeats them): allow-list `pdf, md, txt, png, jpg, jpeg, webp, csv, json, docx, xlsx`; 50 MB per file; the backend checks the magic bytes and computes `sha256`, and a duplicate hash in the same case returns the existing document. Uploads are untrusted: sanitise names, never render uploaded HTML.

### 2. Analysis (`/cases/:caseId/analysis`), mock only at first

Shows the latest run: status (`queued → running → done | failed`), the stage currently running (profile, pick regulations, pick sections, check applicability, verify), the documents it read, and a history of earlier runs. Polls `GET /runs/{id}` every second or two while running. When done, a "View findings" button leads to screen 3. If the run read an older set of documents than the current one, a "Results are out of date" banner offers "Run again".

### 3. Findings (`/cases/:caseId/runs/:runId/findings`), mock only at first

```
┌─ Summary: 190 requirements · 12 unmet · 31 met · 147 not assessable · 4 regulations ─┐
│ [Status ▾] [Regulation ▾] [Search…]                          Group by: Regulation ▾ │
├──────────────────────────────────────────────┬──────────────────────────────────────┤
│ Status  Regulation  §        Requirement      │  UN R48 §6.4.2.3 · v… · page 41      │
│ ● Unmet R48        6.4.2.3  A reversing…      │  Requirement (full text)             │
│ ○ N/A   R150       3.3.1.2  The markings…     │  Rationale                           │
│ ✓ Met   R48        5.1      …                 │  Evidence: spec.md › "PMMA…"         │
│                                               │  ┌────────────────────────────┐     │
│                                               │  │   cited page image (PDF)   │     │
│                                               │  └────────────────────────────┘     │
└──────────────────────────────────────────────┴──────────────────────────────────────┘
```

- Master/detail: a table (shadcn `table`) and a side panel (`sheet`) with the selected finding. The selected finding is in the URL (`?finding=G-0042`), so a result can be shared and the browser back button works.
- Summary cards at the top double as status filters.
- Filters and search are client-side; 190 rows need no server paging. If a case produces thousands, move filtering behind the API (the contract below already accepts the same query params).
- The status colours are never the only signal: each status has an icon and a label.
- Coverage: a collapsible section lists profile items for which nothing was found ("no applicable provision found"), as in the root proposal A6.

## Frontend architecture

The goal is that adding the real backend, or a new screen, touches one folder.

**1. Feature folders.** Each screen owns its components and hooks. Shared things stay shared.

```
src/frontend/src/
  app/
    router.tsx                  # routes, layout
    app-sidebar.tsx             # workflow nav; Analysis/Findings enabled when data exists
  components/
    ui/                         # shadcn (generated)
    status-badge.tsx            # DocumentStatus, RunStatus, FindingStatus → badge
    pdf-page-image.tsx          # cited page image with loading/error state
  features/
    documents/                  # iteration 1
      documents-page.tsx  upload-dropzone.tsx  document-table.tsx
      document-preview-dialog.tsx  use-documents.ts
    analysis/                   # mock first
      analysis-page.tsx  run-progress.tsx  run-history.tsx  use-run.ts
    findings/                   # mock first
      findings-page.tsx  findings-table.tsx  finding-detail-sheet.tsx
      findings-summary.tsx  use-findings.ts
  lib/
    api/
      types.ts                  # domain types + the ApiClient interface (the contract)
      http.ts                   # real implementation (fetch; XHR for upload progress)
      mock/                     # mock implementation + fixtures
      index.ts                  # exports `api`, chosen by VITE_USE_MOCK
    documents.ts                # allow-list, size limit, validate, formatBytes
    utils.ts
```

**2. One typed seam to the backend.** Components never call `fetch`. They call hooks in `features/*`, which call `api` from `lib/api`. The `ApiClient` interface in `types.ts` is the single definition of the contract. Switching to the real backend is changing one env var, plus fixing whatever the mock hid.

**3. Server state through TanStack Query, UI state through React.** Document lists, runs and findings are server state: they need caching, refetch after upload or delete, and polling while a run is `running`. TanStack Query does this with less code than hand-written effects. Selected row, open dialog, and active filters are local state or URL params. No global store (Redux, Zustand) is needed.

**4. React Router.** There are now three pages and shareable URLs (`runId`, `finding`), so a router is justified. Use `react-router`.

New dependencies for the team to approve (neither is a UI library): `@tanstack/react-query`, `react-router`.

**5. A mock that is hard to mislead.** Mock fixtures are built from the real dev case: `cases/dev-rear-lamp/expected.json` already has the shape of a finding (`id`, `text`, `source.{regulation, version, page, paragraph}`), and the mock adds `status`, `rationale` and `evidence` on top (a deterministic assignment, with a few `unmet` and `met` and the rest `not-assessable`). The mock run advances through the stages on timers. A `VITE_MOCK_FAILURES` flag makes uploads and runs fail occasionally so error states get built. Page images in the mock are a placeholder card, with one real page if easy.

## API contract

Prefix `/api`; the Vite dev server proxies it to `http://localhost:8000`. Everything marked (later) is implemented by the mock first.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/cases/{caseId}/documents` | list, newest first |
| `POST` | `/cases/{caseId}/documents` | multipart, field `file`; `201` document; `413` too large; `415` unsupported type |
| `GET` | `/documents/{id}/file` | original bytes, for preview and download |
| `DELETE` | `/documents/{id}` | `204` |
| `POST` | `/cases/{caseId}/runs` | (later) starts an analysis over the case's current documents; `202` with the run |
| `GET` | `/cases/{caseId}/runs` | (later) run history |
| `GET` | `/runs/{runId}` | (later) status and stage; the frontend polls this |
| `GET` | `/runs/{runId}/findings` | (later) query params `status`, `regulation`, `q` (optional; the UI filters client-side first) |
| `GET` | `/regulations/{reg}/pages/{n}.png` | (later) cited page image; `reg` is the label, version is implied by the finding |

```ts
// src/lib/api/types.ts
export type DocumentStatus = 'uploading' | 'uploaded' | 'failed'   // 'processing' | 'ready' if the backend needs them
export type RunStatus = 'queued' | 'running' | 'done' | 'failed'
export type FindingStatus = 'unmet' | 'met' | 'not-assessable'

export interface CaseDocument {
  id: string
  caseId: string
  name: string
  mimeType: string
  sizeBytes: number
  sha256?: string            // set by the server
  status: DocumentStatus
  progress?: number          // 0–100, client-side, only while uploading
  error?: string
  uploadedAt: string         // ISO 8601
}

export interface AnalysisRun {
  id: string
  caseId: string
  status: RunStatus
  stage?: string             // free text from the backend, e.g. 'Checking applicability'
  documentHashes: string[]   // sha256 of every document read; compared with the current list to detect staleness
  startedAt: string
  finishedAt?: string
  error?: string
}

export interface Citation {
  regulation: string         // 'UN R48'
  version: string            // base version label
  page: number
  paragraph?: string
}

export interface Evidence {
  documentId: string
  quote?: string
  location?: string          // 'page 3', 'row 12', free text
}

export interface Finding {
  id: string                 // 'G-0042'
  text: string               // atomic requirement
  source: Citation
  status: FindingStatus
  rationale?: string
  evidence?: Evidence[]
}

export interface ApiClient {
  documents: {
    list(caseId: string): Promise<CaseDocument[]>
    upload(caseId: string, file: File, opts: { onProgress(pct: number): void; signal: AbortSignal }): Promise<CaseDocument>
    remove(id: string): Promise<void>
    fileUrl(id: string): string
  }
  runs: {
    start(caseId: string): Promise<AnalysisRun>
    list(caseId: string): Promise<AnalysisRun[]>
    get(runId: string): Promise<AnalysisRun>
  }
  findings: {
    list(runId: string): Promise<Finding[]>
  }
  pageImageUrl(citation: Citation): string
}
```

`Finding` deliberately mirrors the output format in `cases/dev-rear-lamp/expected.json` (`text`, `source`), so the backend can emit its existing result and add `status`, `rationale` and `evidence` without a second format.

## Components (shadcn first)

Already in the repo: `button`. To add with the CLI (`npx shadcn@latest add …`): iteration 1: `card`, `badge`, `table`, `progress`, `alert-dialog`, `dialog`, `sonner`, `tooltip`, `sidebar`, `skeleton`. Mock screens: `sheet`, `select`, `input`, `tabs`, `collapsible`, `alert` (stale-results banner). `upload-dropzone` is the one custom primitive (shadcn has none), built on a native `<input type="file">` so it works from the keyboard.

## Build checklist

Iteration 1: documents (real contract, mock backend)

- [ ] Vite proxy for `/api`; `.env.example` with `VITE_USE_MOCK=true`.
- [ ] Add `react-router` and `@tanstack/react-query` (after approval); add the shadcn components for iteration 1.
- [ ] `lib/api/types.ts` (full contract above), `lib/documents.ts`, mock documents implementation, `index.ts`.
- [ ] `app/` router and sidebar shell; replace the Vite starter `App.tsx`/`App.css`.
- [ ] `features/documents/`: dropzone, table, status badge, preview dialog (images, PDF; text/markdown as plain text), delete confirmation, all states.
- [ ] `npm run lint` and `npm run build` pass.

Iteration 2: results (mock only)

- [ ] Mock runs and findings from `expected.json`; staleness detection by `documentHashes`.
- [ ] `features/analysis/`: run progress with polling, history, stale banner.
- [ ] `features/findings/`: summary cards as filters, table with filters and search, detail sheet with citation, rationale, evidence and page image; selected finding in the URL.
- [ ] Walk through with the team, adjust the contract, and only then hand it to whoever builds the backend endpoints.

Backend follow-up (not part of this proposal): the endpoints above in `src/backend/main.py`; a `document` table in the SQLite store (`id, case_id, name, mime, size, sha256, storage_path, uploaded_at`); analysis runs as background tasks writing `status` and `stage`; the assessment step for met/unmet.

## Risks and open questions

- **Met/unmet is new work for the backend.** See the section above. Decide with the backend side whether iteration 2 ships with `not-assessable` only.
- **Contract drift.** A convincing mock can hide gaps. Keep the contract only in `types.ts` (this file links to it, it does not copy changes), and review it with the backend before implementing.
- **Document roles.** The pipeline treats the spec (text) and the exploded view (vision) differently. v1 shows no role. Later options: infer from file type, or let the user tag each file.
- **Allow-list vs what the backend can parse.** The backend currently plans for `spec.md` and one PNG. Anything else uploads fine but is not understood until the profile step handles it. Shrink the allow-list if we do not want to promise more than that.
- **Long runs.** The pipeline can take minutes (up to about 200K tokens of regulations per case). Polling is enough locally. If stage-by-stage streaming is wanted later, server-sent events can replace the polling inside `use-run.ts` without changing the screens.
- **Many cases.** Needs a case list, create and switch flow, and a `cases` table. Types and URLs already allow it.
