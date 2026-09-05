"""Output filing — folder resolution and idempotency.

Covers the review finding of 2026-09-05 (P2): the unique constraint
`workspace_folders_sibling_name_uniq` is on
`(client_id, parent_folder_id, name)` and is NOT partial, so a
SOFT-DELETED sibling still occupies the name. The first version of
`ensure_child_folder()` looked up with `deleted_at IS NULL`, missed the
deleted row, INSERTed into a taken name, caught the unique violation,
re-read with the same `deleted_at IS NULL` predicate, found nothing and
returned **None** — which propagated as a missing parent folder: a
false success, or an output filed at the wrong level of the tree.
"""

from __future__ import annotations

from datetime import datetime, timezone

import asyncpg
import pytest

from runtime.workspace_filing import (
    date_folder_name,
    ensure_child_folder,
    is_valid_folder_name,
    order_folder_name,
    slugify,
)


# ── pure helpers ─────────────────────────────────────────────────────


def test_slug_is_path_safe_and_lowercased() -> None:
    assert slugify("KLEAR.ai Press Office – 2‑Page Spec").startswith(
        "klear-ai-press-office"
    )
    assert "/" not in slugify("a/b/c")
    assert slugify("") == "untitled"
    assert slugify("!!!") == "untitled"


def test_order_folder_name_carries_an_id_suffix() -> None:
    """Two work orders can share a title on the same day; without the id
    the second one's outputs land silently among the first one's."""
    a = order_folder_name("Weekly report", "d147a99e-4884-20fe-8bd0-0daf103bd")
    b = order_folder_name("Weekly report", "aa11bb22-4884-20fe-8bd0-0daf103bd")
    assert a != b
    assert a.endswith("_d147a99e")


def test_order_folder_name_survives_a_missing_work_order_id() -> None:
    assert order_folder_name("Ad hoc", "").endswith("_nowo")


def test_date_folder_is_utc_iso() -> None:
    assert date_folder_name(datetime(2026, 9, 5, 23, 30, tzinfo=timezone.utc)) == (
        "2026-09-05"
    )


@pytest.mark.parametrize("bad", ["", "  ", ".", "..", "a/b", "a\\b", "x" * 121])
def test_invalid_folder_names_are_rejected(bad: str) -> None:
    """Separators and traversal are rejected outright rather than
    sanitised into something the operator did not ask for."""
    assert is_valid_folder_name(bad) is False


@pytest.mark.parametrize("ok", ["Press Office", "2026-09-05", "A. Reports (2026)"])
def test_reasonable_folder_names_are_accepted(ok: str) -> None:
    assert is_valid_folder_name(ok) is True


# ── idempotency against soft deletes ─────────────────────────────────


class _FakeConn:
    """Stands in for asyncpg. `rows` is the sibling table."""

    def __init__(self, rows: list[dict] | None = None, raise_once: bool = False):
        self.rows = rows or []
        self.raise_once = raise_once
        self.inserted = 0
        self.revived: list[str] = []

    async def fetchrow(self, sql: str, *args):  # noqa: ANN001
        """Honours `deleted_at IS NULL` if the query carries it.

        This matters: the defect under test IS that predicate. A fake
        that matches on name alone returns the soft-deleted row either
        way, so the test passes whether the bug is present or not — it
        did, until reintroducing the defect failed to turn it red.
        """
        name = args[2]
        excludes_deleted = "deleted_at is null" in " ".join(sql.lower().split())
        for r in self.rows:
            if r["name"] != name:
                continue
            if excludes_deleted and r["deleted_at"] is not None:
                continue
            return r
        return None

    async def fetchval(self, sql: str, *args):  # noqa: ANN001
        if "INSERT INTO workspace_folders" in sql:
            # `workspace_folders_sibling_name_uniq` is NOT partial — a
            # soft-deleted sibling still holds the name, so an INSERT
            # over it raises. Modelling this is what makes the test able
            # to see the bug.
            if any(r["name"] == args[2] for r in self.rows):
                raise asyncpg.UniqueViolationError("duplicate key")
            if self.raise_once:
                self.raise_once = False
                # Concurrent creator won; make the row visible.
                self.rows.append({"id": "raced-id", "deleted_at": None,
                                  "name": args[2]})
                raise asyncpg.UniqueViolationError("duplicate key")
            self.inserted += 1
            return "new-id"
        return None

    async def execute(self, sql: str, *args):  # noqa: ANN001
        if "deleted_at = NULL" in sql:
            self.revived.append(args[0])


