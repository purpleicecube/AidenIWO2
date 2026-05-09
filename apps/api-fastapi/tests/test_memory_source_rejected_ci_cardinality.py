"""Loop Kappa κ.3 — CI cardinality gate for memory.source_rejected.

The firewall smoke alarm should NEVER fire in production. Loop Iota
M-009 marked any non-zero count as a P0 incident. Loop Kappa
operationalizes this as a CI hard gate: the full pytest pass must
leave zero `memory.source_rejected` rows in the test DB.

Skips when IWO3_DATABASE_URL is unset.

If this test fails, the firewall has caught a regression — Layer 4
validation rejected a source that reached the assembler. Investigate
which source produced the rejection (the metadata carries
expected_client_id, actual_client_id, expected_user_id,
actual_user_id, kind, reason).
"""

from __future__ import annotations

import asyncio
import os

import asyncpg
import pytest


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


@iwo3_db
def test_memory_source_rejected_cardinality_zero() -> None:
    """Hard gate: zero memory.source_rejected rows in the test DB."""

    async def run() -> None:
        url = os.environ["IWO3_DATABASE_URL"]
        conn = await asyncpg.connect(url)
        try:
            row = await conn.fetchrow(
                """
                SELECT count(*)::int AS reject_count,
                       array_agg(metadata) FILTER (WHERE metadata IS NOT NULL) AS metas
                FROM action_audit_log
                WHERE action = 'memory.source_rejected'
                """
            )
            count = int(row["reject_count"]) if row else 0
            assert count == 0, (
                f"Firewall smoke alarm fired {count} time(s) during "
                f"the test run. Each rejection means the assembler "
                f"validator caught a tenant or owner mismatch — "
                f"investigate immediately. Sample metadata: "
                f"{row['metas'][:3] if row.get('metas') else 'none'}"
            )
        finally:
            await conn.close()

    asyncio.run(run())
