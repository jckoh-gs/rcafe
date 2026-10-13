---
paths:
  - "**/mobile/**"
  - "**/mobiles/**"
  - "**/mobile-*/**"
  - "**/*-mobile/**"
  - "**/*.dart"
---

# Mobile: Flutter (iOS + Android) + MVVM with Riverpod

One Flutter codebase targets both iOS and Android. A project may contain several mobile apps; each is
its own Flutter package and apps do not import from each other. Shared code across apps belongs in a
dedicated package, not in another app.

The pattern is Flutter's officially recommended app architecture: **MVVM** (View + ViewModel in the UI
layer) over a **Repository + Service** data layer, feature-first folders, and **Riverpod** as the DI and
state-management mechanism. Do not mix in other state managers (BLoC, GetX, MobX, setState-for-business-state).

## Stack
- Flutter (stable channel) + Dart 3, null safety, sound types. Pin the Flutter version (FVM or `.fvmrc`).
- State / DI: `flutter_riverpod` with `riverpod_annotation` + `riverpod_generator` (`@riverpod` Notifiers).
- Navigation: `go_router` (declarative, deep-link ready).
- Models: `freezed` + `json_serializable` — immutable, with `copyWith` and value equality.
- Networking: `dio` (or `http`) wrapped in a Service; backend contracts come from the backend's OpenAPI.
- Local storage: `drift` / `isar` for structured data, `flutter_secure_storage` for tokens/secrets,
  `shared_preferences` for non-sensitive flags only.
- Quality gate: `dart format`, `flutter analyze` (with `flutter_lints`), `dart run custom_lint`
  (riverpod_lint), `tool/check_layers.sh` (layer boundaries), and `flutter test` must pass before work is done.
  The Claude hook runs format, analyze, and the layer check; CI also runs custom_lint and tests. Set an app up
  with the `setup-quality-gates` skill, and fix violations rather than adding `// ignore` comments.

## Layout (per app, feature-first)

```
<mobile>/lib/
  main.dart / app.dart      # entry point, ProviderScope, MaterialApp.router, theme
  core/                     # cross-feature infrastructure — no feature/business knowledge
    routing/ theme/ config/ network/ storage/ error/ l10n/
  data/                     # shared data layer (used by several features)
    services/               # wrap one external source: REST client, platform channel, local DB, secure storage
    repositories/           # single source of truth per domain entity; expose domain models
    models/ (dto)           # API/DB data shapes (json_serializable); mapped to domain models in repositories
  domain/                   # domain models (freezed) + optional use cases; pure Dart
  features/
    <feature>/
      view/                 # screens and widgets (UI only)
      view_model/           # @riverpod Notifier/AsyncNotifier + immutable UI state
      (data/ domain/)       # feature-private repositories/models if not shared
  shared/                   # reusable dumb widgets (design system), extensions, utils
test/                       # mirrors lib/; integration_test/ for end-to-end flows
```

Match the existing layout if an app already differs; keep the same layer boundaries.

## Layers and responsibilities

| Layer | Contains | Knows about |
|---|---|---|
| View | Widgets, layout, animations, navigation calls | its ViewModel's state and methods |
| ViewModel | Screen state, presentation logic, user-action handlers | Repositories (and use cases) |
| Repository | Caching, offline logic, retries, mapping DTO → domain model | Services |
| Service | One raw data source, no business logic, stateless | the platform / network / DB |

## Mandatory rules

### 1. Dependency direction is one-way
- `View → ViewModel → (UseCase →) Repository → Service`. A layer never imports from a layer above it.
- Views never touch Repositories or Services; ViewModels never touch Services directly.
- Features do not import each other's `view/` or `view_model/`. Share via `domain/`, `data/`, `shared/`,
  or compose them in a higher-level screen/route.

