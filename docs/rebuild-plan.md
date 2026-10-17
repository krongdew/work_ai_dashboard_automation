# Rebuild Plan — Auth, Multi-Tenancy, Postgres, React/Ant Design

Status: PLANNING. Owner: krongkwan.bua@mahidol.ac.th (first admin).
Chosen approach: **Frontend A** (full React + Ant Design rewrite) + OAuth scaffold
with credentials filled in later by the user.

## Current state (grounded in code, 2026-10-16)

- Backend: Flask (`factory-ui/app.py`, port 5050), AI via `ai_client.py`
  (local LM Studio / Groq / LAN worker).
- Auth today: `lan_service.py` only, SQLite, username+password, session cookie +
  CSRF, login throttle. Active only in `FACTORY_MODE=lan`. **No Google OAuth, no
  Postgres, no org model.**
- Data: filesystem under `projects/<name>/` (input/output/working/config.json).
  Projects are NOT owner-scoped in local mode.
- Frontend: single `factory-ui/static/index.html` (vanilla JS). Must be replaced.
- Docker: available (v29). No compose file in this repo yet.

## Target architecture

```
┌─ React + Ant Design SPA (factory-ui-react/, Vite build → factory-ui/static/dist)
│    Google login button → backend OAuth → session cookie
│    Step-by-step workflow wizard, Thai UI, mobile responsive, Mahidol theme
├─ Flask backend (factory-ui/app.py)
│    /api/auth/google/*  — OAuth login, mahidol.ac.th + allowlist enforcement
│    /api/me             — identity + role + org scope
│    /api/admin/*        — user/org/sub-unit management (admin only)
│    existing project/dashboard APIs — now ORG-SCOPED
│    DELETE project/dashboard
└─ PostgreSQL (Docker) — users, organizations, sub_units, project_meta, sessions
```

## Decisions

1. **DB = PostgreSQL in Docker.** New `docker-compose.yml` (postgres:16-alpine,
   named volume, 127.0.0.1-only port). Access via `psycopg2`/SQLAlchemy.
   Filesystem `projects/` stays for dashboard artifacts; a `project_meta` table
   adds `org_id` / `sub_unit_id` / `owner_email` for access scoping.
2. **Auth = Google OAuth 2.0 (Authorization Code).** Scaffold now, credentials
   later. `.env`: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
   `GOOGLE_REDIRECT_URI`, `OAUTH_HD=mahidol.ac.th`. Rules:
   - email domain MUST be `@mahidol.ac.th` (reject others)
   - email MUST already exist in `users` (allowlist) — otherwise denied
   - first admin seeded: `krongkwan.bua@mahidol.ac.th` (role=admin)
3. **Roles:** `admin` (sees everything, manages users/orgs) and `member`
   (sees only their own org's data/dashboards).
4. **Multi-tenancy:** every user has `org_id` (+ optional `sub_unit_id`) set by an
   admin. Non-admin list/read/build/delete is filtered by their org. Admin bypass.
5. **Delete:** DELETE project (removes `projects/<name>/` + `project_meta` row,
   org-checked) and delete a built dashboard only.
6. **Manual:** Thai user manual (`docs/user-manual-th.md`) + in-app Help page.

## Data model (Postgres)

```sql
organizations(id, name UNIQUE, created_at)
sub_units(id, org_id → organizations, name, UNIQUE(org_id,name))
users(id, email UNIQUE CITEXT, full_name, role ['admin'|'member'],
      org_id → organizations NULL, sub_unit_id → sub_units NULL,
      active BOOL, created_at)
project_meta(project_name PK, org_id, sub_unit_id, owner_email, created_at)
sessions(token_hash PK, user_id, csrf, expires)   -- reuse LAN session pattern
```

Seed: admin user `krongkwan.bua@mahidol.ac.th`, role=admin, active=true.

## Phased implementation (each phase = its own work session, serialized)

- **P0 Infra** — docker-compose postgres, `db.py` connection + migrations runner,
  SQL migrations, seed admin. Verify: container up, tables exist, admin seeded.
- **P1 Auth** — Google OAuth flow + domain/allowlist guard + session issue;
  `/api/me`. Scaffold works end-to-end with placeholder creds (documented).
- **P2 Org admin API** — CRUD users/orgs/sub-units (admin-only), assign org to user.
- **P3 Org scoping** — add `org_id` to project create; filter every
  list/read/build/delete by caller's org (admin bypass). `project_meta` backfill.
- **P4 Delete** — DELETE project + dashboard, org-checked, confirm-guarded.
- **P5 React/AntD SPA** — Vite app, AntD, Mahidol theme tokens, step wizard,
  Thai copy, responsive; replace `index.html`; build into static dist served by Flask.
- **P6 Manual** — `docs/user-manual-th.md` + in-app Help.

## Blocking on user

- Google OAuth **Client ID + Secret** (user creates the OAuth app in Google Cloud
  Console; agent cannot). Until provided, P1 ships with documented placeholders
  and cannot be fully tested against Google.

## Guardrails (from dashboard-automation skill + data-rules)

- Never commit secrets; `.env` stays gitignored. Enforce authz in the backend,
  never trust the frontend. Parameterized SQL only. Keep raw `projects/*/input`
  untouched. Add a numbered migration per schema change; never edit a run migration.
