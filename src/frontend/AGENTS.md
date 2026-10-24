# Frontend Instructions

## Component Library
- Use shadcn/ui as the default component library.
- Before creating a custom button, dialog, dropdown, tooltip, form control, or other common UI primitive, check whether shadcn/ui already provides it.
- Add shadcn/ui components using the project's configured CLI and conventions when possible.
- Customize existing components rather than replacing the design system with ad hoc implementations.
- Use Lucide React icons consistently.

## Design
- Aim for a clean, cohesive, modern SaaS aesthetic.
- Prefer clear page hierarchy, restrained colors, consistent spacing, and readable typography.
- Use cards, tables, dialogs, badges, and sidebars where they improve usability; do not add them decoratively.
- Avoid excessive gradients, shadows, animations, and unnecessary visual effects.
- Ensure interactive elements have clear hover, focus, disabled, and loading states.
- Use semantic HTML and accessible labels.

## Code Quality
- Use functional React components and TypeScript.
- Avoid `any` unless genuinely necessary.
- Follow existing component and file naming conventions.
- Keep components focused and avoid unnecessarily large files.
- Reuse shared UI components instead of duplicating implementations.
- Follow ESLint rules and run the configured lint and build scripts after changes.
- Do not install additional UI libraries when shadcn/ui already covers the requirement.