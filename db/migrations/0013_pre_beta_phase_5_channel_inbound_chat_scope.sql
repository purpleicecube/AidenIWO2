-- Pre-Beta β.5 — channel correctness hardening.
-- The α.5 inbound UNIQUE was scoped (channel_kind, external_message_id).
-- For Telegram (and many other chat APIs), message_id is per-chat,
-- not global — so chat A's message #42 and chat B's message #42 would
-- collide on the existing constraint and the second INSERT would
-- silently UPSERT into the first row.
--
-- Widen the inbound UNIQUE to include external_chat_id so cross-chat
-- collisions cannot alias rows.
-- See ADR-028.

-- Drop the old constraint (named in 0010_alpha_phase_5_channel_layer.sql).
ALTER TABLE "channel_messages"
  DROP CONSTRAINT IF EXISTS "channel_messages_inbound_external_uniq";
--> statement-breakpoint

-- Re-add with the chat-scoped key. NULL chat ids (e.g. broadcast-style
-- channels we may add later) still get the original two-tuple shape
-- because UNIQUE treats NULLs as distinct in Postgres — no row aliases.
ALTER TABLE "channel_messages"
  ADD CONSTRAINT "channel_messages_inbound_external_uniq"
  UNIQUE ("channel_kind", "external_chat_id", "external_message_id");
