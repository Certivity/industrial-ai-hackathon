# regal.ai frontend

The web interface for regal.ai. It lets you browse the regulatory requirements of a product and submit technical documentation to check it against regulations.

Built with React 19, TypeScript, Vite, Tailwind CSS v4 and [shadcn/ui](https://ui.shadcn.com), with Lucide icons and Recharts for charts.

## Getting started

Requires Node.js 20 or newer.

```bash
npm install
npm run dev       # http://localhost:5173
```

| Script | What it does |
|---|---|
| `npm run dev` | Start the dev server with hot reload |
| `npm run build` | Type-check and build for production into `dist/` |
| `npm run preview` | Serve the production build locally |
| `npm run lint` | Run ESLint |

## What is in the app

| Page | Route | What it does |
|---|---|---|
| Home | `#/home` | Landing page with the product banner, an overview and calls to action |
| All Requirements | `#/requirements` | Browse and filter every requirement of a product, with its regulation, version, paragraph and page |
| Assess Product | `#/assess` | Upload documentation and see which requirements are not met |

The app is a stateless demo: nothing is stored between sessions, and it is meant to run on localhost only.

### Product data

The requirements browser reads straight from the repository's `cases/` folder. Each case is a folder containing:

- `expected.json` with `{ "requirements": [{ "id", "text", "source": { "regulation", "version", "page", "paragraph" } }] }`
- an optional `spec.md`, whose first heading (for example `# spec: Rear Lamp`) becomes the product name

Add a new case folder and it shows up in the product picker without any code change.

### Assessing a product

Drop one or more files on the Assess page and submit them. The results view shows summary figures, a chart of unmet requirements by regulation, and a searchable table where each row expands to show the reasoning. The results can be exported as JSON.

The backend endpoint does not exist yet, so the page currently uses a stub in `src/lib/assess.ts` that returns sample data after a short delay. To connect the real backend, replace the body of `assessDocuments()` in that file with a `POST /api/assess` request (multipart form data, one `files` field per file) that returns `{ checked, unmet }`, and add a Vite proxy for `/api` to `http://localhost:8000` in `vite.config.ts`.

## Project structure

```
src/
  App.tsx                  Page switching and the toast container
  components/
    app-header.tsx         Floating navigation bar
    reveal.tsx             Fade-in on scroll
    ui/                    shadcn/ui components (generated)
  features/
    home/                  Landing page sections
    requirements/          Requirements browser
    assess/                Upload page
    assess/results/        Results dashboard
  lib/
    cases.ts               Reads the cases/ folder
    assess.ts              Backend call (currently a stub)
    use-route.ts           Hash-based routing
    motion.ts              Reduced-motion helper
  assets/                  Images
```

Each feature folder owns its components. Shared code lives in `components/` and `lib/`.

## Development notes

- **Components:** use shadcn/ui first. Add one with `npx shadcn@latest add <name>` from this folder. See [AGENTS.md](AGENTS.md) for the coding conventions.
- **Routing:** a small hash router (`src/lib/use-route.ts`) handles the three pages, so no router library is needed.
- **Styling:** colours, glass and gradient utilities and the animations are defined in `src/index.css`. Animations are plain CSS and switch off when the user prefers reduced motion.
- **Hotspots on the home banner:** the dots over the car photo and their example regulations are placeholder content defined in `src/features/home/car-hotspots.tsx`. They are positioned as percentages of the photo, so re-place them if the image changes.
- **Select dropdowns:** the shadcn `Select` was edited so its menu opens below the trigger. Re-adding the component overwrites that change.

For design decisions, data contracts and the list of next steps, see [spec.md](spec.md).

## Troubleshooting

- **Blank page and an error like "does not provide an export named 'default'":** the dev server got out of sync after many quick file changes. Stop it, run `npm run dev` again and hard-reload the browser.
- **Build warns that a chunk is larger than 500 kB:** this comes from the charting library and is harmless for a local demo.
