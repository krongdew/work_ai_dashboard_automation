"""Authenticated LAN workspace and durable, owner-scoped inference queue."""
from __future__ import annotations

from contextvars import ContextVar
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time

from dotenv import load_dotenv
from flask import abort, g, jsonify, request, send_file
from io import BytesIO
import zipfile
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv(Path(__file__).resolve().with_name(".env"))
CURRENT_OWNER = ContextVar("factory_owner", default=None)
CURRENT_STORE = ContextVar("factory_store", default=None)
COOKIE = "factory_session"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            for migration in sorted((Path(__file__).resolve().parent / "lan/migrations").glob("*.sql")):
                db.executescript(migration.read_text(encoding="utf-8"))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_user(self, username, password):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{3,40}", username) or len(password) < 12 or len(password) > 256:
            raise ValueError("Username: 3-40 letters/digits/_/-. Password: 12-256 characters.")
        owner = secrets.token_hex(16)
        with self.connect() as db:
            db.execute("INSERT INTO users(id,username,password) VALUES(?,?,?)", (owner, username, generate_password_hash(password)))
        return owner

    def disable_user(self, username):
        with self.connect() as db:
            row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
            if not row:
                raise ValueError("User not found")
            db.execute("UPDATE users SET active=0 WHERE id=?", (row["id"],))
            db.execute("DELETE FROM sessions WHERE owner=?", (row["id"],))
            db.execute("UPDATE workers SET active=0 WHERE owner=?", (row["id"],))
            db.execute("UPDATE tasks SET status='failed',error='Account disabled',payload='{}' WHERE owner=? AND status IN ('queued','running')", (row["id"],))

    def session(self, token):
        with self.connect() as db:
            return db.execute("SELECT s.owner,s.csrf,u.username FROM sessions s JOIN users u ON u.id=s.owner WHERE s.token=? AND s.expires>? AND u.active=1", (digest(token), time.time())).fetchone()

    def worker(self, token):
        with self.connect() as db:
            return db.execute("SELECT w.* FROM workers w JOIN users u ON u.id=w.owner WHERE w.token=? AND w.active=1 AND u.active=1", (digest(token),)).fetchone()

    def enqueue(self, owner, payload):
        task = secrets.token_hex(16)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM tasks WHERE expires<? AND status IN ('completed','failed')", (time.time()-3600,))
            db.execute("UPDATE tasks SET status='failed',error='Worker timed out',payload='{}' WHERE expires<? AND status IN ('queued','running')", (time.time(),))
            if not db.execute("SELECT 1 FROM workers WHERE owner=? AND active=1 AND seen>?", (owner, time.time()-60)).fetchone():
                raise ValueError("Worker offline. Start your paired Factory Worker and try again.")
            if db.execute("SELECT count(*) FROM tasks WHERE owner=? AND status IN ('queued','running')", (owner,)).fetchone()[0] >= 2:
                raise ValueError("Your Worker queue is full. Wait for the current AI request.")
            db.execute("INSERT INTO tasks(id,owner,payload,status,expires) VALUES(?,?,?,'queued',?)", (task, owner, json.dumps(payload), time.time()+1200))
        return task

    def claim(self, worker):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM workers w JOIN users u ON u.id=w.owner WHERE w.id=? AND w.active=1 AND u.active=1", (worker["id"],)).fetchone():
                raise ValueError("Worker revoked")
            db.execute("UPDATE workers SET seen=? WHERE id=? AND active=1", (time.time(), worker["id"]))
            db.execute("UPDATE tasks SET status='failed',error='Worker disconnected or timed out',payload='{}' WHERE expires<? AND status IN ('queued','running')", (time.time(),))
            # A worker processes one request at a time. A disconnected lease is failed, never reassigned silently.
            if db.execute("SELECT 1 FROM tasks WHERE worker=? AND status='running'", (worker["id"],)).fetchone():
                return None
            task = db.execute("SELECT * FROM tasks WHERE owner=? AND status='queued' ORDER BY rowid LIMIT 1", (worker["owner"],)).fetchone()
            if not task:
                return None
            lease = secrets.token_urlsafe(24)
            db.execute("UPDATE tasks SET status='running',worker=?,lease=?,expires=? WHERE id=?", (worker["id"], digest(lease), time.time()+90, task["id"]))
            return {"id": task["id"], "lease": lease, **json.loads(task["payload"])}

    def complete(self, worker, task_id, lease, result=None, error=None):
        from jsonschema import Draft202012Validator
        from output_language import require_supported_text
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = db.execute("SELECT * FROM tasks WHERE id=? AND owner=? AND worker=? AND lease=? AND status='running' AND expires>?", (task_id, worker["owner"], worker["id"], digest(lease), time.time())).fetchone()
            if not task:
                raise ValueError("Task lease is invalid or expired")
            if not error:
                Draft202012Validator(json.loads(task["payload"])["schema"]).validate(result)
                require_supported_text(result)
            db.execute("UPDATE tasks SET status=?,result=?,error=?,payload='{}',lease=NULL WHERE id=?", ("failed" if error else "completed", json.dumps(result) if not error else None, str(error)[:500] if error else None, task_id))

    def wait(self, task_id, timeout=1200):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            with self.connect() as db:
                row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if not row:
                    raise ValueError("AI task is no longer available")
                if row["status"] == "completed":
                    db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
                    return json.loads(row["result"])
                if row["status"] == "failed" or row["expires"] < time.time():
                    db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
                    raise ValueError(row["error"] or "Worker timed out. Reconnect your Worker and retry.")
            time.sleep(0.5)
        with self.connect() as db:
            db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        raise ValueError("AI task timed out")


