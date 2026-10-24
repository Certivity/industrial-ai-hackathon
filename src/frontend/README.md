# regal.ai frontend

React 19 + TypeScript + Vite 8, Tailwind v4, shadcn/ui (style `base-nova`, built on `@base-ui/react`), Lucide icons, Recharts (through the shadcn `chart` component). Read `AGENTS.md` for the conventions (shadcn first, no extra UI libraries, lint and build after changes).

```
npm install
npm run dev      # http://localhost:5173
npm run lint
npm run build    # tsc -b && vite build
```

This README is the working memory for the frontend. Keep it current when behaviour changes.

## Product (stateless demo)

regal.ai checks a car component's technical documentation against UN regulations. The app keeps no state: the user submits documents, the FastAPI backend returns the **unmet requirements** (with reasoning), and nothing is stored. Regulation PDFs are retrieved and indexed by the backend; the frontend never touches them. The root `proposal.md` describes the backend pipeline. `src/frontend/proposal.md` is outdated and will be deleted, so ignore it.

## Navigation and routing

A floating glass "island" nav (`components/app-header.tsx`, fixed at the top centre of every page) with the text logo "regal.ai" and three links: **Home**, **All Requirements**, **Assess Product**. Routing is a tiny hash router (`lib/use-route.ts`): `#/home` (default), `#/requirements`, `#/assess`. Navigating scrolls to the top. No `react-router`. Because the nav is `fixed`, inner pages start with `pt-24`; the landing hero starts under it.

## Pages

### Home (`features/home/`)

Landing page, props `{ onNavigate }`. Sections, one component each: `hero-section` (pill, gradient headline, CTAs to Assess / All Requirements, animated blurred blobs and a masked grid), `product-visual` (decorative glass "app window" mock of an assessment result, floating; content is sample data from the dev case, aria-hidden), `stats-strip` (real numbers from `cases/` via `use-home-stats.ts`, count-up on first view with `use-count-up.ts`, hides itself if loading fails), `how-it-works` (3 steps), `features-section` (cards), `cta-band`, `site-footer`. Only claims capabilities the product is meant to have (grounded citations, atomic requirements, version tracking, stateless); no fake logos, testimonials or metrics.

### All Requirements (`features/requirements/`)

Browse every requirement of a product. Data is read **directly from the repo's `cases/` folder** by `lib/cases.ts` (`import.meta.glob` over `cases/*/expected.json`, lazy, and `cases/*/spec.md` for the product name from the first heading, e.g. `# spec: Rear Lamp`). A new case folder with an `expected.json` appears in the product picker without code changes. `vite.config.ts` sets `server.fs.allow` to the repo root so Vite may read `cases/`.

`expected.json` shape: `{ requirements: [{ id, text, source: { regulation, version, page, paragraph } }] }`.

Filters (client-side, 190 rows in the dev case): product, text/ID search, regulation, version (options follow the chosen regulation), paragraph prefix (`6.4` matches `6.4.2.3`, not `16.4`). Table uses `table-fixed` with set column widths.

### Assess Product (`features/assess/`)

Upload flow: drop or browse multiple files (`file-dropzone.tsx`), review and remove them (`file-list.tsx`), "Submit documentation" -> spinner -> toast "Documentation submitted" -> results dashboard. Duplicate files (same name, size, modified time) are ignored. Errors show an error toast and keep the files. The upload view is `max-w-3xl`, the results view is wider.

**Results dashboard** (`features/assess/results/`, entry `assess-results.tsx`, props `{ result, fileCount, onReset }`):
- `results-header`: h1 "Assessment results" (receives focus on mount, since the submit button is gone), document count, "Assess another product" (resets files and state) and "Export JSON" (`export-json.ts`, downloads `result.unmet`).
- No unmet requirements: only an Alert "All regulations have been fulfilled".
- Otherwise: `summary-cards` (unmet count, regulations affected, requirements checked, share unmet; count-up via `use-count-up.ts`), `regulation-chart` (horizontal bar chart of unmet by regulation with the shadcn chart; clicking a bar or a chip filters the table; text alternative via aria-label), `unmet-table` + `unmet-row` (search, regulation filter, expandable rows with reasoning and citation, fixed column widths). `stats.ts` has the aggregation helpers.

