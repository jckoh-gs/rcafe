---
paths:
  - "**/backend/**"
  - "**/backends/**"
  - "**/backend-*/**"
  - "**/*-backend/**"
---

# Backend: Python FastAPI + Hexagonal Architecture (Ports and Adapters)

A project may contain several backends. These rules apply to every one of them; treat each backend
directory as its own self-contained hexagon and do not import across backends.

## Stack
- Python + FastAPI, async-first.
- Pydantic v2 for inbound/outbound schemas at adapter boundaries.
- Static analysis is a quality gate: code must pass `mypy` (strict) and `ruff` before it is done.

## Layout (per backend)

```
<backend>/app/
  domain/          # models.py, services.py, ports.py — pure Python, no framework imports
  application/     # use cases orchestrating domain services (optional for small services)
  adapters/
    inbound/http/          # FastAPI routers, Pydantic request/response schemas
    outbound/persistence/  # SQLAlchemy/asyncpg repository implementations
    outbound/clients/      # external API clients (httpx, etc.)
  main.py          # composition root: build adapters, wire them into services via Depends
```

Match the existing layout if a backend already differs; keep the same layer boundaries.

## Mandatory rules

### 1. Domain is isolated from frameworks
- `domain/` must never import `fastapi`, `starlette`, `sqlalchemy`, `pydantic`, DB drivers, HTTP clients,
  or anything under `adapters/`.
- Domain depends only on domain models, value objects (plain classes / `dataclass`), and port interfaces.
- Why: business rules must survive a change of web framework, ORM, or transport.

### 2. Persistence goes through repository ports
- No SQL or ORM calls inside domain or application services.
- Define repository interfaces as `typing.Protocol` or `abc.ABC` in `domain/ports.py`.
- Implement them in `adapters/outbound/`. Swapping PostgreSQL for MongoDB or an in-memory fake must not
  change service code. Tests for services use in-memory fakes of the ports.

### 3. Typed boundaries
- Type hints on every function signature, including return types.
- Validate all inbound JSON with Pydantic v2 models in `adapters/inbound/`; never pass raw `dict`s inward.
- Map Pydantic schemas / ORM rows to domain models at the adapter boundary, in both directions.
  Domain models are not Pydantic models and are never returned directly as API responses.

### 4. Async I/O
- Endpoints and outbound adapters are `async def`; use async drivers/clients (`asyncpg`, async SQLAlchemy,
  `httpx.AsyncClient`).
- No blocking calls in request paths. Unavoidable blocking work goes behind a port and runs via
  `asyncio.to_thread` or a worker, never inline in an endpoint.

## Dependency direction
- adapters → application → domain. Never the reverse.
- Side effects (DB, network, clock, randomness, filesystem) live behind ports.
- Dependency wiring happens only in the composition root (`main.py` / FastAPI `Depends` providers),
  not inside services.
