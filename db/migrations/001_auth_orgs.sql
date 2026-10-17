-- 001_auth_orgs.sql — initial auth + org multi-tenancy schema.
-- Idempotent: safe to re-run. Never edit after it has run in another environment.

CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS organizations (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sub_units (
    id          BIGSERIAL PRIMARY KEY,
    org_id      BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, name)
);

CREATE TABLE IF NOT EXISTS users (
    id           BIGSERIAL PRIMARY KEY,
    email        CITEXT NOT NULL UNIQUE,
    full_name    TEXT,
    role         TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
    org_id       BIGINT REFERENCES organizations(id) ON DELETE SET NULL,
    sub_unit_id  BIGINT REFERENCES sub_units(id) ON DELETE SET NULL,
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Dashboard artifacts stay on the filesystem (projects/<name>/); this table
-- adds the org scoping + ownership metadata the access checks need.
CREATE TABLE IF NOT EXISTS project_meta (
    project_name  TEXT PRIMARY KEY,
    org_id        BIGINT REFERENCES organizations(id) ON DELETE SET NULL,
    sub_unit_id   BIGINT REFERENCES sub_units(id) ON DELETE SET NULL,
    owner_email   CITEXT REFERENCES users(email) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf        TEXT NOT NULL,
    expires     DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);

-- Seed the first admin. ON CONFLICT keeps an existing row untouched on re-run.
INSERT INTO users (email, full_name, role, active)
VALUES ('krongkwan.bua@mahidol.ac.th', 'Krongkwan (Admin)', 'admin', TRUE)
ON CONFLICT (email) DO NOTHING;