**Backend call is a stub.** `assessDocuments(files)` in `lib/assess.ts` waits 1.2 s and returns mock data: `checked` = all requirements of the first case in `cases/`, and every 7th of them as "unmet" with an invented reason. Set `MOCK_SCENARIO` to `'clean'` in that file to get the "all fulfilled" state.

To wire the real backend, replace the body of that one function with `POST /api/assess` (`multipart/form-data`, field `files` repeated per file) returning `AssessResult { checked: number; unmet: UnmetRequirement[] }`. `UnmetRequirement` = `Requirement` plus optional `reasoning`. Add a Vite dev proxy for `/api` -> `http://localhost:8000` in `vite.config.ts` (not done yet). Analysis may be slow; a single long request with the spinner is the plan, switch to job ID + polling only if needed (inside `assessDocuments`). If `checked` could be smaller than `unmet.length`, the "share unmet" card would exceed 100%; keep the contract honest.

## Visual system (`src/index.css`)

- Neutral shadcn palette plus brand tokens: `--brand` (indigo) and `--brand-2` (blue), used as `text-brand`, `bg-brand`, `from-brand`, `to-brand-2`; chart colours `--chart-1..5` are brand tints. The app never sets `.dark`, so dark mode is not designed.
- Utilities: `glass` (translucent blurred surface, used by the nav island), `text-gradient` (animated brand gradient text).
- Animations (CSS only, no animation library): `animate-fade-up`, `animate-float`, `animate-blob`, `animate-shimmer`. `components/reveal.tsx` (`<Reveal delay={ms}>`) fades children in when they first scroll into view. A `prefers-reduced-motion` block disables motion; JS-driven motion checks `prefersReducedMotion()` from `lib/motion.ts`.

## Layout

```
src/
  App.tsx                    nav + route switch + <Toaster />
  components/app-header.tsx  glass island nav
  components/reveal.tsx      scroll-reveal wrapper
  components/ui/             shadcn (generated; eslint rule react-refresh/only-export-components is off here)
  features/home/             landing page sections
  features/requirements/     page, table, filter-select, filters.ts, use-requirements.ts
  features/assess/           upload page, file-dropzone, file-list
  features/assess/results/   dashboard (see above)
  lib/cases.ts               reads cases/ (types Requirement, Citation)
  lib/assess.ts              backend stub + AssessResult types
  lib/use-route.ts           hash router hook
  lib/motion.ts              prefersReducedMotion()
```

## Gotchas

- `html { scrollbar-gutter: stable }` in `index.css` stops the layout shifting when a page is too short to scroll.
- shadcn `SelectContent` defaults were changed to `alignItemWithTrigger=false`, `align="start"` so dropdowns open below the trigger.
- `tsconfig.app.json` has no `baseUrl` (deprecated in TS 6); the `@/` alias works through `paths`.
- shadcn components added so far: alert, badge, button, card, chart, input, select, skeleton, sonner, table, tabs. `tabs` is no longer used by the nav but is still installed.
- The build warns that the JS chunk exceeds 500 kB (Recharts). Fix by lazy-loading the results view if it matters.
- On narrow screens the unmet table scrolls horizontally inside its card (`min-w-4xl`); a stacked card layout would be better on mobile.
- The layout was checked by build, lint and code reading only; nobody has looked at the pages in a browser at 375 px yet. `text-gradient` ends in `--brand-2`, check its contrast on the headline.
- Nothing from the frontend is committed yet; check `git status`.

## Media wanted (optional)

The pages work without any image. Better results with: a real screenshot of the Assess results view (about 1600x1000 px, PNG/WebP) to replace the mocked window in `product-visual.tsx`; an abstract or product hero background (at least 2400 px wide, low contrast); a cut-out of a car component (`cases/dev-rear-lamp/exploded_view.png` could be cleaned up); an SVG logomark.

## Next

- Real `assessDocuments` and the dev proxy once the endpoint exists.
- Look at every page in a browser (desktop and 375 px) and tune spacing, contrast and motion.
- Mobile layout for the unmet table.
