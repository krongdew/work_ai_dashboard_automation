"""Google OAuth login + Postgres-backed sessions + org access scoping.

Login policy (all three must hold):
  1. Google account email domain == OAUTH_ALLOWED_DOMAIN (mahidol.ac.th)
  2. the email already exists in the users table (allowlist) and is active
  3. a valid session cookie is issued only after 1 and 2 pass

Admins (role='admin') see every project; members see only their org's projects.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time
from functools import wraps
from urllib.parse import urlencode

import requests
from flask import g, jsonify, redirect, request

import db

COOKIE = "factory_session"
SESSION_TTL = 28800  # 8 hours
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"

# Public routes that never require a session.
PUBLIC_PATHS = {"/", "/api/health", "/api/me", "/api/auth/google/login", "/api/auth/google/callback"}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def oauth_configured() -> bool:
    return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))


# ---------------------------------------------------------------- sessions ---
def issue_session(user_id: int) -> tuple[str, str]:
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE expires < %s", (time.time(),))
            cur.execute(
                "INSERT INTO sessions(token_hash, user_id, csrf, expires) VALUES(%s,%s,%s,%s)",
                (_digest(token), user_id, csrf, time.time() + SESSION_TTL),
            )
    return token, csrf


def session_user(token: str) -> dict | None:
    if not token:
        return None
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT u.id, u.email, u.full_name, u.role, u.org_id, u.sub_unit_id, s.csrf
                   FROM sessions s JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = %s AND s.expires > %s AND u.active = TRUE""",
                (_digest(token), time.time()),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def destroy_session(token: str) -> None:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE token_hash = %s", (_digest(token),))


# ------------------------------------------------------------------- OAuth ---
def google_login_url() -> tuple[str, str]:
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "redirect_uri": os.getenv("GOOGLE_REDIRECT_URI", ""),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "hd": os.getenv("OAUTH_ALLOWED_DOMAIN", "mahidol.ac.th"),
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH}?{urlencode(params)}", state


