-- MegaLoop Beta-1 ε.3 — production auth password storage.
-- Architect Q2 lock: signed JWT (HS256) with TTL + refresh; password
-- credentials stored on the users table; dev bearer remains local-dev
-- only behind an env gate. PBKDF2-HMAC-SHA256 hash format documented
-- in apps/api-fastapi/auth/passwords.py.

ALTER TABLE "users"
  ADD COLUMN IF NOT EXISTS "password_hash" varchar(512),
  ADD COLUMN IF NOT EXISTS "password_updated_at" timestamp with time zone;
