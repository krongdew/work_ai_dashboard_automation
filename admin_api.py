"""Admin-only management API: organizations, sub-units, and users.

Every route is guarded by auth.require_admin. All SQL is parameterized.
"""
from __future__ import annotations

from flask import jsonify, request

import db
from auth import require_admin


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def install_admin(app):
    # ----------------------------------------------------------- organizations
    @app.get("/api/admin/organizations")
    @require_admin
    def list_orgs():
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT o.id, o.name, o.created_at,
                       COALESCE(json_agg(json_build_object('id', s.id, 'name', s.name)
                                ORDER BY s.name) FILTER (WHERE s.id IS NOT NULL), '[]') AS sub_units
                FROM organizations o
                LEFT JOIN sub_units s ON s.org_id = o.id
                GROUP BY o.id ORDER BY o.name
            """)
            return jsonify([dict(r) for r in cur.fetchall()])

    @app.post("/api/admin/organizations")
    @require_admin
    def create_org():
        name = str(_body().get("name", "")).strip()
        if not name or len(name) > 120:
            return jsonify(error="ชื่อหน่วยงานต้องมี 1-120 ตัวอักษร"), 400
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO organizations(name) VALUES(%s) ON CONFLICT (name) DO NOTHING RETURNING id, name", (name,))
            row = cur.fetchone()
        if not row:
            return jsonify(error="มีหน่วยงานชื่อนี้อยู่แล้ว"), 409
        return jsonify(dict(row)), 201

    @app.delete("/api/admin/organizations/<int:org_id>")
    @require_admin
    def delete_org(org_id: int):
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM organizations WHERE id = %s", (org_id,))
        return jsonify(ok=True)

    # --------------------------------------------------------------- sub-units
    @app.post("/api/admin/organizations/<int:org_id>/sub-units")
    @require_admin
    def create_sub_unit(org_id: int):
        name = str(_body().get("name", "")).strip()
        if not name or len(name) > 120:
            return jsonify(error="ชื่อหน่วยย่อยต้องมี 1-120 ตัวอักษร"), 400
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM organizations WHERE id = %s", (org_id,))
            if not cur.fetchone():
                return jsonify(error="ไม่พบหน่วยงาน"), 404
            cur.execute(
                "INSERT INTO sub_units(org_id, name) VALUES(%s,%s) ON CONFLICT (org_id,name) DO NOTHING RETURNING id, org_id, name",
                (org_id, name),
            )
            row = cur.fetchone()
        if not row:
            return jsonify(error="มีหน่วยย่อยชื่อนี้อยู่แล้ว"), 409
        return jsonify(dict(row)), 201

    @app.delete("/api/admin/sub-units/<int:sub_unit_id>")
    @require_admin
    def delete_sub_unit(sub_unit_id: int):
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM sub_units WHERE id = %s", (sub_unit_id,))
        return jsonify(ok=True)

    # ------------------------------------------------------------------- users
    @app.get("/api/admin/users")
    @require_admin
    def list_users():
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT u.id, u.email, u.full_name, u.role, u.org_id, u.sub_unit_id, u.active,
                       o.name AS org_name, s.name AS sub_unit_name
                FROM users u
                LEFT JOIN organizations o ON o.id = u.org_id
                LEFT JOIN sub_units s ON s.id = u.sub_unit_id
                ORDER BY u.email
            """)
            return jsonify([dict(r) for r in cur.fetchall()])

    @app.post("/api/admin/users")
    @require_admin
    def create_user():
        body = _body()
        email = str(body.get("email", "")).strip().lower()
        full_name = str(body.get("full_name", "")).strip() or None
        role = str(body.get("role", "member")).strip()
        if not email.endswith("@mahidol.ac.th"):
            return jsonify(error="อนุญาตเฉพาะอีเมล @mahidol.ac.th"), 400
        if role not in {"admin", "member"}:
            return jsonify(error="role ต้องเป็น admin หรือ member"), 400
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users(email, full_name, role) VALUES(%s,%s,%s) ON CONFLICT (email) DO NOTHING RETURNING id, email, role",
                (email, full_name, role),
            )
            row = cur.fetchone()
        if not row:
            return jsonify(error="มีผู้ใช้อีเมลนี้อยู่แล้ว"), 409
        return jsonify(dict(row)), 201

    @app.put("/api/admin/users/<int:user_id>")
    @require_admin
    def update_user(user_id: int):
        """Assign org/sub-unit/role/active. Only provided fields change."""
        body = _body()
        sets, params = [], []
        if "org_id" in body:
            sets.append("org_id = %s"); params.append(body["org_id"] or None)
        if "sub_unit_id" in body:
            sets.append("sub_unit_id = %s"); params.append(body["sub_unit_id"] or None)
        if "role" in body:
            if body["role"] not in {"admin", "member"}:
                return jsonify(error="role ต้องเป็น admin หรือ member"), 400
            sets.append("role = %s"); params.append(body["role"])
        if "active" in body:
            sets.append("active = %s"); params.append(bool(body["active"]))
        if "full_name" in body:
            sets.append("full_name = %s"); params.append(str(body["full_name"]).strip() or None)
        if not sets:
            return jsonify(error="ไม่มีข้อมูลให้แก้ไข"), 400
        params.append(user_id)
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = %s RETURNING id, email, role, org_id, sub_unit_id, active", params)
            row = cur.fetchone()
        if not row:
            return jsonify(error="ไม่พบผู้ใช้"), 404
        return jsonify(dict(row))

    @app.delete("/api/admin/users/<int:user_id>")
    @require_admin
    def delete_user(user_id: int):
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT email FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if row and row["email"].lower() == "krongkwan.bua@mahidol.ac.th":
                return jsonify(error="ลบผู้ดูแลระบบหลักไม่ได้"), 400
            cur.execute("UPDATE users SET active = FALSE WHERE id = %s", (user_id,))
            cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
        return jsonify(ok=True)
