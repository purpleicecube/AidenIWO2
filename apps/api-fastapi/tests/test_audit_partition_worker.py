"""Audit-log partition window maintenance.

Regression cover for the defect that took every audited mutation in
IWO3 offline on 2026-07-01: migration 0002 seeded three months of
partitions (2026-04 … 2026-06), shipped `ensure_audit_partition_for()`
to extend the window, and nothing ever called it. `action_audit_log`
then had no partition for `now()`, so ~55 audited call sites 500'd and
60 vitest integration tests failed on a freshly reset database.

`month_starts` is pure, so the rollover cases are testable without
freezing the clock or touching Postgres.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from workers.audit_partition_worker import (
    ensure_audit_partitions,
    month_starts,
)


def _utc(y: int, m: int, d: int, h: int = 0) -> datetime:
    return datetime(y, m, d, h, tzinfo=timezone.utc)


# ── month_starts ─────────────────────────────────────────────────────


def test_window_starts_at_the_current_month_not_the_next() -> None:
    """The bug was a window that had already expired. Today's month
    must always be in it — mid-month, month-start and month-end."""
    for day in (1, 15, 30):
        starts = month_starts(_utc(2026, 9, day, 13), 3)
        assert starts[0] == _utc(2026, 9, 1)


def test_window_covers_requested_months_ahead() -> None:
    starts = month_starts(_utc(2026, 9, 4), 3)
    assert [s.date().isoformat() for s in starts] == [
        "2026-09-01",
        "2026-10-01",
        "2026-11-01",
        "2026-12-01",
    ]


def test_window_crosses_the_year_boundary() -> None:
    """December + 3 must roll into the next year, not clamp at 12."""
    starts = month_starts(_utc(2026, 12, 20), 3)
    assert [s.date().isoformat() for s in starts] == [
        "2026-12-01",
        "2027-01-01",
        "2027-02-01",
        "2027-03-01",
    ]


def test_window_handles_31_to_30_day_rollover() -> None:
    """Naive +30/+31 day arithmetic skips or repeats a month. Jan 31
    is the classic case."""
    starts = month_starts(_utc(2027, 1, 31), 3)
    assert [s.date().isoformat() for s in starts] == [
        "2027-01-01",
        "2027-02-01",
        "2027-03-01",
        "2027-04-01",
    ]


def test_window_handles_february_in_a_leap_year() -> None:
    starts = month_starts(_utc(2028, 2, 29), 2)
    assert [s.date().isoformat() for s in starts] == [
        "2028-02-01",
        "2028-03-01",
        "2028-04-01",
    ]


def test_start_instants_are_midnight_utc() -> None:
    """A partition bound must be the first instant of the month —
    a bound of 09-04T13:22 would leave the first three days of the
    month unroutable."""
    for s in month_starts(_utc(2026, 9, 4, 13), 2):
        assert (s.day, s.hour, s.minute, s.second, s.microsecond) == (1, 0, 0, 0, 0)
        assert s.tzinfo is not None


def test_naive_datetimes_are_treated_as_utc() -> None:
    starts = month_starts(datetime(2026, 9, 4, 13), 1)
    assert starts[0].date().isoformat() in ("2026-09-01", "2026-08-01")


# ── ensure_audit_partitions ──────────────────────────────────────────


class _FakeConn:
    """Minimal asyncpg.Connection stand-in — records what was run."""

    def __init__(self, helper_present: bool = True) -> None:
        self.helper_present = helper_present
        self.executed: list[tuple[str, tuple]] = []

    async def fetchval(self, sql: str, *args):  # noqa: ANN001
        return self.helper_present

    async def execute(self, sql: str, *args):  # noqa: ANN001
        self.executed.append((sql, args))


@pytest.mark.asyncio
async def test_ensure_calls_the_helper_once_per_month() -> None:
    conn = _FakeConn()
    ensured = await ensure_audit_partitions(conn, now=_utc(2026, 9, 4))
    assert ensured == ["2026-09-01", "2026-10-01", "2026-11-01", "2026-12-01"]
    assert len(conn.executed) == 4
    assert all("ensure_audit_partition_for" in sql for sql, _ in conn.executed)


@pytest.mark.asyncio
async def test_missing_helper_is_reported_not_swallowed() -> None:
    """A database predating migration 0002 must produce an empty
    window and no DDL attempt — never a false 'window ok'."""
    conn = _FakeConn(helper_present=False)
    ensured = await ensure_audit_partitions(conn, now=_utc(2026, 9, 4))
    assert ensured == []
    assert conn.executed == []
