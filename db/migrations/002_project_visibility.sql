-- 002_project_visibility.sql — add a visibility tier to each dashboard.
-- Idempotent: safe to re-run. Never edit after it has run in another environment.
--
-- Tiers:
--   'sub_unit'      visible only to users in the same sub-unit (and admins)
--   'org'           visible to the whole organization (DEFAULT, legacy behavior)
--   'authenticated' visible to EVERY signed-in user, across organizations
--                   (this is the "public to logged-in staff" tier, NOT open internet)

ALTER TABLE project_meta
    ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'org';

-- Enforce the allowed set. Drop-then-add so re-running updates the constraint cleanly.
ALTER TABLE project_meta DROP CONSTRAINT IF EXISTS project_meta_visibility_chk;
ALTER TABLE project_meta
    ADD CONSTRAINT project_meta_visibility_chk
    CHECK (visibility IN ('sub_unit', 'org', 'authenticated'));

CREATE INDEX IF NOT EXISTS project_meta_visibility ON project_meta(visibility);
