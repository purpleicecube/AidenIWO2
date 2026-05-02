"""ζ.6 — Seed real PBKDF2 password hashes for selected users.

Interactive operator script. Run from repo root with the public Railway
Postgres URL set as IWO3_DATABASE_URL:

    cd /home/virgina/VS_AIDEN_IWO3
    DB_PUB=$(railway variables --service Postgres --kv \
        | grep "^DATABASE_PUBLIC_URL=" | cut -d= -f2-)
    IWO3_DATABASE_URL="$DB_PUB" \
        apps/api-fastapi/.venv/bin/python infra/local/seed_user_passwords.py

The script:
  1. Lists every user in the `users` table that has password_hash IS NULL
  2. For each user, prompts for a password via getpass (input hidden)
     - press Enter to skip that user (leaves them disabled)
  3. Hashes via the same PBKDF2-HMAC-SHA256 (600k iterations) routine
     used by /auth/login
  4. UPDATEs users.password_hash + users.password_updated_at

Passwords never leave the operator's machine. Only the resulting hash
(which is useless without the password) is sent to Postgres.

This script does not change Railway env vars. The public runtime stays
in IWO3_AUTH_MODE=jwt throughout; this helper only writes password
hashes directly to Postgres.
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
        if not rows:
            print("No users without password_hash — nothing to seed.")
            return 0

        print(f"Found {len(rows)} user(s) without password_hash.\n")
        print("For each, type a password and press Enter to set it.")
        print("Press Enter on an empty prompt to SKIP that user.\n")

        seeded = 0
        skipped = 0
        for row in rows:
            email = row["email"]
            user_id = row["id"]
            try:
                pw = getpass(f"  password for {email!s:35s} > ")
            except (EOFError, KeyboardInterrupt):
                print("\n[abort] no further updates")
                break

            if not pw:
                skipped += 1
                continue

            # Confirm strong-ish minimum
            if len(pw) < 8:
                print(
                    f"  ! password for {email} is shorter than 8 chars — "
                    "skipping. Re-run if you want to set a real password."
                )
                skipped += 1
                continue

            digest = hash_password(pw)
            # lint:bypass-rls-explain="operator-only ζ.6 helper; UPDATE keyed on users.id which is unique across tenants; tenant-cross by design"
            await conn.execute(
                "UPDATE users "
                "SET password_hash = $1, password_updated_at = NOW() "
                "WHERE id = $2",
                digest,
                user_id,
            )
            seeded += 1
            print(f"  ✓ {email}")

        print(f"\n[done] seeded={seeded} skipped={skipped}")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
