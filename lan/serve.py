"""Run authenticated LAN Factory behind a local HTTPS reverse proxy."""
import argparse
import importlib.util
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True, help="Public HTTPS origin, e.g. https://192.168.1.10:8443")
    parser.add_argument("--port", type=int, default=5051)
    args = parser.parse_args()
    os.environ["FACTORY_MODE"] = "lan"
    os.environ["FACTORY_PUBLIC_ORIGIN"] = args.origin.rstrip("/")
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from waitress import serve
    spec = importlib.util.spec_from_file_location("factory_lan_app", root / "factory-ui/app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.app.config["DEBUG"] = False
    print("Factory LAN backend on loopback. Public origin:", args.origin)
    serve(module.app, host="127.0.0.1", port=args.port, threads=16, max_request_body_size=200*1024*1024)


if __name__ == "__main__":
    main()
