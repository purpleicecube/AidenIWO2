"""Workspace tool authorization + scratch-folder privacy.

Both findings below came from code review on 2026-09-05, not from a
test — because there were no tests for these tools at all. That absence
is the reason they shipped. These are the tests that should have caught
them.

P1 PRIVACY. `workspace_folders.owner_user_id` marks per-operator
scratch folders, made owner-only in Beta-1.5 ε.5 / Q11.
`GET /workspace/tree` filters on it; the RLS policy does NOT (it checks
`client_id` alone). The first cut of these tools queried by tenant only,
so Aiden could list a colleague's scratch folder, locate artifacts in
it, and create folders beneath it.

P1 AUTHORIZATION. `/aiden/chat` gates on `work_order:create`.
`execute_tool` performed a workspace mutation with no permission check,
while the equivalent route requires `workspace:write`. Every seeded role
holding `work_order:create` happens to hold `workspace:write` too, so
the matrix concealed it — a guard resting on a coincidence in the
permission table is not a guard.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import runtime.aiden_tools  # noqa: F401 — resolve the registry cycle
from runtime.aiden_tools import TOOL_REGISTRY


TOOLS_SRC = Path(__file__).parent.parent / "runtime" / "tools" / "workspace.py"
MUTATING_TOOLS = {"workspace_create_folder"}
READING_TOOLS = {"workspace_list_tree", "workspace_locate_output"}


# ── P1: authorization ────────────────────────────────────────────────


def test_folder_creation_requires_workspace_write() -> None:
    """The same permission `POST /workspace/folders` demands."""
    assert (
        TOOL_REGISTRY["workspace_create_folder"].required_permission
        == "workspace:write"
    )


@pytest.mark.parametrize("name", sorted(READING_TOOLS))
def test_workspace_reads_require_workspace_read(name: str) -> None:
    assert TOOL_REGISTRY[name].required_permission == "workspace:read"


def test_every_workspace_tool_declares_a_permission() -> None:
    """A new workspace tool added without one would inherit the chat
    route's `work_order:create` gate and nothing else."""
    missing = [
        n
        for n, t in TOOL_REGISTRY.items()
        if n.startswith("workspace_") and not t.required_permission
    ]
    assert missing == [], f"workspace tools with no permission gate: {missing}"


def test_execute_tool_enforces_the_declared_permission() -> None:
    """The field is inert unless `execute_tool` checks it before running
    the handler and denies loudly."""
    src = (
        Path(__file__).parent.parent / "runtime" / "aiden_tools.py"
    ).read_text(encoding="utf-8")
    assert "if tool.required_permission:" in src
    assert "_actor_has_permission" in src
    assert "permission_denied" in src
    assert "authz.denied" in src
    # The check must precede handler execution in source order.
    assert src.index("if tool.required_permission:") < src.index(
        "result = await tool.handler("
    )


def test_permission_check_denies_when_there_is_no_actor() -> None:
    """A tool that mutates must never run unattributed."""
    src = (
        Path(__file__).parent.parent / "runtime" / "aiden_tools.py"
    ).read_text(encoding="utf-8")
    fn = src[src.index("async def _actor_has_permission") :]
    fn = fn[: fn.index("\n\nasync def ") if "\n\nasync def " in fn else len(fn)]
    assert "if not user_id:" in fn and "return False" in fn


# ── P1: scratch-folder privacy ───────────────────────────────────────


def _sql_strings(src: str) -> list[str]:
    """Every string literal in the module, f-strings REASSEMBLED.

    An f-string is a `JoinedStr` whose literal halves are separate
    `Constant` nodes, so walking Constants alone chops a query at its
    first `{placeholder}` — which is precisely how the first version of
    this test read `... FROM artifacts a WHERE` and concluded the query
    was unguarded. Reassemble, marking each interpolation, so a query is
    examined as written.
    """
    out: list[str] = []
    tree = ast.parse(src)
    joined_parts: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            pieces: list[str] = []
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    joined_parts.add(id(v))
                    pieces.append(v.value)
                else:
                    pieces.append("{interpolated}")
            out.append(" ".join("".join(pieces).split()))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in joined_parts
        ):
            out.append(" ".join(node.value.split()))
    return out


def _folder_queries(src: str) -> list[str]:
    """Every SQL string in the module that reads `workspace_folders`."""
    return [
        s
        for s in _sql_strings(src)
        if re.search(r"\bfrom\s+workspace_folders\b", s, re.I)
    ]


def test_every_folder_query_filters_on_owner() -> None:
    """The load-bearing assertion. A folder query without the owner
    predicate exposes another operator's scratch space — RLS will not
    catch it, because RLS only checks the tenant."""
    src = TOOLS_SRC.read_text(encoding="utf-8")
    queries = _folder_queries(src)
    assert queries, "no folder queries found — has the module moved?"
    unfiltered = [q for q in queries if "owner_user_id" not in q]
    assert unfiltered == [], (
        "workspace_folders query without an owner_user_id predicate:\n"
        + "\n".join(q[:160] for q in unfiltered)
    )


def test_artifact_lookup_is_gated_on_folder_visibility() -> None:
    """An artifact inherits its folder's visibility — a document filed
    in someone else's scratch folder must not be locatable."""
    src = TOOLS_SRC.read_text(encoding="utf-8")
    artifact_queries = [
        s
        for s in _sql_strings(src)
        if re.search(r"\bfrom\s+artifacts\b", s, re.I)
    ]
    assert artifact_queries, "no artifact queries found"
    # One artifact query interpolates a separately-built WHERE clause,
    # so the predicate is not inside its own literal. Accept that form
    # ONLY if the builder itself carries the ownership constraint —
    # checked immediately below, so neither path can slip through.
    for q in artifact_queries:
        assert "owner_user_id" in q or "{interpolated}" in q, (
            "artifact query does not constrain on folder ownership: " + q[:160]
        )
    flat = " ".join(src.split())
    assert (
        'where = (' in src or "where = " in src
    ), "expected a composed WHERE clause in _locate_output"
    # The composed clause must gate on folder visibility.
    assert re.search(
        r"EXISTS \(SELECT 1 FROM workspace_folders f.*?owner_user_id",
        flat,
    ), "composed artifact WHERE clause does not gate on folder ownership"


def test_owner_predicate_matches_the_route_it_mirrors() -> None:
    """Same shape as `GET /workspace/tree`: shared folders (NULL owner)
    stay visible to the tenant, owned ones only to their owner."""
    src = TOOLS_SRC.read_text(encoding="utf-8")
    assert re.search(
        r"owner_user_id IS NULL\s+OR\s+f\.owner_user_id = \$\d+::uuid",
        " ".join(src.split()),
    ), "owner predicate is not the tenant-shared-OR-mine shape"
