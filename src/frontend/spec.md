# Frontend spec and working notes

Audience: engineers and AI assistants picking up work on `src/frontend`. This file is the single source of truth for decisions, contracts and current state. Read it together with `AGENTS.md` (coding conventions). The human-facing `README.md` is being rewritten separately and does not hold decisions. Last updated 2026-10-24.

Related: root `proposal.md` (backend pipeline, scoring, build phases). `src/frontend/proposal.md` is an outdated draft kept only until it is deleted; everything still useful from it is migrated here.

## 1. Product and scope

regal.ai checks a car component's technical documentation against regulations. The hackathon demo is **stateless** and **localhost only**:

1. The user submits documents (specs, exploded views, drawings, datasheets; each under about 100 KB).
2. The FastAPI backend returns the **unmet requirements** with reasoning. Nothing is stored; there are no accounts, cases, runs or history.
3. The frontend shows them in a dashboard.

Out of scope for the frontend: regulation PDFs (the backend retrieves and indexes them periodically), auth, multiple users, persistence, cloud storage.

### Decisions already made (do not reopen without a reason)

- **Documents go straight to a FastAPI endpoint** (`POST /api/assess`, `multipart/form-data`), not to a folder and not to S3. Reasons: a browser cannot write to `cases/`, so a backend endpoint would be needed anyway; saving then deleting adds cleanup and race conditions; the files are tiny; one request/response fits a stateless demo. The backend decides whether to use memory or a temp dir.
- **One long request with a spinner** is the plan for the analysis. Switch to job ID + polling only if runs get too slow, and only inside `assessDocuments` (the pages must not change).
- **Hash routing, no `react-router`**, no global state store, no data-fetching library. Three pages do not justify them. Revisit if the app grows beyond about five routes or needs shareable deep links.
- **No animation or extra UI library.** Motion is CSS only; charts use shadcn `chart` (Recharts).
- **Requirements browser reads `cases/` directly** from disk through Vite (`import.meta.glob`), not through the backend.

## 2. Current state

| Area | State |
|---|---|
| Nav island, hash router, three pages | done |
| Home: split banner with photo and hotspots, stats, showcase, how it works, features, CTA, footer | done (visuals not yet reviewed in a browser at 375 px) |
| All Requirements (reads `cases/*/expected.json`) | done |
| Assess: multi-file upload, submit, toast | done |
| Assess results dashboard (summary cards, chart, filterable table with reasoning, JSON export) | done, against mock data |
| Backend call | **stub** in `src/lib/assess.ts` |
| Vite dev proxy `/api` -> `http://localhost:8000` | not done |
| Tests | none; verification is `npm run lint` and `npm run build` |
| Git | frontend work is **uncommitted**; check `git status` |

## 3. Routing and layout

`lib/use-route.ts`: hash router, routes `home` (default), `requirements`, `assess` -> `#/home`, `#/requirements`, `#/assess`. `navigate()` scrolls to top. `components/app-header.tsx` is a **fixed floating glass nav island** (`top-4`, centred), so inner pages use `px-6 pt-24`; the Home hero goes under it. `App.tsx` switches on the route and mounts `<Toaster />` (sonner).

## 4. Data contracts

### 4.1 Cases (read by All Requirements and the home stats)

`cases/<case-id>/expected.json`: `{ requirements: [{ id, text, source: { regulation, version, page, paragraph } }] }`. Optional `cases/<case-id>/spec.md`: its first heading (`# spec: Rear Lamp`) is the product name; the folder name is the fallback. A new folder appears in the product picker with no code change. `lib/cases.ts` exports `Requirement`, `Citation`, `listCases()`, `loadRequirements(caseId)`. `vite.config.ts` sets `server.fs.allow` to the repo root so Vite may read `cases/`.

`source.version` is the **base** version label of the regulation, and `page` is the physical PDF page (see root `proposal.md`). Do not display or compute anything that contradicts that.

### 4.2 Assess backend (to implement on the backend side)

```
POST /api/assess
Content-Type: multipart/form-data, field "files" repeated once per file
-> 200 AssessResult
```

