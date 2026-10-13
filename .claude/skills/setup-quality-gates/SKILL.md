---
name: setup-quality-gates
description: Set up linters that mechanically enforce the architecture rules for one backend (FastAPI hexagonal - ruff, mypy strict, import-linter), one frontend (React FSD - Steiger, ESLint, tsc), or one Flutter mobile app (MVVM - flutter analyze, riverpod_lint, layer check). Use when the user asks to set up, add, or fix linting, type checking, or architecture enforcement for a backend, frontend, or mobile directory, or when a new backend/frontend/mobile app is added to the project.
argument-hint: "[backend-frontend-or-mobile-dir]"
---

# Set up quality gates for a backend, frontend, or mobile app

The repo-level pieces are already shared by every backend, frontend, and mobile app and need no per-directory setup:
- `.claude/hooks/quality-gate.sh` (wired in `.claude/settings.json`): after each edit runs ruff / eslint /
  dart format on the file; before Claude finishes runs mypy + import-linter / typecheck + Steiger /
  flutter analyze + `tool/check_layers.sh` for touched directories.
- `.github/workflows/quality.yml`: discovers configured directories and runs the same checks in CI.

This skill adds the per-directory config those two pick up. Both only check a directory once its tools are
installed and configured, so nothing changes for directories that are not set up yet.

## 1. Pick the target
Arguments: `$ARGUMENTS`. If no directory was given, list candidates (`pyproject.toml` / `package.json`
roots under `backend`, `*-backend`, `frontend`, `*-frontend`, `mobile`, `*-mobile`, `apps/*`, `services/*`, ...) and ask which. A `pubspec.yaml` root is a mobile app.
Set up one directory at a time.

## 2a. Backend (Python)
1. Find the top-level package (the directory holding `domain/`, e.g. `app` or `src/<name>`).
2. Merge [assets/backend/pyproject.quality.toml](assets/backend/pyproject.quality.toml) into the backend's
   `pyproject.toml`:
   - Replace `app` with the real package name in `root_package`, `layers`, `source_modules`, and mypy `files`
     (for a `src/` layout use `files = ["src"]`).
   - Map `layers` to the actual layout (e.g. `infrastructure` instead of `adapters`). Keep the direction
     entrypoint → adapters → application → domain.
   - If `application/` exists, add it to the forbidden contract's `source_modules`.
   - If a `[tool.ruff]` / `[tool.mypy]` section already exists, merge instead of duplicating, and ask before
     loosening or tightening rules the team already chose.
3. Install dev tools in the backend's own environment: `uv add --dev ruff mypy import-linter`
   (no uv: install into `.venv` so the hook finds `.venv/bin/*`).
4. Run `ruff format --check .`, `ruff check .`, `mypy`, `lint-imports` and go to step 3.

## 2b. Frontend (React + FSD)
1. Use the package manager its lockfile indicates.
2. Install `steiger` and `@feature-sliced/steiger-plugin` as dev deps and copy
   [assets/frontend/steiger.config.ts](assets/frontend/steiger.config.ts) into the frontend root.
3. If there is no ESLint config, copy [assets/frontend/eslint.config.js](assets/frontend/eslint.config.js)
   and install `eslint @eslint/js typescript-eslint eslint-plugin-react-hooks globals`. If one exists, leave it.
4. Add scripts to `package.json`: `"lint:fsd": "steiger ./src"` and `"typecheck"`: `"tsc -b"` when
   `tsconfig.json` uses `references` (Vite default), otherwise `"tsc --noEmit"`.
5. Run eslint, typecheck, and `steiger ./src` and go to step 3.

## 2c. Mobile (Flutter + MVVM)
1. Confirm the app root (the directory with `pubspec.yaml` and `lib/`).
2. Copy [assets/mobile/analysis_options.yaml](assets/mobile/analysis_options.yaml) to the app root. If one
   exists, merge instead of replacing and ask before changing rules the team already chose.
3. Copy [assets/mobile/check_layers.sh](assets/mobile/check_layers.sh) to `<app>/tool/check_layers.sh` and
   `chmod +x` it. It enforces the View / ViewModel / Repository / Service / domain boundaries from the rules
   with plain grep, so it needs no extra packages. Adjust the directory names in it only if the app's layout
   deliberately differs from the rules.
4. Add dev dependencies: `flutter pub add --dev flutter_lints custom_lint riverpod_lint`. Check the versions
   resolve with the app's `flutter_riverpod`/`riverpod_annotation`; if not, ask before changing app dependencies.
5. Run `dart format --set-exit-if-changed .`, `flutter analyze`, `dart run custom_lint`, `tool/check_layers.sh`
   and `flutter test`, then go to step 3. (The hook runs analyze + layer check; CI also runs format, custom_lint
   and tests. `flutter test` is not run by the hook because it is too slow.)

## 3. Report existing violations
A codebase that predates the rules usually fails at first. List the violations grouped by tool and ask the
user whether to fix them now. Do not make large refactors unasked, and never make checks pass by adding
ignores, `# type: ignore`, `eslint-disable`, or by deleting contracts or rules.