### 2. Views are dumb
- Widgets render state and forward events (`ref.watch(vmProvider)` / `ref.read(vmProvider.notifier).doX()`).
- No business logic, no network/DB calls, no data mapping, no `async` orchestration in `build()` or widget callbacks.
- Prefer `const` constructors and small widgets over helper methods that return widgets. Use
  `ConsumerWidget` / `Consumer` scoped as narrowly as possible, and `select` to limit rebuilds.
- Use `StatelessWidget`; `StatefulWidget` only for ephemeral UI state (controllers, animations, focus).

### 3. ViewModels own screen state
- One `@riverpod` Notifier / AsyncNotifier per screen (or per cohesive piece of state), exposing a single
  immutable `freezed` state object (loading / data / error), not several loose fields.
- ViewModels are free of Flutter UI imports (`BuildContext`, `Widget`, `Navigator`, `ScaffoldMessenger`).
  One-off effects (navigation, snackbars) are modelled as state or events the View reacts to via `ref.listen`.
- Expose intent-named methods (`submitOrder`, `refresh`), not setters. State changes only inside the
  ViewModel, always by producing a new state object.
- Never block on I/O in the constructor/`build`; return `AsyncValue` and let the View handle loading/error.

### 4. Repositories are the single source of truth
- Repositories expose domain models and `Stream`/`Future` APIs; they hide whether data came from cache,
  network, or DB. DTOs never leak above the repository.
- Define each repository as an abstract class (interface) with an implementation, and provide it through
  Riverpod so tests can override it with a fake.
- Errors: Services throw; Repositories convert to typed failures (sealed class / `Result`); ViewModels map
  failures to UI state. No raw `DioException` in the UI.

### 5. Dependency injection only through Riverpod
- Construct Services, Repositories, and ViewModels via providers; no singletons, no `GetIt`, no
  `static` instances, no global mutable state.
- Keep providers `autoDispose` by default; use `keepAlive` only for app-lifetime state (auth session, config).

### 6. Cross-platform discipline
- Write platform-agnostic Dart by default. Platform-specific code goes behind a Service interface
  (platform channel, `Platform.isIOS` checks, or a federated plugin), never inline in Views/ViewModels.
- Use adaptive widgets (`.adaptive` constructors, `Theme.of(context).platform`) where iOS/Android conventions
  differ; do not fork whole screens per platform unless unavoidable.
- Every new plugin must support both iOS and Android; check this before adding it. Native config
  (`Info.plist` permission strings, `AndroidManifest.xml` permissions) changes together for both platforms.

### 7. Navigation, config, and secrets
- All routes are declared in `core/routing` with `go_router`; screens navigate by route name/typed route,
  not by pushing widgets directly.
- Environment values (API base URL, flavor) come from `--dart-define` / `--dart-define-from-file` through
  `core/config`; never hardcode them. Use Flutter flavors (`dev`/`staging`/`prod`) for iOS schemes and Android
  product flavors.
- Never ship secrets in the app binary or `--dart-define` values: they are extractable. Store user tokens in
  `flutter_secure_storage`; keep API secrets on the backend.

## Implementation guidelines
- Generated files (`*.g.dart`, `*.freezed.dart`) are committed or built consistently per project policy; never
  hand-edit them. Run `dart run build_runner build --delete-conflicting-outputs` after changing annotated code.
- Localize all user-visible strings through `l10n` (ARB files); no hardcoded UI text.
- Support accessibility: semantic labels, minimum 48dp tap targets, dynamic text scaling, light/dark theme.
- Handle all async states in the UI (loading, empty, error with retry, offline).
- Prefer composition over inheritance; keep widget files under ~300 lines and split by responsibility.

## Testing
- ViewModel and Repository unit tests with `ProviderContainer` + overridden fakes — these carry most of the
  coverage because logic lives there, not in widgets.
- Widget tests for Views with overridden ViewModel providers; golden tests for design-system widgets.
- `integration_test` for critical user flows, run on one iOS simulator and one Android emulator in CI.

Backend contracts are owned by the backend rules; mobile consumes them through Services only.