```ts
interface AssessResult {
  checked: number                    // requirements that were checked against the documents
  unmet: UnmetRequirement[]
}
interface UnmetRequirement extends Requirement {   // Requirement = { id, text, source: Citation }
  reasoning?: string                 // why the documents do not satisfy it
}
```

Errors: show a toast and keep the files (already implemented for thrown errors). The backend should answer `413` too large, `415` unsupported type, `5xx` with a message. Allowed types are not enforced on the frontend yet; the dropzone accepts anything. If a list is wanted: pdf, md, txt, png, jpg, jpeg, webp, csv, json, docx, xlsx, 50 MB per file, and the backend should check magic bytes, not extensions.

`checked` must be at least `unmet.length`; otherwise the "share unmet" card exceeds 100%.

To go live: replace the body of `assessDocuments(files)` in `lib/assess.ts` (keep the signature), and add the Vite proxy for `/api`. `MOCK_SCENARIO` only exists in the stub and goes away with it. The stub waits 1.2 s and returns every 7th requirement of the first case as unmet with an invented reason; `MOCK_SCENARIO = 'clean'` gives the "all fulfilled" state.

### 4.3 Future option: met and not-assessable (not built)

The backend pipeline (root `proposal.md`, A4) lists the requirements that **apply**; it does not decide whether the product **meets** them, and a spec often has no evidence either way. If the backend later reports more than unmet, extend with a status per finding: `unmet | met | not-assessable`, plus `evidence?: { document, quote?, location? }[]`. `not-assessable` must never be shown as failed or passed; it is a to-do ("provide a test report"). Today the UI only knows unmet. Showing met ones was floated for visibility; do it through this status, not a second list.

## 5. Pages and components

### Home (`features/home/`)

`HomePage({ onNavigate })` composes: `hero-section`, `stats-strip`, `product-showcase`, `how-it-works`, `features-section`, `cta-band`, `site-footer`; shared `section-heading`, `use-count-up`, `use-home-stats`.

- **Hero** is a split banner: tinted text panel (slogan "Compliance that doesn't slow you down", CTAs to Assess and All Requirements) and the photo `src/assets/mercedes-in-motion.jpg`, fading into the panel from `lg` up, stacked on mobile.
- **Hotspots** (`car-hotspots.tsx`): pulsing dots over the photo; each opens a shadcn popover with a part name and **hardcoded, illustrative** example regulations plus the line "Illustrative example, not an assessment of this vehicle". Keep that disclaimer. Verify the UN regulation numbers and titles before a demo. Dot positions are percentages of the photo; the photo wrapper has `aspect-[1200/795]` so dots stay on their parts. If the photo changes, re-place the dots and update the ratio. The photo shows a car front while the dev case is a rear lamp; a rear photo would match better.
- **Stats strip** shows real numbers from `cases/` (requirement count, regulation count, product count) with a count-up; it hides itself if loading fails.
- **Product showcase** uses `product-visual.tsx`, a decorative glass mock of a result (aria-hidden) with sample rows from the dev case, all "Unmet".
- Content rule: only claim capabilities the product is meant to have (grounded citations, atomic requirements, version tracking, stateless). No fake logos, testimonials or metrics.

### All Requirements (`features/requirements/`)

`requirements-page`, `requirements-table` (table-fixed, set column widths so columns stay even), `filter-select`, `filters.ts`, `use-requirements.ts`. Filters are client-side (190 rows): product, text/ID search, regulation, version (options follow the chosen regulation), paragraph prefix (`6.4` matches `6.4.2.3`, not `16.4`), clear button, "Showing N of M". States: loading skeleton, error, no match. If a `cases` file lacks a `requirements` list the page shows an error.

### Assess (`features/assess/`)

Upload: `file-dropzone`, `file-list`, `assess-page`. Duplicates (same name, size, modified time) are ignored; the input is reset so the same file can be re-added. Submit disabled with no files; spinner while submitting. The upload view is `max-w-3xl`, the results view `max-w-7xl`.

