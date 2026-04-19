# ADR-007 — Python toolchain: uv

Date: 2026-04-19
Status: Accepted
Deciders: AI, MD (per `IWO3_LOOP_1_PLAN_v0.1.0.md` §9)

## Context

IWO3 introduces Python via FastAPI (runtime API, channel gateway, render/adapter services) and Streamlit (operator console). A workspace-level Python toolchain is required from Loop 1 to pin interpreter version, manage virtual environments, install per-app dependencies from each `pyproject.toml`, and run CI reproducibly.

## Decision

Use **uv** as the IWO3 Python toolchain.

Interpreter pin: `.python-version` at repo root declares `3.11`.

Per-app dependency declaration: each Python app has its own `pyproject.toml` under `apps/<name>/`.

CI install: `uv sync` per app. Local dev: same.

## Rationale

- Single static binary; fast; resolves and installs dependencies in one pass.
- Reads `pyproject.toml` directly.
- Works with Alembic, FastAPI, Streamlit without adapters.
- GitHub Actions has a maintained setup action (`astral-sh/setup-uv@v3`).

## Alternatives considered

- **Poetry** — heavier, slower, less native to setup-python, harder for mixed venv layouts.
- **pip + venv** — minimal, but no lockfile, no reproducibility guarantees, no workspace awareness.
- **Hatch / Rye** — either overlap with uv or are less broadly adopted in 2026.

## Consequences

- Every Python app ships `pyproject.toml` with `[project.optional-dependencies] dev = [...]` for test/lint tooling.
- CI uses `astral-sh/setup-uv@v3` + `uv sync --extra dev` per app.
- Local dev runbook documents `uv run pytest`, `uv run uvicorn main:app`, etc.
- No `requirements.txt` files.

## Revisit triggers

- uv ships a breaking change that destabilizes IWO3 CI for >1 week.
- Poetry or an equivalent gains a strictly better ecosystem fit (unlikely as of 2026-04).
