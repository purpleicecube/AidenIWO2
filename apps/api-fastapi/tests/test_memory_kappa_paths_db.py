"""Loop Kappa — Memory V1.5 path/filename/folder-listing integration.

Live DB tests for the new assembler CTEs (path_hits, filename_hits)
and the folder_listing follow-up query. Skips when IWO3_DATABASE_URL
is unset.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
import pytest

from memory import memory_context_builder
from memory.assembler import fetch_memory_inputs
from memory.intent_parser import ContextIntent
from memory.cache import clear_all_caches


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


@pytest.fixture
def db_url() -> str:
    return os.environ["IWO3_DATABASE_URL"]


async def _open_tenant_conn(
    db_url: str,
    *,
    client_id: str,
    user_id: str,
) -> asyncpg.Connection:
    conn = await asyncpg.connect(db_url)
    await conn.execute("SET LOCAL ROLE iwo3_app")
    await conn.execute(
        f"SET LOCAL app.current_client_id = '{client_id}'"
    )
    return conn


async def _insert_test_folder_and_artifact(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    folder_name: str,
    artifact_filename: str,
    artifact_text: str,
) -> tuple[str, str]:
    """Insert a tenant-shared workspace folder + one artifact under it.
    Returns (folder_id, artifact_id). Caller is responsible for
    cleanup (use a transaction + rollback)."""
    folder_id = str(uuid.uuid4())
    artifact_id = str(uuid.uuid4())
    # Use the seeded operator for the active tenant as creator —
    # client membership matters less than NOT NULL satisfaction here.
    creator_id = (
        KLEAR_OPERATOR if client_id == KLEAR_CLIENT
        else "00000000-0000-4000-8000-000002000003"
    )
    await conn.execute(
        """
        INSERT INTO workspace_folders (id, client_id, name, parent_folder_id, owner_user_id, created_by_user_id)
        VALUES ($1::uuid, $2::uuid, $3, NULL, NULL, $4::uuid)
        """,
        folder_id,
        client_id,
        folder_name,
        creator_id,
    )
    await conn.execute(
        """
        INSERT INTO artifacts
            (id, client_id, workspace_folder_id, filename, extracted_text,
             mime_type, source_type, content_class, storage_ref, created_by_user_id)
        VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5,
                'text/plain', 'upload', 'c1', 'inline://test', $6::uuid)
        """,
        artifact_id,
        client_id,
        folder_id,
        artifact_filename,
        artifact_text,
        creator_id,
    )
    return folder_id, artifact_id


# ── path_hits CTE ────────────────────────────────────────────────


@iwo3_db
def test_path_hits_resolves_named_folder(db_url: str) -> None:
    async def run() -> None:
        # Use the existing seed Klear workspace folder if present, but
        # to be self-contained insert our own and roll back at the end.
        bypass = await asyncpg.connect(db_url)
        try:
            tx = bypass.transaction()
            await tx.start()
            try:
                # Switch to tenant-scoped role so the WITH CHECK on
                # workspace_folders + artifacts validates inserts.
                await bypass.execute(
                    f"SET LOCAL app.current_client_id = '{KLEAR_CLIENT}'"
                )
                await bypass.execute("SET LOCAL ROLE iwo3_app")
                folder_id, art_id = await _insert_test_folder_and_artifact(
                    bypass,
                    client_id=KLEAR_CLIENT,
                    folder_name="kappa_test_folder",
                    artifact_filename="kappa_test_doc.md",
                    artifact_text="The kappa test pricing model is $7K/mo.",
                )

                intent = ContextIntent(paths=("kappa_test_folder",))
                inputs = await fetch_memory_inputs(
                    bypass,
                    client_id=KLEAR_CLIENT,
                    user_id=KLEAR_OPERATOR,
                    intake_text="show me kappa_test_folder",
                    intent=intent,
                )
                ids = [h["id"] for h in inputs.get("path_hits") or []]
                assert art_id in ids, (
                    f"path_hits did not surface seeded artifact {art_id}; "
                    f"got {ids}"
                )
            finally:
                await tx.rollback()
        finally:
            await bypass.close()

    asyncio.run(run())


@iwo3_db
def test_path_hits_excludes_other_tenant(db_url: str) -> None:
    async def run() -> None:
        # Insert "kappa_isolation" folder in FFAI; query as Klear with
        # the same path; assert it is NOT returned.
        bypass = await asyncpg.connect(db_url)
        try:
            tx = bypass.transaction()
            await tx.start()
            try:
                await bypass.execute(
                    f"SET LOCAL app.current_client_id = '{FFAI_CLIENT}'"
                )
                await bypass.execute("SET LOCAL ROLE iwo3_app")
                _, ffai_art = await _insert_test_folder_and_artifact(
                    bypass,
                    client_id=FFAI_CLIENT,
                    folder_name="kappa_isolation",
                    artifact_filename="ffai_doc.md",
                    artifact_text="FFAI confidential UNIQUE_LEAK_MARKER",
                )
                # Reset role / set to Klear to query.
                await bypass.execute("RESET ROLE")
                await bypass.execute(
                    f"SET LOCAL app.current_client_id = '{KLEAR_CLIENT}'"
                )
                await bypass.execute("SET LOCAL ROLE iwo3_app")

                intent = ContextIntent(paths=("kappa_isolation",))
                inputs = await fetch_memory_inputs(
                    bypass,
                    client_id=KLEAR_CLIENT,
                    user_id=KLEAR_OPERATOR,
                    intake_text="check kappa_isolation",
                    intent=intent,
                )
                ids = [h["id"] for h in inputs.get("path_hits") or []]
                assert ffai_art not in ids, (
                    f"FIREWALL VIOLATION: FFAI artifact {ffai_art} "
                    f"reached Klear path_hits"
                )
            finally:
                await tx.rollback()
        finally:
            await bypass.close()

    asyncio.run(run())


# ── filename_hits CTE ────────────────────────────────────────────


@iwo3_db
def test_filename_hits_resolves_filename(db_url: str) -> None:
    async def run() -> None:
        bypass = await asyncpg.connect(db_url)
        try:
            tx = bypass.transaction()
            await tx.start()
            try:
                await bypass.execute(
                    f"SET LOCAL app.current_client_id = '{KLEAR_CLIENT}'"
                )
                await bypass.execute("SET LOCAL ROLE iwo3_app")
                _, art_id = await _insert_test_folder_and_artifact(
                    bypass,
                    client_id=KLEAR_CLIENT,
                    folder_name="kappa_fn_test",
                    artifact_filename="kappa_unique_filename.pptx",
                    artifact_text="The body has no special markers.",
                )
                intent = ContextIntent(filename_terms=("kappa_unique_filename",))
                inputs = await fetch_memory_inputs(
                    bypass,
                    client_id=KLEAR_CLIENT,
                    user_id=KLEAR_OPERATOR,
                    intake_text="find kappa_unique_filename.pptx",
                    intent=intent,
                )
                ids = [h["id"] for h in inputs.get("filename_hits") or []]
                assert art_id in ids
            finally:
                await tx.rollback()
        finally:
            await bypass.close()

    asyncio.run(run())


# ── folder_listing follow-up query ───────────────────────────────


@iwo3_db
def test_folder_listing_returns_subfolders_and_files(db_url: str) -> None:
    async def run() -> None:
        bypass = await asyncpg.connect(db_url)
        try:
            tx = bypass.transaction()
            await tx.start()
            try:
                await bypass.execute(
                    f"SET LOCAL app.current_client_id = '{KLEAR_CLIENT}'"
                )
                await bypass.execute("SET LOCAL ROLE iwo3_app")

                # Insert: kappa_dir_root with one subfolder + one file.
                root_id = str(uuid.uuid4())
                sub_id = str(uuid.uuid4())
                file_id = str(uuid.uuid4())
                await bypass.execute(
                    """
                    INSERT INTO workspace_folders (id, client_id, name, parent_folder_id, owner_user_id, created_by_user_id)
                    VALUES ($1::uuid, $2::uuid, 'kappa_dir_root', NULL, NULL, $3::uuid)
                    """,
                    root_id, KLEAR_CLIENT, KLEAR_OPERATOR,
                )
                await bypass.execute(
                    """
                    INSERT INTO workspace_folders (id, client_id, name, parent_folder_id, owner_user_id, created_by_user_id)
                    VALUES ($1::uuid, $2::uuid, 'kappa_subdir', $3::uuid, NULL, $4::uuid)
                    """,
                    sub_id, KLEAR_CLIENT, root_id, KLEAR_OPERATOR,
                )
                await bypass.execute(
                    """
                    INSERT INTO artifacts
                        (id, client_id, workspace_folder_id, filename, extracted_text,
                         mime_type, source_type, content_class, storage_ref, created_by_user_id)
                    VALUES ($1::uuid, $2::uuid, $3::uuid, 'kappa_listing_file.md', 'body',
                            'text/plain', 'upload', 'c1', 'inline://test', $4::uuid)
                    """,
                    file_id, KLEAR_CLIENT, root_id, KLEAR_OPERATOR,
                )

                intent = ContextIntent(
                    paths=("kappa_dir_root",),
                    wants_folder_listing=True,
                )
                inputs = await fetch_memory_inputs(
                    bypass,
                    client_id=KLEAR_CLIENT,
                    user_id=KLEAR_OPERATOR,
                    intake_text="what's in kappa_dir_root?",
                    intent=intent,
                )
                listing = inputs.get("folder_listing")
                assert listing is not None
                assert listing["root_path"] == "kappa_dir_root"
                names = [s["name"] for s in listing["subfolders"]]
                files = [f["filename"] for f in listing["files"]]
                assert "kappa_subdir" in names
                assert "kappa_listing_file.md" in files
            finally:
                await tx.rollback()
        finally:
            await bypass.close()

    asyncio.run(run())


# ── end-to-end through memory_context_builder ────────────────────


@iwo3_db
def test_memory_context_builder_renders_path_targeted_section(db_url: str) -> None:
    async def run() -> None:
        clear_all_caches()
        bypass = await asyncpg.connect(db_url)
        try:
            tx = bypass.transaction()
            await tx.start()
            try:
                await bypass.execute(
                    f"SET LOCAL app.current_client_id = '{KLEAR_CLIENT}'"
                )
                await bypass.execute("SET LOCAL ROLE iwo3_app")
                _, art_id = await _insert_test_folder_and_artifact(
                    bypass,
                    client_id=KLEAR_CLIENT,
                    folder_name="kappa_render_test",
                    artifact_filename="kappa_render.md",
                    artifact_text="KAPPA_RENDER_BODY_MARKER content here.",
                )
                bundle = await memory_context_builder(
                    bypass,
                    client_id=KLEAR_CLIENT,
                    user_id=KLEAR_OPERATOR,
                    message="please use the deck in kappa_render_test for context",
                )
                assert "## PATH-TARGETED FILES" in bundle.block
                assert "kappa_render_test/kappa_render.md" in bundle.block
                assert "KAPPA_RENDER_BODY_MARKER" in bundle.block
                assert "## GROUNDING RULES" in bundle.block
                assert "## CITATIONS" in bundle.block
                # exactly one path_targeted source surfaced
                kinds = [s.kind for s in bundle.sources]
                assert "path_targeted" in kinds
            finally:
                await tx.rollback()
        finally:
            await bypass.close()

    asyncio.run(run())