def exchange_code(code: str) -> dict:
    resp = requests.post(
        GOOGLE_TOKEN,
        data={
            "code": code,
            "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
            "redirect_uri": os.getenv("GOOGLE_REDIRECT_URI", ""),
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    # Google answers 4xx with a JSON {"error": ..., "error_description": ...} body.
    # raise_for_status() would hide that as a generic HTTPError (-> "google_unreachable"),
    # so surface the real reason as a readable ValueError instead.
    if resp.status_code >= 400:
        try:
            payload = resp.json()
            reason = payload.get("error_description") or payload.get("error") or resp.text
        except ValueError:
            reason = resp.text
        import sys
        print(f"[oauth] token exchange failed ({resp.status_code}): {reason}", file=sys.stderr, flush=True)
        raise ValueError(f"Google token exchange failed: {reason}")
    access_token = resp.json().get("access_token", "")
    info = requests.get(
        GOOGLE_USERINFO,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    if info.status_code >= 400:
        import sys
        print(f"[oauth] userinfo failed ({info.status_code}): {info.text}", file=sys.stderr, flush=True)
        raise ValueError(f"Google userinfo failed: {info.text}")
    return info.json()


def authorize_email(email: str, email_verified: bool) -> dict:
    """Apply the 3-part policy. Returns the user row or raises ValueError."""
    domain = os.getenv("OAUTH_ALLOWED_DOMAIN", "mahidol.ac.th").lower()
    email = (email or "").strip().lower()
    if not email_verified:
        raise ValueError("Google did not verify this email.")
    if not email.endswith("@" + domain):
        raise ValueError(f"อนุญาตเฉพาะอีเมล @{domain} เท่านั้น")
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, full_name, role, org_id, sub_unit_id, active FROM users WHERE email = %s",
                (email,),
            )
            user = cur.fetchone()
    if not user:
        raise ValueError("อีเมลนี้ยังไม่ได้รับสิทธิ์เข้าใช้งาน กรุณาติดต่อผู้ดูแลระบบ")
    if not user["active"]:
        raise ValueError("บัญชีนี้ถูกปิดการใช้งาน")
    return dict(user)


# ------------------------------------------------------- request lifecycle ---
def current_user() -> dict | None:
    return getattr(g, "factory_user", None)


def is_admin() -> bool:
    user = current_user()
    return bool(user and user.get("role") == "admin")


def require_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return jsonify(error="Please sign in", login_required=True), 401
        return fn(*args, **kwargs)
    return wrapper


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return jsonify(error="Please sign in", login_required=True), 401
        if not is_admin():
            return jsonify(error="ต้องเป็นผู้ดูแลระบบ (admin) เท่านั้น"), 403
        return fn(*args, **kwargs)
    return wrapper


def visible_org_filter() -> int | None:
    """Return the org_id a member is scoped to, or None for admin (sees all)."""
    if is_admin():
        return None
    user = current_user() or {}
    return user.get("org_id")


# ---------------------------------------------------------- project scoping ---
def set_project_meta(project_name: str, org_id, sub_unit_id, owner_email, visibility: str = "org") -> None:
    if visibility not in {"sub_unit", "org", "authenticated"}:
        visibility = "org"
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO project_meta(project_name, org_id, sub_unit_id, owner_email, visibility)
               VALUES(%s,%s,%s,%s,%s)
               ON CONFLICT (project_name) DO UPDATE
               SET org_id = EXCLUDED.org_id, sub_unit_id = EXCLUDED.sub_unit_id,
                   visibility = EXCLUDED.visibility""",
            (project_name, org_id, sub_unit_id, owner_email, visibility),
        )


def update_project_visibility(project_name: str, org_id, sub_unit_id, visibility: str) -> None:
    """Change a dashboard's org/sub-unit/visibility without touching its owner."""
    if visibility not in {"sub_unit", "org", "authenticated"}:
        raise ValueError("visibility must be sub_unit, org, or authenticated")
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE project_meta
               SET org_id = %s, sub_unit_id = %s, visibility = %s
               WHERE project_name = %s""",
            (org_id, sub_unit_id, visibility, project_name),
        )


def project_meta(project_name: str) -> dict | None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT project_name, org_id, sub_unit_id, owner_email, visibility FROM project_meta WHERE project_name = %s",
            (project_name,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def visible_project_names() -> set | None:
    """Project names the current user may see, or None = all (admin).

    A member sees: every 'authenticated' dashboard (any org), every 'org'
    dashboard in their own org, and 'sub_unit' dashboards only within their
    own sub-unit.
    """
    if is_admin():
        return None
    user = current_user() or {}
    org_id = user.get("org_id")
    sub_unit_id = user.get("sub_unit_id")
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT project_name FROM project_meta
               WHERE visibility = 'authenticated'
                  OR (visibility = 'org' AND org_id IS NOT DISTINCT FROM %s)
                  OR (visibility = 'sub_unit' AND sub_unit_id IS NOT DISTINCT FROM %s)""",
            (org_id, sub_unit_id),
        )
        return {r["project_name"] for r in cur.fetchall()}


def can_access_project(project_name: str) -> bool:
    names = visible_project_names()
    return names is None or project_name in names


def delete_project_meta(project_name: str) -> None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM project_meta WHERE project_name = %s", (project_name,))


def install_auth(app):
    """Wire OAuth routes + the before_request session guard onto the Flask app."""
    app.secret_key = os.getenv("FACTORY_SECRET_KEY", "dev-only-change-me")

    @app.before_request
    def _load_session():
        g.factory_user = None
        path = request.path
        is_public = path in PUBLIC_PATHS or path.startswith("/static/")
        user = session_user(request.cookies.get(COOKIE, ""))
        if user:
            g.factory_user = user
            # CSRF for state-changing requests (skip for public paths).
            if not is_public and request.method not in {"GET", "HEAD", "OPTIONS"}:
                if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), user["csrf"]):
                    return jsonify(error="CSRF validation failed"), 403
        if is_public:
            return None
        if not user and path.startswith("/api/"):
            return jsonify(error="Please sign in", login_required=True), 401
        return None

    @app.get("/api/auth/google/login")
    def google_login():
        if not oauth_configured():
            return jsonify(error="Google OAuth ยังไม่ได้ตั้งค่า (GOOGLE_CLIENT_ID/SECRET)", configured=False), 503
        url, state = google_login_url()
        resp = redirect(url)
        resp.set_cookie("oauth_state", state, max_age=600, httponly=True, samesite="Lax")
        return resp

    @app.get("/api/auth/google/callback")
    def google_callback():
        if not oauth_configured():
            return jsonify(error="Google OAuth not configured"), 503
        if request.args.get("state") != request.cookies.get("oauth_state"):
            return jsonify(error="Invalid OAuth state"), 400
        code = request.args.get("code", "")
        if not code:
            return jsonify(error="Missing authorization code"), 400
        try:
            profile = exchange_code(code)
            user = authorize_email(profile.get("email", ""), profile.get("email_verified", False))
        except ValueError as exc:
            # Redirect back to the SPA with the real, readable reason.
            from urllib.parse import quote
            return redirect("/?login_error=" + quote(str(exc)))
        except requests.RequestException as exc:
            import sys
            print(f"[oauth] network error reaching Google: {exc!r}", file=sys.stderr, flush=True)
            return redirect("/?login_error=google_unreachable")
        token, csrf = issue_session(user["id"])
        resp = redirect("/")
        resp.set_cookie(COOKIE, token, httponly=True, samesite="Lax", max_age=SESSION_TTL)
        resp.delete_cookie("oauth_state")
        return resp

    @app.get("/api/me")
    def me():
        user = current_user()
        if not user:
            return jsonify(authenticated=False, oauth_configured=oauth_configured()), 200
        return jsonify(
            authenticated=True,
            email=user["email"],
            full_name=user.get("full_name"),
            role=user["role"],
            org_id=user.get("org_id"),
            sub_unit_id=user.get("sub_unit_id"),
            csrf=user["csrf"],
            is_admin=user["role"] == "admin",
        )

    @app.post("/api/auth/logout")
    def logout():
        destroy_session(request.cookies.get(COOKIE, ""))
        resp = jsonify(ok=True)
        resp.delete_cookie(COOKIE)
        return resp

    @app.get("/api/org-options")
    def org_options():
        """Org + sub-unit options for the create/edit UI, scoped by role.
        Admin: every org and its sub-units. Member: only their own org's sub-units."""
        user = current_user()
        if not user:
            return jsonify(error="Please sign in", login_required=True), 401
        with db.connect() as conn, conn.cursor() as cur:
            if user["role"] == "admin":
                cur.execute("SELECT id, name FROM organizations ORDER BY name")
                orgs = [dict(r) for r in cur.fetchall()]
                cur.execute("SELECT id, org_id, name FROM sub_units ORDER BY name")
                subs = [dict(r) for r in cur.fetchall()]
            else:
                orgs = []
                if user.get("org_id") is not None:
                    cur.execute("SELECT id, name FROM organizations WHERE id = %s", (user["org_id"],))
                    orgs = [dict(r) for r in cur.fetchall()]
                    cur.execute("SELECT id, org_id, name FROM sub_units WHERE org_id = %s ORDER BY name", (user["org_id"],))
                    subs = [dict(r) for r in cur.fetchall()]
                else:
                    subs = []
        return jsonify(is_admin=user["role"] == "admin", org_id=user.get("org_id"),
                       sub_unit_id=user.get("sub_unit_id"), organizations=orgs, sub_units=subs)
