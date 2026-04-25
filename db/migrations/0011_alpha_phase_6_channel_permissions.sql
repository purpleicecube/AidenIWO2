-- MegaLoop Alpha α.6 — channel layer RBAC vocabulary.
-- Adds three permission keys + their default role_permissions mapping.
-- See db/seeds/permissions.json (single source of truth) — this migration
-- mirrors those rows so freshly-migrated DBs (CI / new dev installs) get
-- the channel routes working without re-running the seed loader.
--
-- Idempotent: ON CONFLICT (permission_key) DO UPDATE updates display_name
-- + description in case they're tweaked over time.

INSERT INTO permissions (id, permission_key, display_name, description, scope)
VALUES
  ('00000000-0000-4000-8000-0000a0000070', 'channel_auth_code:issue',
   'Issue channel auth code',
   'Generate a one-time /start binding code for an external chat channel (Telegram, Slack, etc).',
   'tenant'::permission_scope),
  ('00000000-0000-4000-8000-0000a0000071', 'channel_identity:read',
   'Read channel identities',
   'List bound channel identities (chat IDs) for this tenant.',
   'tenant'::permission_scope),
  ('00000000-0000-4000-8000-0000a0000072', 'channel_identity:revoke',
   'Revoke channel identity',
   'Revoke a bound external chat identity so it can no longer act on this tenant.',
   'tenant'::permission_scope)
ON CONFLICT (permission_key) DO UPDATE
  SET display_name = EXCLUDED.display_name,
      description  = EXCLUDED.description;
--> statement-breakpoint

-- Default role mapping. Idempotent on (role, permission_id) UNIQUE.
INSERT INTO role_permissions (role, permission_id)
SELECT r.role::membership_role, p.id
  FROM permissions p
  JOIN (VALUES
    ('owner',        'channel_auth_code:issue'),
    ('owner',        'channel_identity:read'),
    ('owner',        'channel_identity:revoke'),
    ('admin',        'channel_auth_code:issue'),
    ('admin',        'channel_identity:read'),
    ('admin',        'channel_identity:revoke'),
    ('operator',     'channel_auth_code:issue'),
    ('operator',     'channel_identity:read'),
    ('reviewer',     'channel_identity:read'),
    ('agent_system', 'channel_identity:read')
  ) AS r(role, permission_key) ON r.permission_key = p.permission_key
ON CONFLICT ON CONSTRAINT role_permissions_role_permission_uniq DO NOTHING;
