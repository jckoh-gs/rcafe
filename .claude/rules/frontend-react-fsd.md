---
paths:
  - "**/frontend/**"
  - "**/frontends/**"
  - "**/frontend-*/**"
  - "**/*-frontend/**"
---

# Frontend: React + Feature-Sliced Design (FSD)

A project may contain several frontends. These rules apply to every one of them; each frontend has its
own FSD tree, and frontends do not import from each other. Shared code across frontends belongs in a
dedicated package, not in another frontend's `shared/`.

## Stack
- React with functional components and hooks.
- Keep UI declarative; isolate side effects in hooks or the `model` / `api` segments.

## FSD layers (per frontend)

```
<frontend>/src/
  app/       # providers, routing, global styles, app init
  pages/     # route-level composition
  widgets/   # large self-contained UI blocks composed of features/entities
  features/  # user interactions that deliver business value
  entities/  # business entities (user, order, ...)
  shared/    # reusable UI kit, utils, API client, config — no business/domain knowledge
```

Segments inside a slice: `ui`, `model`, `api`, `lib`, `config`.

## Mandatory rules
- Import direction is strictly downward: `app → pages → widgets → features → entities → shared`.
  A layer never imports from a layer above it.
- Slices on the same layer do not import each other (e.g. `features/a` must not import `features/b`).
  Compose them in a higher layer instead.
- Import a slice only through its public API (`index.ts`); never deep-import its internal files.
- Business logic lives in `features` or `entities`, never in `shared`.
- Put code in the smallest meaningful slice and segment.

## Implementation guidelines
- Keep components focused; split large components and extract reusable hooks.
- Read environment-specific values (API base URL, etc.) from build-time env vars via `shared/config`;
  never hardcode them. Build-time env vars end up in the public bundle, so never put secrets in them.

Deployment is handled by the `deploy-frontend` skill, not by these rules.
