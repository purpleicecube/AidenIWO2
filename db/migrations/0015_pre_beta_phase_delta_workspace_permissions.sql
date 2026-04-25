-- Pre-Beta Loop δ.2 — Workspace RBAC vocabulary.
-- Mirrors db/seeds/permissions.json + role_permissions.json so freshly-
-- migrated DBs (CI / new dev installs) can hit /workspace/* without
-- re-running the seed loader.

INSERT INTO permissions (id, permission_key, display_name, description, scope)
VALUES
  ('00000000-0000-4000-8000-0000a0000073', 'workspace:read',
   'Read tenant workspace',
   'List workspace folders + artifacts for this tenant.',
   'tenant'::permission_scope),
  ('00000000-0000-4000-8000-0000a0000074', 'workspace:write',
   'Mutate tenant workspace',
   'Create, rename, move folders + files in the tenant workspace tree.',
   'tenant'::permission_scope),
  ('00000000-0000-4000-8000-0000a0000075', 'workspace:delete',
   'Delete from tenant workspace',
   'Soft-delete folders + artifacts in the tenant workspace tree.',
   'tenant'::permission_scope)
ON CONFLICT (permission_key) DO UPDATE
  SET display_name = EXCLUDED.display_name,
      description  = EXCLUDED.description;
--> statement-breakpoint

INSERT INTO role_permissions (role, permission_id)
SELECT r.role::membership_role, p.id
  FROM permissions p
  JOIN (VALUES
    ('owner',        'workspace:read'),
    ('owner',        'workspace:write'),
    ('owner',        'workspace:delete'),
    ('admin',        'workspace:read'),
    ('admin',        'workspace:write'),
    ('admin',        'workspace:delete'),
    ('operator',     'workspace:read'),
    ('operator',     'workspace:write'),
    ('reviewer',     'workspace:read'),
    ('viewer',       'workspace:read'),
    ('agent_system', 'workspace:read'),
    ('agent_system', 'workspace:write')
  ) AS r(role, permission_key) ON r.permission_key = p.permission_key
ON CONFLICT ON CONSTRAINT role_permissions_role_permission_uniq DO NOTHING;
