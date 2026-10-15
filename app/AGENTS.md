<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## Naming

Component files are PascalCase and named after their main export (`MoveMenu.tsx` exports `MoveMenu`). Hooks are camelCase `.ts` files with a `use` prefix (`useJobEvent.ts`) and live next to the feature's other modules, not inside `components/`. Other modules are camelCase (`apiClient.ts`). Single-word files stay lowercase (`types.ts`, `api.ts`). Folders are kebab-case. Components use named exports. Only Next.js route files (`page.tsx`, `layout.tsx`, `error.tsx`) use default exports. shadcn files in `src/components/ui/` stay kebab-case so `npx shadcn add` keeps working. `npm run lint` enforces this with `eslint-plugin-check-file`, except for `src/app/` and `src/components/ui/`.
