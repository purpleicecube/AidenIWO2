"""Enumerated coverage for the provider/credential cross-wire guard.

The point fix was Darla. This is the gate that makes it universal.

A config whose `provider` and `credential_ref` name different providers
saves cleanly and then returns HTTP 401 "Invalid API Key" on every
invoke — an error that blames the key, not the wiring. Guarding one
endpoint is not enough: the row reaches the database down four paths in
this module alone, and a path added next month would silently reopen
the hole.

DETECTION IS FAIL-SAFE, DELIBERATELY
A first cut of this gate asked "does this function's SQL mention
provider or credential_ref?" and got two answers wrong in opposite
directions: `delete_config` looked unsafe because those columns appear
in its RETURNING clause though it only sets `enabled = false`, and
`update_config` looked safe because it assembles its SET clause at
runtime so no literal names the columns at all. Reading a substring of
a SQL string is not reading the statement. So the rule inverted: a path
must be GUARDED unless it can be PROVEN never to write either column —
proof being a static SET clause that names neither. Anything dynamic is
unprovable and therefore must be guarded.

Non-Python writers, guarded where they live and listed here so the
inventory sits in one place:
  · `infra/local/seed-loader.ts` — `assertProviderCredentialPair()`
  · direct SQL / migrations — not guardable from the app; the rollback
    guard catches historical rows on their way back in.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


ROUTES = Path(__file__).parent.parent / "routes" / "llm.py"
GUARD = "_validate_provider_credential_pair"
GUARDED_COLUMNS = ("provider", "credential_ref")

# Every function in routes/llm.py that writes llm_configs, mapped to
# whether it is exempt from the guard. Exempt means "provably cannot
# write provider or credential_ref". Edit deliberately.
EXPECTED_WRITE_PATHS: dict[str, bool] = {
    "create_config": False,    # POST   /llm/configs
    "update_config": False,    # PATCH  /llm/configs/{id} — dynamic SET
    "delete_config": True,     # DELETE /llm/configs/{id} — sets enabled only
    "rollback_config": False,  # POST   /llm/configs/{id}/rollback
}


def _functions() -> dict[str, ast.AST]:
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    return {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _sql_literals(fn: ast.AST) -> list[str]:
    return [
        " ".join(n.value.split())
        for n in ast.walk(fn)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def _write_statements(fn: ast.AST) -> list[str]:
    return [
        s
        for s in _sql_literals(fn)
        if re.search(r"\b(insert into|update)\s+llm_configs\b", s, re.I)
    ]


def _assigned_columns(stmt: str) -> str | None:
    """The columns a statement actually WRITES, or None if unprovable.

    UPDATE → the text between SET and WHERE/RETURNING.
    INSERT → the parenthesised column list.
    Anything else (or a statement whose clause we cannot isolate) is
    unprovable, and unprovable means guarded.
    """
    if re.search(r"\bupdate\s+llm_configs\b", stmt, re.I):
        m = re.search(r"\bset\b(.*?)(?:\bwhere\b|\breturning\b|$)", stmt, re.I)
        return m.group(1) if m else None
    if re.search(r"\binsert into\s+llm_configs\b", stmt, re.I):
        m = re.search(r"\binsert into\s+llm_configs\s*\((.*?)\)", stmt, re.I)
        return m.group(1) if m else None
    return None


def _builds_sql_dynamically(fn: ast.AST) -> bool:
    """An f-string or .join() feeding a SET clause means the columns are
    decided at runtime — nothing static can prove what it writes."""
    for n in ast.walk(fn):
        if isinstance(n, ast.JoinedStr):
            for v in n.values:
                if isinstance(v, ast.Constant) and re.search(
                    r"\bupdate\s+llm_configs\b|\bset\b", str(v.value), re.I
                ):
                    return True
    return False


def is_exempt(fn: ast.AST) -> bool:
    """True only when every write is provably free of the two columns."""
    stmts = _write_statements(fn)
    if not stmts:
        return True
    if _builds_sql_dynamically(fn):
        return False
    for stmt in stmts:
        cols = _assigned_columns(stmt)
        if cols is None:
            return False
        if any(c in cols.lower() for c in GUARDED_COLUMNS):
            return False
    return True


def calls_guard(fn: ast.AST) -> bool:
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            if name == GUARD:
                return True
    return False


# ── the gate ─────────────────────────────────────────────────────────


def test_every_unexempt_write_path_calls_the_guard() -> None:
    """The load-bearing assertion. Add an endpoint that writes
    llm_configs without provably avoiding both columns, and without
    calling the guard, and this fails by name."""
    unguarded = [
        name
        for name, fn in _functions().items()
        if _write_statements(fn) and not is_exempt(fn) and not calls_guard(fn)
    ]
    assert unguarded == [], (
        f"llm_configs write path(s) may set {GUARDED_COLUMNS} without "
        f"calling {GUARD}(): {unguarded}. A cross-wired config saves "
        "cleanly and then 401s on every invoke."
    )


def test_write_path_inventory_has_not_drifted() -> None:
    """Catches a path added or renamed without updating this file — the
    failure mode where the gate above passes because the new function is
    simply never looked at."""
    found = {n for n, fn in _functions().items() if _write_statements(fn)}
    assert found == set(EXPECTED_WRITE_PATHS), (
        "llm_configs write paths changed. Added: "
        f"{sorted(found - set(EXPECTED_WRITE_PATHS))}; removed: "
        f"{sorted(set(EXPECTED_WRITE_PATHS) - found)}. Update "
        "EXPECTED_WRITE_PATHS and confirm the guard applies."
    )


@pytest.mark.parametrize(
    "fn_name", [n for n, exempt in EXPECTED_WRITE_PATHS.items() if not exempt]
)
def test_declared_guarded_paths_call_the_guard(fn_name: str) -> None:
    fn = _functions().get(fn_name)
    assert fn is not None, f"{fn_name} no longer exists in routes/llm.py"
    assert calls_guard(fn), f"{fn_name} does not call {GUARD}()"


@pytest.mark.parametrize(
    "fn_name", [n for n, exempt in EXPECTED_WRITE_PATHS.items() if exempt]
)
def test_declared_exempt_paths_are_still_provably_exempt(fn_name: str) -> None:
    """`delete_config` only flips `enabled`. If it ever starts writing
    provider or credential_ref — or starts building its SET clause
    dynamically — its exemption is no longer sound."""
    fn = _functions()[fn_name]
    assert is_exempt(fn), (
        f"{fn_name} is listed as exempt but can now write "
        f"{GUARDED_COLUMNS}. Guard it or re-prove the exemption."
    )


def test_rollback_is_guarded_because_history_predates_the_guard() -> None:
    """Rollback is the subtle one: a snapshot taken BEFORE the guard
    existed can carry a mismatched pair, and restoring it would sneak
    the bad state past create and update. This repo's own data contains
    exactly such a snapshot (darla_tier_2, 2026-09-05)."""
    assert calls_guard(_functions()["rollback_config"])


def test_seed_loader_guards_the_same_invariant() -> None:
    """The seeder runs on every fresh reset, so an unguarded seed ships
    a broken agent to every new environment."""
    loader = (
        Path(__file__).parents[3] / "infra" / "local" / "seed-loader.ts"
    ).read_text(encoding="utf-8")
    assert "function assertProviderCredentialPair" in loader
    assert "assertProviderCredentialPair(r)" in loader, (
        "seed-loader.ts defines the guard but never calls it per row"
    )
