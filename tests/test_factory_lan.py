import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lan_service import CURRENT_OWNER, CURRENT_STORE

ORIGIN = "https://factory.test:8443"
SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["dashboard_title"], "properties": {"dashboard_title": {"type": "string"}}}


class FactoryLanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        with patch.dict(os.environ, {"FACTORY_MODE": "lan", "FACTORY_PUBLIC_ORIGIN": ORIGIN,
                                     "FACTORY_LAN_DB": str(self.folder / "lan.sqlite3")}):
            spec = importlib.util.spec_from_file_location("factory_lan_test", ROOT / "factory-ui/app.py")
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        self.app = self.module.app
        self.app.config.update(TESTING=True, FACTORY_LAN_PROJECTS=str(self.folder / "projects"))
        self.store = self.app.extensions["factory_lan"]
        self.alice_id = self.store.create_user("alice", "alice-private-password")
        self.bob_id = self.store.create_user("bob", "bob-private-password")
        self.alice = self.app.test_client()
        self.bob = self.app.test_client()
        self.alice_csrf = self.login(self.alice, "alice", "alice-private-password")
        self.bob_csrf = self.login(self.bob, "bob", "bob-private-password")
        self.worker_client = self.app.test_client()

    def request(self, client, path, method="GET", csrf="", **kwargs):
        headers = kwargs.pop("headers", {})
        headers.update(Origin=ORIGIN)
        if csrf:
            headers["X-CSRF-Token"] = csrf
        return client.open(path, method=method, base_url=ORIGIN, headers=headers, **kwargs)

    def login(self, client, username, password):
        result = self.request(client, "/api/auth/login", "POST", json={"username": username, "password": password})
        self.assertEqual(result.status_code, 200)
        self.assertIn("Secure", result.headers["Set-Cookie"])
        self.assertIn("HttpOnly", result.headers["Set-Cookie"])
        return result.json["csrf"]

    def pair(self, client=None, csrf=None):
        client = client or self.alice
        csrf = csrf or self.alice_csrf
        code = self.request(client, "/api/workers/pairing", "POST", csrf, json={}).json["code"]
        result = self.request(self.worker_client, "/api/worker/pair", "POST", json={"code": code, "model": "friend-model"})
        self.assertEqual(result.status_code, 200)
        return result.json, code

    def worker_request(self, token, path, payload=None):
        return self.request(self.worker_client, path, "POST", json=payload or {}, headers={"Authorization": "Bearer "+token})

    def test_auth_origin_csrf_and_host_are_required(self):
        self.assertEqual(self.request(self.app.test_client(), "/api/projects").status_code, 401)
        self.assertEqual(self.request(self.alice, "/api/projects", "POST", json={"name": "sample"}).status_code, 403)
        self.assertEqual(self.alice.post("/api/projects", base_url=ORIGIN, headers={"Origin": "https://evil.test", "X-CSRF-Token": self.alice_csrf}, json={"name": "sample"}).status_code, 403)
        self.assertEqual(self.alice.get("/api/projects", base_url="https://evil.test").status_code, 400)
        self.assertIsNone(CURRENT_OWNER.get())
        self.assertIsNone(CURRENT_STORE.get())

    def test_users_have_separate_projects_uploads_and_dashboard_assets(self):
        self.assertEqual(self.request(self.alice, "/api/projects", "POST", self.alice_csrf, json={"name": "private"}).status_code, 201)
        self.assertEqual(self.request(self.bob, "/api/projects/private").status_code, 404)
        self.assertEqual(self.request(self.bob, "/api/projects/private/dashboard").status_code, 404)
        self.assertEqual(self.request(self.bob, "/api/projects/private/dashboard/assets/logo.png").status_code, 404)
        self.assertEqual(self.request(self.bob, "/api/projects/private/datalink-bundle").status_code, 400)
        self.assertEqual(self.request(self.bob, "/api/projects").json, [])
        self.assertEqual(self.request(self.bob, "/api/projects", "POST", self.bob_csrf, json={"name": "private"}).status_code, 201)
        self.request(self.alice, "/api/projects/private/uploads", "POST", self.alice_csrf,
                     data={"files": (BytesIO(b"Department,Cost\nA,10\nB,20\nA,5\n"), "data.csv")})
        self.assertEqual(len(self.request(self.alice, "/api/projects/private").json["inputs"]), 1)
        self.assertEqual(self.request(self.bob, "/api/projects/private").json["inputs"], [])
        self.assertEqual(self.request(self.alice, "/api/projects", "POST", self.alice_csrf, json={"name": "../escape"}).status_code, 400)

    def test_pairing_is_single_use_and_revocable(self):
        worker, code = self.pair()
        self.assertEqual(self.request(self.worker_client, "/api/worker/pair", "POST", json={"code": code, "model": "other"}).status_code, 401)
        self.assertEqual(self.request(self.bob, f"/api/workers/{worker['worker_id']}", "DELETE", self.bob_csrf, json={}).status_code, 200)
        self.assertEqual(self.worker_request(worker["token"], "/api/worker/claim").status_code, 200)
        self.request(self.alice, f"/api/workers/{worker['worker_id']}", "DELETE", self.alice_csrf, json={})
        self.assertEqual(self.worker_request(worker["token"], "/api/worker/claim").status_code, 401)

    def test_worker_can_claim_only_own_tasks_and_results_require_valid_lease_schema_language(self):
        alice_worker, _ = self.pair()
        bob_worker, _ = self.pair(self.bob, self.bob_csrf)
        task_id = self.store.enqueue(self.alice_id, {"system_prompt": "test", "user_prompt": "test", "schema": SCHEMA})
        self.assertIsNone(self.worker_request(bob_worker["token"], "/api/worker/claim").json["task"])
        task = self.worker_request(alice_worker["token"], "/api/worker/claim").json["task"]
        self.assertEqual(task["id"], task_id)
        endpoint = f"/api/worker/tasks/{task_id}/result"
        valid = {"lease": task["lease"], "result": {"dashboard_title": "ภาพรวม"}}
        self.assertEqual(self.worker_request(bob_worker["token"], endpoint, valid).status_code, 400)
        self.assertEqual(self.worker_request(alice_worker["token"], endpoint, {**valid, "lease": "wrong"}).status_code, 400)
        self.assertEqual(self.worker_request(alice_worker["token"], endpoint, {"lease": task["lease"], "result": {"unexpected": True}}).status_code, 400)
        self.assertEqual(self.worker_request(alice_worker["token"], endpoint, {"lease": task["lease"], "result": {"dashboard_title": "总览"}}).status_code, 400)
        self.assertEqual(self.worker_request(alice_worker["token"], endpoint, valid).status_code, 200)
        self.assertEqual(self.store.wait(task_id, timeout=1), valid["result"])
        self.assertEqual(self.worker_request(alice_worker["token"], endpoint, valid).status_code, 400)

    def test_offline_disabled_and_expired_workers_cannot_process(self):
        with self.assertRaisesRegex(ValueError, "offline"):
            self.store.enqueue(self.alice_id, {"schema": SCHEMA})
        worker, _ = self.pair()
        task_id = self.store.enqueue(self.alice_id, {"schema": SCHEMA})
        task = self.worker_request(worker["token"], "/api/worker/claim").json["task"]
        with self.store.connect() as db:
            db.execute("UPDATE tasks SET expires=0 WHERE id=?", (task_id,))
        self.assertEqual(self.worker_request(worker["token"], f"/api/worker/tasks/{task_id}/heartbeat", {"lease": task["lease"]}).status_code, 409)
        self.store.disable_user("alice")
        self.assertEqual(self.request(self.alice, "/api/projects").status_code, 401)
        self.assertEqual(self.worker_request(worker["token"], "/api/worker/claim").status_code, 401)

    def test_download_worker_package_contains_no_server_credentials(self):
        response = self.request(self.alice, "/api/worker-package")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(BytesIO(response.data)) as archive:
            self.assertEqual(set(archive.namelist()), {"worker.py", "output_language.py", "requirements.txt", "INSTALL.md"})

    def test_full_upload_profile_remote_worker_spec_build_flow(self):
        self.request(self.alice, "/api/projects", "POST", self.alice_csrf, json={"name": "demo"})
        self.request(self.alice, "/api/projects/demo/uploads", "POST", self.alice_csrf,
                     data={"files": (BytesIO(b"Department,Cost\nA,10\nB,20\nA,5\n"), "data.csv")})
        self.assertEqual(self.request(self.alice, "/api/projects/demo/profile", "POST", self.alice_csrf, json={}).status_code, 200)
        worker, _ = self.pair()
        result = self.request(self.alice, "/api/projects/demo/suggest-jobs", "POST", self.alice_csrf, json={"instruction": "Create an overview"})
        self.assertEqual(result.status_code, 202)
        job_id = result.json["job_id"]
        self.assertEqual(self.request(self.bob, f"/api/ai-jobs/{job_id}").status_code, 404)
        self.assertEqual(self.request(self.alice, "/api/projects/demo/profile", "POST", self.alice_csrf, json={}).status_code, 409)
        spec_result = {"dashboard_title": "ภาพรวม", "purpose": "Summary", "audience": "Owner",
                       "kpis": [{"name": "รายการทั้งหมด", "metric": "record_count", "aggregation": "count", "formula": "COUNT(*)", "source_fields": [], "limitations": ""}],
                       "filters": ["Department"], "charts": [{"title": "รายการตามหน่วยงาน", "type": "bar", "dimension": "Department", "metric": "record_count", "aggregation": "count", "formula": "COUNT(*) GROUP BY Department", "source_fields": ["Department"], "limitations": ""}],
                       "insight_questions": ["How many records?"]}
        deadline = time.monotonic()+15
        handled = 0
        while time.monotonic() < deadline:
            job = self.request(self.alice, f"/api/ai-jobs/{job_id}").json
            if job["status"] != "running":
                break
            task = self.worker_request(worker["token"], "/api/worker/claim").json["task"]
            if task:
                if "semantic" in task["schema"].get("properties", {}):
                    output = {"semantic": {"field_interpretations": [], "dataset_summary": "Overview", "warnings": []},
                              "normalization": {"mappings": [], "warnings": []}, "calculations": {"requests": []}}
                else:
                    output = spec_result
                self.assertNotIn("data.csv", task["user_prompt"]) if "semantic" in task["schema"].get("properties", {}) else None
                response = self.worker_request(worker["token"], f"/api/worker/tasks/{task['id']}/result", {"lease": task["lease"], "result": output})
                self.assertEqual(response.status_code, 200, response.json)
                handled += 1
            time.sleep(0.05)
        self.assertEqual(job["status"], "completed", job)
        self.assertGreaterEqual(handled, 2)
        built = self.request(self.alice, "/api/projects/demo/build", "POST", self.alice_csrf, json={})
        self.assertEqual(built.status_code, 200, built.json)
        self.assertEqual(built.json["records"], 3)
        page = self.request(self.alice, "/api/projects/demo/dashboard")
        self.assertIn("ภาพรวม", page.data.decode())
        self.assertIn("sandbox", page.headers["Content-Security-Policy"])
        page.close()


class WorkerClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("factory_worker_test", ROOT / "lan/worker.py")
        cls.worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.worker)

    def test_rejects_remote_lmstudio_or_plain_http_factory(self):
        self.worker.validate_urls(ORIGIN, "http://127.0.0.1:1234/v1")
        with self.assertRaises(ValueError):
            self.worker.validate_urls("http://factory.test", "http://127.0.0.1:1234/v1")
        with self.assertRaises(ValueError):
            self.worker.validate_urls(ORIGIN, "http://192.168.1.20:1234/v1")

    def test_worker_calls_its_configured_model_and_repairs_language(self):
        calls = []
        def create(**kwargs):
            calls.append(kwargs)
            text = "总览" if len(calls) == 1 else "ภาพรวม"
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"dashboard_title": text})))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        result = self.worker.infer({"system_prompt": "system", "user_prompt": "metadata", "schema": SCHEMA},
                                   {"model": "friend-model", "lm_url": "http://127.0.0.1:1234/v1"}, client)
        self.assertEqual(result["dashboard_title"], "ภาพรวม")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["model"], "friend-model")


if __name__ == "__main__":
    unittest.main()
