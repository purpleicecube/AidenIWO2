-- MegaLoop Beta-1.5 phase 2 / Q15 — encrypted-at-rest adapter credentials.
-- Architect Q15 lock (path B): libsodium app-side. The DB stores ciphertext;
-- the runtime holds the master key in IWO3_CRYPTO_MASTER_KEY and derives a
-- per-tenant key via HKDF inside the process.
--
-- Three additive columns. Beta-1 rows keep `encrypted_value IS NULL`; the
-- runtime continues to env-inject from `credential_ref:env:NAME`. As
-- operators rotate to encrypted-at-rest, they POST the new ciphertext +
-- algo tag and the resolver prefers the encrypted blob (see
-- runtime/credentials_crypto.resolve_encrypted_or_env).
--
-- Constraint discipline:
--   * encrypted_value + encryption_algo + encrypted_at must move together.
--   * encryption_algo is a free-form tag (e.g. `libsodium-secretbox-v1`)
--     so future algorithm rotations don't need a schema change.

ALTER TABLE "adapter_credentials"
  ADD COLUMN IF NOT EXISTS "encrypted_value" bytea,
  ADD COLUMN IF NOT EXISTS "encryption_algo" varchar(64),
  ADD COLUMN IF NOT EXISTS "encrypted_at" timestamp with time zone;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conname = 'adapter_credentials_encrypted_triplet_chk'
  ) THEN
    ALTER TABLE "adapter_credentials"
      ADD CONSTRAINT "adapter_credentials_encrypted_triplet_chk"
      CHECK (
        (encrypted_value IS NULL AND encryption_algo IS NULL AND encrypted_at IS NULL)
        OR
        (encrypted_value IS NOT NULL AND encryption_algo IS NOT NULL AND encrypted_at IS NOT NULL)
      );
  END IF;
END$$;