def remote_generate(system_prompt, user_prompt, schema):
    store, owner = CURRENT_STORE.get(), CURRENT_OWNER.get()
    if store is None or owner is None:
        raise ValueError("LAN AI requests require an authenticated owner")
    task = store.enqueue(owner, {"system_prompt": system_prompt, "user_prompt": user_prompt, "schema": schema})
    return store.wait(task)


def model_identity():
    store, owner = CURRENT_STORE.get(), CURRENT_OWNER.get()
    if store and owner:
        with store.connect() as db:
            row = db.execute("SELECT id,model FROM workers WHERE owner=? AND active=1", (owner,)).fetchone()
        return f"{row['id']}:{row['model']}" if row else "worker-offline"
    return None


def worker_archive(root):
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for source, destination in [
            (root / "lan/worker.py", "worker.py"),
            (root / "output_language.py", "output_language.py"),
            (root / "lan/worker-requirements.txt", "requirements.txt"),
            (root / "lan/WORKER-INSTALL.md", "INSTALL.md"),
        ]:
            archive.write(source, destination)
    output.seek(0)
    return output


def install_lan(app, root):
    enabled = os.getenv("FACTORY_MODE", "local") == "lan"
    app.config["FACTORY_LAN"] = enabled
    if not enabled:
        return
    store = Store(os.getenv("FACTORY_LAN_DB", str(root / ".lan/factory.sqlite3")))
    app.extensions["factory_lan"] = store
    app.config["FACTORY_LAN_PROJECTS"] = str(root / ".lan/projects")
    public_origin = os.environ.get("FACTORY_PUBLIC_ORIGIN", "").rstrip("/")
    if not public_origin or not public_origin.startswith("https://"):
        raise ValueError("LAN mode requires FACTORY_PUBLIC_ORIGIN=https://<LAN host>:<port>")

    @app.errorhandler(ValueError)
    def invalid_lan_input(error):
        return jsonify(error=str(error)), 400

    @app.before_request
    def authenticate():
        # The trusted local reverse proxy must preserve Host. Ignore client-supplied forwarding headers.
        if request.host != public_origin.split("://", 1)[1]:
            return jsonify(error="Untrusted host"), 400
        if request.path in {"/", "/api/health", "/static/lan.js"}:
            return None
        if request.path.startswith("/api/worker/"):
            if request.content_length and request.content_length > 2*1024*1024:
                return jsonify(error="Worker payload too large"), 413
            if request.method == "POST" and not isinstance(request.get_json(silent=True), dict):
                return jsonify(error="JSON body must be an object"), 400
            if request.path == "/api/worker/pair":
                return None
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            g.worker = store.worker(token)
            if not g.worker:
                return jsonify(error="Worker authorization failed"), 401
            return None
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("Origin") != public_origin:
                return jsonify(error="Origin validation failed"), 403
        if request.path == "/api/auth/login":
            if not isinstance(request.get_json(silent=True), dict):
                return jsonify(error="JSON body must be an object"), 400
            return None
        user = store.session(request.cookies.get(COOKIE, ""))
        if not user:
            return jsonify(error="Please sign in", login_required=True), 401
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), user["csrf"]):
            return jsonify(error="CSRF validation failed"), 403
        g.factory_user = dict(user)
        g.owner_context = CURRENT_OWNER.set(user["owner"])
        g.store_context = CURRENT_STORE.set(store)

    @app.teardown_request
    def clear_context(_error):
        if hasattr(g, "owner_context"):
            CURRENT_OWNER.reset(g.owner_context)
            CURRENT_STORE.reset(g.store_context)

    @app.after_request
    def response_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.endpoint == "dashboard":
            response.headers["Content-Security-Policy"] = (
                "sandbox allow-scripts allow-downloads; default-src 'none'; "
                "script-src 'unsafe-inline'; style-src 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'none'; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
            )
        return response

    @app.post("/api/auth/login")
    def lan_login():
        payload = request.get_json(silent=True) or {}
        username, password = payload.get("username", ""), payload.get("password", "")
        if not isinstance(username, str) or not isinstance(password, str) or len(username)>40 or len(password)>256:
            return jsonify(error="Invalid credentials"), 400
        key = digest(request.remote_addr or "unknown")
        with store.connect() as db:
            attempt = db.execute("SELECT * FROM login_attempts WHERE key=?", (key,)).fetchone()
            if attempt and attempt["since"] > time.time()-300 and attempt["failures"] >= 10:
                return jsonify(error="Too many login attempts. Wait five minutes."), 429
            user = db.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
            if not user or not check_password_hash(user["password"], password):
                failures = attempt["failures"]+1 if attempt and attempt["since"] > time.time()-300 else 1
                db.execute("INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)", (key, failures, attempt["since"] if failures>1 else time.time()))
                return jsonify(error="Invalid credentials"), 401
            db.execute("DELETE FROM login_attempts WHERE key=?", (key,))
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (digest(token), user["id"], csrf, time.time()+28800))
        response = jsonify(username=username, csrf=csrf, mode="lan")
        response.set_cookie(COOKIE, token, secure=True, httponly=True, samesite="Strict", max_age=28800)
        return response

    @app.get("/api/auth/me")
    def lan_me():
        return jsonify(username=g.factory_user["username"], csrf=g.factory_user["csrf"], mode="lan")

    @app.post("/api/auth/logout")
    def lan_logout():
        with store.connect() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (digest(request.cookies.get(COOKIE, "")),))
        response = jsonify(ok=True)
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="Strict")
        return response

    @app.post("/api/workers/pairing")
    def pairing_code():
        code = secrets.token_urlsafe(24)
        with store.connect() as db:
            db.execute("DELETE FROM pairing WHERE expires<? OR owner=?", (time.time(), CURRENT_OWNER.get()))
            db.execute("INSERT INTO pairing VALUES(?,?,?)", (digest(code), CURRENT_OWNER.get(), time.time()+300))
        return jsonify(code=code, expires_in=300)

    @app.post("/api/worker/pair")
    def pair_worker():
        payload = request.get_json(silent=True) or {}
        code, model = payload.get("code", ""), payload.get("model", "")
        if not isinstance(code, str) or not isinstance(model, str) or not model.strip() or len(model)>200 or len(code)>200:
            return jsonify(error="Pairing code and model are required"), 400
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            pairing = db.execute("SELECT p.* FROM pairing p JOIN users u ON u.id=p.owner WHERE p.token=? AND p.expires>? AND u.active=1", (digest(code), time.time())).fetchone()
            if not pairing:
                return jsonify(error="Invalid or expired pairing code"), 401
            db.execute("DELETE FROM pairing WHERE token=?", (digest(code),))
            db.execute("UPDATE workers SET active=0 WHERE owner=?", (pairing["owner"],))
            db.execute("UPDATE tasks SET status='failed',error='Worker replaced',payload='{}' WHERE owner=? AND status IN ('queued','running')", (pairing["owner"],))
            token, worker_id = secrets.token_urlsafe(32), secrets.token_hex(16)
            db.execute("INSERT INTO workers(id,owner,token,model,seen) VALUES(?,?,?,?,?)", (worker_id, pairing["owner"], digest(token), model, time.time()))
        return jsonify(worker_id=worker_id, token=token)

    @app.get("/api/workers")
    def workers():
        with store.connect() as db:
            rows = db.execute("SELECT id,model,seen FROM workers WHERE owner=? AND active=1", (CURRENT_OWNER.get(),)).fetchall()
        return jsonify([{**dict(row), "online": row["seen"] > time.time()-60} for row in rows])

    @app.get("/api/worker-package")
    def worker_package():
        return send_file(worker_archive(root), mimetype="application/zip", as_attachment=True, download_name="Factory-Worker.zip")

    @app.delete("/api/workers/<worker_id>")
    def revoke_worker(worker_id):
        with store.connect() as db:
            db.execute("UPDATE workers SET active=0 WHERE id=? AND owner=?", (worker_id, CURRENT_OWNER.get()))
            db.execute("UPDATE tasks SET status='failed',error='Worker revoked',payload='{}' WHERE worker=? AND owner=? AND status IN ('queued','running')", (worker_id, CURRENT_OWNER.get()))
        return jsonify(ok=True)

    @app.post("/api/worker/claim")
    def claim_task():
        return jsonify(task=store.claim(g.worker))

    @app.post("/api/worker/tasks/<task_id>/heartbeat")
    def heartbeat_task(task_id):
        lease = (request.get_json(silent=True) or {}).get("lease", "")
        if not isinstance(lease, str):
            abort(400)
        with store.connect() as db:
            changed = db.execute("UPDATE tasks SET expires=? WHERE id=? AND owner=? AND worker=? AND lease=? AND status='running' AND expires>?", (time.time()+90, task_id, g.worker["owner"], g.worker["id"], digest(lease), time.time())).rowcount
            db.execute("UPDATE workers SET seen=? WHERE id=?", (time.time(), g.worker["id"]))
        return (jsonify(ok=True), 200) if changed else (jsonify(error="Lease expired"), 409)

    @app.post("/api/worker/tasks/<task_id>/result")
    def task_result(task_id):
        from jsonschema import ValidationError
        payload = request.get_json(silent=True) or {}
        if request.content_length and request.content_length > 2*1024*1024:
            return jsonify(error="AI result too large"), 413
        if not isinstance(payload.get("lease"), str):
            return jsonify(error="Lease required"), 400
        try:
            store.complete(g.worker, task_id, payload["lease"], payload.get("result"), payload.get("error"))
        except (ValueError, ValidationError):
            return jsonify(error="Invalid result, language, schema or lease"), 400
        return jsonify(ok=True)
