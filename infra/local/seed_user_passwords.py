"""ζ.6 — Bootstrap hosted login users and seed real PBKDF2 hashes.

Interactive operator script. Run from repo root with the public Railway
Postgres URL set as IWO3_DATABASE_URL:

    cd /home/virgina/VS_AIDEN_IWO3
    DB_PUB=$(railway variables --service Postgres --kv \
        | grep "^DATABASE_PUBLIC_URL=" | cut -d= -f2-)
    IWO3_DATABASE_URL="$DB_PUB" \
        apps/api-fastapi/.venv/bin/python infra/local/seed_user_passwords.py

The script supports two flows:

  1. Existing-user password bootstrap
     - Lists every user in the `users` table that has password_hash IS NULL
     - Prompts for passwords and updates the hashes in place

  2. New hosted-user bootstrap
     - Creates one or more new `users` rows directly in the target DB
     - Creates/updates matching `client_memberships`
     - Hashes and stores the chosen password

This is necessary for hosted `ζ.6` because `IWO3_SEED_SCOPE=reference`
deliberately does NOT seed `users` or `client_memberships`.

Passwords never leave the operator's machine. Only the resulting hash
(which is useless without the password) is sent to Postgres.

This script does not change Railway env vars. The public runtime stays
in IWO3_AUTH_MODE=jwt throughout; this helper only writes database rows.
"""

from __future__ import annotations

import asyncio
import os
import sys
from getpass import getpass
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "apps" / "api-fastapi"
sys.path.insert(0, str(API_DIR))

from auth.passwords import hash_password  # noqa: E402

import asyncpg  # noqa: E402


ROLE_OPTIONS = [
    "owner",
    "admin",
    "operator",
    "reviewer",
    "viewer",
    "agent_system",
]


def _prompt_yes_no(prompt: str, default: bool = False) -> bool:
    suffix = " [Y/n] " if default else " [y/N] "
    raw = input(prompt + suffix).strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes"}


def _prompt_nonempty(prompt: str) -> str:
    while True:
        raw = input(prompt).strip()
        if raw:
            return raw
        print("  ! value is required")


def _prompt_password(email: str) -> str | None:
    try:
        pw = getpass(f"  password for {email!s:35s} > ")
    except (EOFError, KeyboardInterrupt):
        print("\n[abort] password entry interrupted")
        return None
    if not pw:
        return ""
    if len(pw) < 8:
        print(
            f"  ! password for {email} is shorter than 8 chars — "
            "skipping. Re-run if you want to set a real password."
        )
        return ""
    try:
        confirm = getpass(f"  confirm   for {email!s:35s} > ")
    except (EOFError, KeyboardInterrupt):
        print("\n[abort] confirmation interrupted")
        return None
    if pw != confirm:
        print("  ! passwords did not match — skipping user")
        return ""
    return pw


def _prompt_choice(title: str, options: list[tuple[str, str]]) -> str:
    print(title)
    for idx, (_, label) in enumerate(options, start=1):
        print(f"  {idx}. {label}")
    while True:
        raw = input("  choose number > ").strip()
        if not raw.isdigit():
            print("  ! enter a number")
            continue
        pos = int(raw)
        if 1 <= pos <= len(options):
            return options[pos - 1][0]
        print("  ! choice out of range")


async def _upsert_user(
    conn: asyncpg.Connection,
    *,
    email: str,
    display_name: str,
    status: str = "active",
) -> str:
    row = await conn.fetchrow(
        """
        INSERT INTO users (email, display_name, status)
        VALUES ($1, $2, $3)
        ON CONFLICT (email) DO UPDATE SET
          display_name = EXCLUDED.display_name,
          status = EXCLUDED.status,
          updated_at = NOW()
        RETURNING id
        """,
        email,
        display_name,
        status,
    )
    assert row is not None
    return str(row["id"])


async def _upsert_membership(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    user_id: str,
    role: str,
    status: str = "active",
) -> None:
    await conn.execute(
        """
        INSERT INTO client_memberships (client_id, user_id, role, status)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (client_id, user_id) DO UPDATE SET
          role = EXCLUDED.role,
          status = EXCLUDED.status,
          updated_at = NOW()
        """,
        client_id,
        user_id,
        role,
        status,
    )


async def _set_password(
    conn: asyncpg.Connection, *, user_id: str, password: str
) -> None:
    digest = hash_password(password)
    await conn.execute(
        "UPDATE users "
        "SET password_hash = $1, password_updated_at = NOW(), updated_at = NOW() "
        "WHERE id = $2",
        digest,
        user_id,
    )


async def _bootstrap_new_users(conn: asyncpg.Connection) -> tuple[int, int]:
    clients = await conn.fetch(
        """
        SELECT id, designation, display_name
          FROM clients
         ORDER BY designation
        """
    )
    if not clients:
        print("No clients found — cannot create hosted users.")
        return 0, 0

    client_options = [
        (
            str(row["id"]),
            f"{row['designation']} ({row['display_name']})",
        )
        for row in clients
    ]
    role_options = [(role, role) for role in ROLE_OPTIONS]

    created = 0
    skipped = 0

    print("\nCreate hosted login users.")
    print("Leave email blank to stop.\n")

    while True:
        email = input("  email (blank to stop) > ").strip().lower()
        if not email:
            break
        display_name = _prompt_nonempty("  display name > ")
        client_id = _prompt_choice("  choose client:", client_options)
        role = _prompt_choice("  choose role:", role_options)
        password = _prompt_password(email)
        if password is None:
            break
        if not password:
            skipped += 1
            continue

        user_id = await _upsert_user(
            conn,
            email=email,
            display_name=display_name,
            status="active",
        )
        await _upsert_membership(
            conn,
            client_id=client_id,
            user_id=user_id,
            role=role,
            status="active",
        )
        await _set_password(conn, user_id=user_id, password=password)
        created += 1
        print(f"  ✓ {email} ({role})")

    return created, skipped


async def main() -> int:
    url = os.environ.get("IWO3_DATABASE_URL")
    if not url:
        print("IWO3_DATABASE_URL is required")
        return 1

    conn = await asyncpg.connect(url)
    try:
        # lint:bypass-rls-explain="operator-only ζ.6 helper; runs as iwo3 superuser to seed initial passwords across all tenants in one pass"
        rows = await conn.fetch(
            "SELECT id, email FROM users "
            "WHERE password_hash IS NULL "
            "ORDER BY email"
        )
        print(f"Found {len(rows)} existing user(s) without password_hash.\n")
        if rows:
            print("For each, type a password and press Enter to set it.")
            print("Press Enter on an empty prompt to SKIP that user.\n")
        else:
            print("No existing users without password_hash.\n")

        seeded = 0
        skipped = 0
        for row in rows:
            email = row["email"]
            user_id = row["id"]
            pw = _prompt_password(email)
            if pw is None:
                print("\n[abort] no further updates")
                break
            if not pw:
                skipped += 1
                continue
            await _set_password(conn, user_id=str(user_id), password=pw)
            seeded += 1
            print(f"  ✓ {email}")

        created = 0
        if _prompt_yes_no(
            "\nCreate or update hosted login users directly in this DB?",
            default=False,
        ):
            created, created_skipped = await _bootstrap_new_users(conn)
            skipped += created_skipped

        print(
            f"\n[done] password_seeded={seeded} new_users_bootstrapped={created} skipped={skipped}"
        )
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
