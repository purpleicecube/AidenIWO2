# ADR-007 — Python toolchain: uv

Date: 2026-04-19
Status: Accepted (v0.1.1 — lockfile policy + dev-extras mandate added per CODEX Loop 1 Phase 1 review)
Deciders: AI, MD (per `IWO3_LOOP_1_PLAN_v0.1.0.md` §9), with CODEX revision

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
- CI **and** local commands use `uv sync --extra dev` per app (plain `uv sync` is disallowed for test/lint-critical paths — it omits the dev extras that `pytest`, `ruff`, and `mypy` need).
- Local dev runbook documents `uv run pytest`, `uv run uvicorn main:app`, etc.
- No `requirements.txt` files.

## Lockfile policy (CODEX revision)

- Every Python app commits its `uv.lock` file alongside `pyproject.toml`.
- CI and local `uv sync --extra dev` must run against the committed lockfile — never with `--upgrade` or `--no-lock` on shared paths.
- Lockfiles are regenerated intentionally by running `uv lock` and committing the result as part of a dep-bump PR.
- The Loop 1 acceptance gate includes a post-`npm ci` / post-`uv sync` diff check: if any tracked `uv.lock` or `package-lock.json` was modified during install, CI fails. (To be wired in a Loop 1 Phase 1.2 follow-up if not in Phase 1.1.)
- A Python app that legitimately cannot lock (e.g., a pure-placeholder `pyproject.toml` with zero runtime deps) documents the deferral in its README. Loop 1's `apps/console-streamlit` falls here until real pages ship in Loop 8.

## Revisit triggers

- uv ships a breaking change that destabilizes IWO3 CI for >1 week.
- Poetry or an equivalent gains a strictly better ecosystem fit (unlikely as of 2026-04).
