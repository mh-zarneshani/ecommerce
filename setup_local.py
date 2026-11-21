"""Run from a real terminal; PostgreSQL admin credentials are never saved."""
import argparse
import getpass
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import warnings

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent
BASE = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".config") / "ActiveEcomBootcamp"
PROFILE = BASE / "postgres.json"
PROJECTS = {"app": ("active_ecom_workshop", "active_ecom_local"),
            "test": ("active_ecom_workshop_test", "active_ecom_test")}


def protect_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "nt":
        identity = subprocess.run(["whoami"], capture_output=True, text=True, check=True).stdout.strip()
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                        identity + ":(OI)(CI)F", "SYSTEM:(OI)(CI)F"], capture_output=True, check=True)
    else:
        path.chmod(0o700)


def provision(port, admin, password):
    if PROFILE.exists():
        raise ValueError("A local profile already exists. Use Start-Windows.cmd.")
    for path in (ROOT / "data").glob("*.sqlite*"):
        raise ValueError("Existing SQLite data must be preserved; migration requires a separate decision.")
    protect_dir(BASE)
    common = dict(host="127.0.0.1", port=port, connect_timeout=5)
    profiles = {}
    created_db, created_roles = [], []
    with psycopg.connect(**common, dbname="postgres", user=admin, password=password,
                         autocommit=True) as db:
        db.execute("select pg_advisory_lock(618113998)")
        for dbname, role in PROJECTS.values():
            if (db.execute("select 1 from pg_database where datname=%s", (dbname,)).fetchone()
                or db.execute("select 1 from pg_roles where rolname=%s", (role,)).fetchone()):
                raise ValueError("Project database or role name already exists. No objects changed.")
        try:
            for kind, (dbname, role) in PROJECTS.items():
                secret = secrets.token_urlsafe(36)
                d, r = map(sql.Identifier, (dbname, role))
                db.execute("set password_encryption = 'scram-sha-256'")
                verifier = db.pgconn.encrypt_password(secret.encode(), role.encode(), b"scram-sha-256").decode()
                db.execute(sql.SQL("create role {} login nosuperuser nocreatedb nocreaterole noinherit password {}")
                           .format(r, sql.Literal(verifier)))
                created_roles.append(r)
                db.execute(sql.SQL("create database {} template template0 encoding 'UTF8'").format(d))
                created_db.append(d)
                db.execute(sql.SQL("revoke all on database {} from public").format(d))
                db.execute(sql.SQL("grant connect on database {} to {}").format(d, r))
                with psycopg.connect(**common, dbname=dbname, user=admin, password=password) as isolated:
                    isolated.execute(sql.SQL("grant usage, create on schema public to {}").format(r))
                profiles[kind] = dict(**common, dbname=dbname, user=role, password=secret)
            fd = os.open(PROFILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(profiles, f)
        except BaseException:
            for d in reversed(created_db):
                db.execute(sql.SQL("drop database {}").format(d))
            for r in reversed(created_roles):
                db.execute(sql.SQL("drop role {}").format(r))
            raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    try:
        if PROFILE.exists():
            print("Setup already completed. Run Start-Windows.cmd.")
            return 0
        port = args.port or int(input("Detected PostgreSQL port (use pg_isready to verify): "))
        admin = input("PostgreSQL administrator [postgres]: ").strip() or "postgres"
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("PostgreSQL password (hidden): ")
        provision(port, admin, password)
    except psycopg.Error as exc:
        print("PostgreSQL setup failed. Verify administrator, password and port.",
              exc.sqlstate or "", file=sys.stderr)
        return 1
    except (ValueError, OSError, getpass.GetPassWarning, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Setup complete. Open Start-Windows.cmd.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