@pytest.mark.asyncio
async def test_existing_live_folder_is_reused_not_duplicated() -> None:
    conn = _FakeConn([{"id": "live-id", "deleted_at": None, "name": "Outputs"}])
    got = await ensure_child_folder(
        conn, client_id="c", parent_folder_id="p", name="Outputs",
        created_by_user_id="u",
    )
    assert got == "live-id"
    assert conn.inserted == 0


@pytest.mark.asyncio
async def test_soft_deleted_folder_is_revived_never_returns_none() -> None:
    """The regression. A deleted sibling holds the name; returning None
    here filed outputs at the wrong level."""
    conn = _FakeConn(
        [{"id": "dead-id", "deleted_at": "2026-08-01", "name": "Outputs"}]
    )
    got = await ensure_child_folder(
        conn, client_id="c", parent_folder_id="p", name="Outputs",
        created_by_user_id="u",
    )
    assert got == "dead-id"
    assert conn.revived == ["dead-id"]
    assert conn.inserted == 0


@pytest.mark.asyncio
async def test_absent_folder_is_created() -> None:
    conn = _FakeConn([])
    got = await ensure_child_folder(
        conn, client_id="c", parent_folder_id="p", name="2026-09-05",
        created_by_user_id="u",
    )
    assert got == "new-id"
    assert conn.inserted == 1


@pytest.mark.asyncio
async def test_concurrent_creator_race_re_reads_and_never_returns_none() -> None:
    """Two workers filing at the same instant: the loser must re-read,
    not fail the filing."""
    conn = _FakeConn([], raise_once=True)
    got = await ensure_child_folder(
        conn, client_id="c", parent_folder_id="p", name="2026-09-05",
        created_by_user_id="u",
    )
    assert got == "raced-id"

# ── one work order, one folder (E2E regression 2026-09-05) ───────────


class _ResolveConn(_FakeConn):
    """Adds `fetchval` support for the work-order title lookup."""

    def __init__(self, wo_title: str | None, **kw):
        super().__init__(**kw)
        self.wo_title = wo_title
        self.created_names: list[str] = []

    async def fetchval(self, sql: str, *args):  # noqa: ANN001
        low = " ".join(sql.lower().split())
        if "from work_orders" in low:
            return self.wo_title
        if "select id::text from workspace_folders" in low or (
            "from workspace_folders" in low and "select id::text" in low
        ):
            return "root-id"
        if "insert into workspace_folders" in low:
            self.created_names.append(args[2])
            self.rows.append({"id": f"id-{args[2]}", "deleted_at": None,
                              "name": args[2]})
            return f"id-{args[2]}"
        return None


@pytest.mark.asyncio
async def test_workflow_steps_all_land_in_one_folder() -> None:
    """A multi-step workflow calls the filing path once per step, each
    with its own step title ("Mark (draft)", "Hank (render)"). All of
    them must resolve to the SAME per-work-order folder.

    Regression: an end-to-end HTML work order produced two sibling
    folders — `…with-press-office-summa_b0d5b5a6` and
    `…summarizing-press-offic_b0d5b5a6` — because the folder name was
    slugged from the caller's title instead of the work order's.
    """
    from runtime.workspace_filing import resolve_filing_folder

    wo = "b0d5b5a6-c1bb-4ac8-8d8b-e85565eebe62"
    seen = set()
    for step_title in ("Mark (draft)", "Hank (render)", "Darla (qa)"):
        conn = _ResolveConn("E2E html landing page")
        folder = await resolve_filing_folder(
            conn,
            client_id="c",
            created_by_user_id="u",
            work_order_id=wo,
            title=step_title,
            now=datetime(2026, 9, 5, tzinfo=timezone.utc),
        )
        assert folder is not None
        # The per-order folder is the last one created.
        seen.add(conn.created_names[-1])
    assert len(seen) == 1, (
        f"one work order produced {len(seen)} folders: {sorted(seen)}"
    )
    assert seen.pop().endswith("_b0d5b5a6")


@pytest.mark.asyncio
async def test_caller_title_is_used_when_there_is_no_work_order() -> None:
    from runtime.workspace_filing import resolve_filing_folder

    conn = _ResolveConn(None)
    await resolve_filing_folder(
        conn,
        client_id="c",
        created_by_user_id="u",
        work_order_id=None,
        title="Ad hoc export",
        now=datetime(2026, 9, 5, tzinfo=timezone.utc),
    )
    assert conn.created_names[-1].startswith("ad-hoc-export")
