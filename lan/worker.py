"""Outbound-only Factory Worker. It performs inference, never executes server code."""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import ssl
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from jsonschema import Draft202012Validator, ValidationError
from openai import OpenAI
if (Path(__file__).resolve().parents[1] / "output_language.py").exists():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from output_language import LANGUAGE_INSTRUCTION, unsupported_text_paths

CONFIG = Path.home() / ".factory-worker/config.json"


def validate_urls(server, lm_url):
    parsed = urlparse(server)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Factory server must be an HTTPS origin, e.g. https://192.168.1.10:8443")
    lm = urlparse(lm_url)
    if lm.scheme != "http" or lm.hostname not in {"localhost", "127.0.0.1", "::1"} or lm.username or lm.password or lm.query or lm.fragment:
        raise ValueError("LM Studio must use an HTTP loopback address on this computer")


def call_server(config, endpoint, payload):
    headers = {"Content-Type": "application/json"}
    if config.get("token"):
        headers["Authorization"] = "Bearer " + config["token"]
    context = ssl.create_default_context(cafile=config.get("ca_certificate") or None)
    req = Request(config["server"] + endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urlopen(req, timeout=30, context=context) as response:
        body = response.read(4*1024*1024+1)
        if len(body)>4*1024*1024:
            raise ValueError("Server response exceeds limit")
        return json.loads(body)


def infer(task, config, client=None):
    client = client or OpenAI(base_url=config["lm_url"], api_key=os.getenv("LMSTUDIO_API_KEY", "lm-studio"), timeout=900, max_retries=0)
    deadline = time.monotonic()+1100
    system = task["system_prompt"] + "\n\n" + LANGUAGE_INSTRUCTION
    messages = [{"role": "system", "content": system}, {"role": "user", "content": task["user_prompt"]}]
    kwargs = {}
    if "qwen3" in config["model"].lower():
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    for _ in range(3):
        if time.monotonic() >= deadline:
            break
        response = client.chat.completions.create(
            model=config["model"], messages=messages, temperature=0,
            max_tokens=config.get("max_tokens", 6144),
            timeout=min(900, max(1, deadline-time.monotonic())),
            response_format={"type": "json_schema", "json_schema": {"name": "factory_result", "strict": True, "schema": task["schema"]}},
            **kwargs,
        )
        try:
            result = json.loads(response.choices[0].message.content or "")
            Draft202012Validator(task["schema"]).validate(result)
            if unsupported_text_paths(result):
                raise ValueError("Generated display text must be Thai or English")
            return result
        except (ValueError, ValidationError):
            messages.append({"role": "user", "content": "Return complete valid JSON matching the schema. Generated display text must be Thai or English only. Preserve source references and formulas."})
    raise ValueError("Model did not return valid Thai/English JSON after three attempts")


def process_task(config, task):
    stopped = threading.Event()

    def heartbeat():
        while not stopped.wait(20):
            try:
                call_server(config, f"/api/worker/tasks/{task['id']}/heartbeat", {"lease": task["lease"]})
            except (HTTPError, URLError, OSError):
                pass  # The result endpoint still verifies the lease and revocation.

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        try:
            result = infer(task, config)
            payload = {"lease": task["lease"], "result": result}
        except Exception:
            # SDK errors may contain prompts, URLs or keys. Keep failures private to the computer.
            payload = {"lease": task["lease"], "error": "Local inference failed. Check LM Studio model, context, output limit and server status."}
        call_server(config, f"/api/worker/tasks/{task['id']}/result", payload)
    finally:
        stopped.set()
        thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description="Factory Worker: use this computer's LM Studio for your own projects")
    parser.add_argument("command", choices=["pair", "run"])
    parser.add_argument("--server")
    parser.add_argument("--model")
    parser.add_argument("--lm-url", default="http://127.0.0.1:1234/v1")
    parser.add_argument("--ca-certificate", help="Path to the Factory server's trusted root CA PEM certificate")
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    if args.command == "pair":
        if not args.server or not args.model:
            parser.error("pair requires --server and --model")
        validate_urls(args.server, args.lm_url)
        client = OpenAI(base_url=args.lm_url, api_key=os.getenv("LMSTUDIO_API_KEY", "lm-studio"), timeout=15)
        if args.model not in [item.id for item in client.models.list().data]:
            raise ValueError("Model not found in LM Studio. Use its exact model identifier and start the server.")
        config = {"server": args.server.rstrip("/"), "lm_url": args.lm_url, "model": args.model,
                  "ca_certificate": str(Path(args.ca_certificate).resolve()) if args.ca_certificate else None}
        result = call_server(config, "/api/worker/pair", {"code": getpass.getpass("One-time pairing code: "), "model": args.model})
        config.update(token=result["token"], worker_id=result["worker_id"])
        args.config.parent.mkdir(parents=True, exist_ok=True)
        # The file contains a bearer token. Use a private per-user directory.
        descriptor = os.open(args.config, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(config, target, indent=2)
        print("Paired. Keep the config private. Start with: python worker.py run")
        return
    config = json.loads(args.config.read_text(encoding="utf-8"))
    validate_urls(config["server"], config["lm_url"])
    print("Factory Worker running. Keep LM Studio open. Press Ctrl+C to stop.")
    while True:
        try:
            task = call_server(config, "/api/worker/claim", {}).get("task")
            if task:
                print("Processing your AI request...")
                process_task(config, task)
                print("Request finished.")
            else:
                time.sleep(3)
        except HTTPError as exc:
            if exc.code == 401:
                raise SystemExit("Worker authorization revoked. Pair again from your Factory account.")
            print("Server rejected request. Retrying shortly.")
            time.sleep(5)
        except (URLError, OSError, ValueError):
            print("Connection unavailable. Check server, certificate and network. Retrying shortly.")
            time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Worker stopped.")
