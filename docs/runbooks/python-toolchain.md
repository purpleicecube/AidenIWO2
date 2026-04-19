# Python Toolchain Runbook (uv)

Per ADR-007. This file lives in the IWO3 worktree as the authoritative reference for common uv operations.

## Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Pin interpreter

`.python-version` at repo root declares `3.11`. uv will use this automatically when operating from any subdirectory of the repo.

## Per-app workflow

Each Python app has its own `pyproject.toml` under `apps/<name>/`. Run uv from the app directory.

```bash
cd apps/api-fastapi

# Install runtime + dev deps
uv sync --extra dev

# Run the app
uv run uvicorn main:app --reload --port 5500

# Run tests
uv run pytest

# Run a one-off
uv run python -c "import fastapi; print(fastapi.__version__)"

# Add a dep
uv add httpx
uv add --dev ruff

# Remove a dep
uv remove httpx
```

## Lockfile

`uv.lock` is generated beside each `pyproject.toml`. Commit it.

## CI

GitHub Actions uses `astral-sh/setup-uv@v3`. `uv sync` is idempotent and honors `uv.lock` for reproducible installs.

## Troubleshooting

- "Python not found": verify `.python-version` file at repo root and a matching interpreter is installed locally. `uv python install 3.11` will fetch one if needed.
- "package X not found": run `uv sync --extra dev` from inside the app directory; you may be in the wrong cwd.
