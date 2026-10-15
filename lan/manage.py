"""Account management is available only through the host computer's terminal."""
import argparse
import getpass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lan_service import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["create-user", "disable-user", "list-users"])
    parser.add_argument("username", nargs="?")
    args = parser.parse_args()
    import os
    store = Store(os.getenv("FACTORY_LAN_DB", str(ROOT / ".lan/factory.sqlite3")))
    if args.command == "list-users":
        with store.connect() as db:
            for row in db.execute("SELECT username,active FROM users ORDER BY username"):
                print(row["username"], "active" if row["active"] else "disabled")
        return
    if not args.username:
        parser.error("username is required")
    if args.command == "disable-user":
        store.disable_user(args.username)
        print("User disabled; sessions and workers revoked.")
    else:
        password = getpass.getpass("New password (at least 12 characters): ")
        if password != getpass.getpass("Repeat password: "):
            raise SystemExit("Passwords do not match")
        store.create_user(args.username, password)
        print("User created. Sign in through the Factory HTTPS URL.")


if __name__ == "__main__":
    main()