Results (`features/assess/results/`, entry `assess-results.tsx`, props `{ result, fileCount, onReset }`): `results-header` (h1 takes focus on mount; "Assess another product" resets; "Export JSON" downloads `unmet`), `summary-cards` (unmet, regulations affected, checked, share unmet; count-up), `regulation-chart` (horizontal bars, click a bar or chip to filter the table; `role="img"` with an aria-label listing the counts), `unmet-table` + `unmet-row` (search, regulation filter, expandable rows with reasoning, fixed column widths), `stats.ts` (aggregations). Zero unmet shows only the Alert "All regulations have been fulfilled".

## 6. Visual system (`src/index.css`)

- shadcn neutral palette plus brand tokens: `--brand` (indigo) and `--brand-2` (blue); use `text-brand`, `bg-brand`, `from-brand`, `to-brand-2`. `--chart-1..5` are brand tints. `.dark` is never applied, so dark mode is not designed.
- Utilities: `glass` (blurred translucent surface, used by the nav), `text-gradient` (animated brand gradient text; its blue end is only about 3:1 against white, keep it for large text).
- Animations (CSS): `animate-fade-up`, `animate-float`, `animate-blob`, `animate-shimmer`. `components/reveal.tsx` (`<Reveal delay={ms}>`) reveals on first scroll into view. A `prefers-reduced-motion` block disables motion; JS-driven motion must check `prefersReducedMotion()` from `lib/motion.ts` (the Recharts bar animation does).
- Aesthetic: clean modern AI-SaaS, restrained; no heavy shadows, no emoji, text-only logo "regal.ai" (the `.ai` part is `text-brand`).

## 7. Conventions and gotchas

Follow `AGENTS.md` (shadcn first, Lucide icons, TypeScript without `any`, lint and build after changes). In addition:

- Files are kebab-case; one focused component per file; features own their folder, shared code lives in `components/` and `lib/`.
- shadcn is configured as `base-nova` on `@base-ui/react`. Add components with `npx shadcn@latest add <name> -y` from `src/frontend`. Installed: alert, badge, button, card, chart, input, popover, select, skeleton, sonner, table, tabs (tabs is currently unused). Generated `components/ui` files import `cn` from the `cn` package; leave that.
- `SelectContent` was edited to default `alignItemWithTrigger=false`, `align="start"` so dropdowns open below the trigger. Re-adding the select component overwrites this.
- `eslint.config.js` turns off `react-refresh/only-export-components` under `src/components/ui`.
- `tsconfig.app.json` has no `baseUrl` (deprecated in TS 6); the `@/` alias works through `paths`.
- `html { scrollbar-gutter: stable }` prevents sideways layout shifts between short and long pages.
- A blank page with "does not provide an export named 'default'" in the console was a stale Vite dev server after files changed rapidly; restart `npm run dev` and hard-reload.
- Tooling: in the Bash tool, shell heredocs containing apostrophes in the text fail to parse. Write files with the Write/Edit tools. Use a temporary dev server only briefly and stop it afterwards.
- Verification is lint + build only. Nobody has checked the app in a browser at 375 px; the build warns the JS chunk exceeds 500 kB (Recharts), fix by lazy-loading the results view if it matters.
- The unmet table scrolls horizontally on narrow screens (`min-w-4xl`); a stacked card layout would be better on mobile.

## 8. Next steps

1. Implement `POST /api/assess` on the backend and switch `assessDocuments` to it; add the Vite `/api` proxy.
2. Review every page in a browser (desktop and 375 px); tune spacing, contrast and the hotspot positions.
3. Decide on an allowed-file-type list and enforce it in the dropzone and on the backend.
4. Mobile layout for the unmet table; lazy-load the results view.
5. Optional: met / not-assessable statuses (section 4.3); a rear-view hero photo; a real screenshot of the results view for the showcase, an SVG logomark.
6. Delete `src/frontend/proposal.md` (the README is already rewritten for human readers; keep decisions in this file, not there).
7. Commit the frontend work.
