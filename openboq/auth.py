"""Minimal login for the dashboard: users with salted PBKDF2 password hashes in data/users.json (git-ignored).

    python cli.py adduser anirudh "Anirudh R."     # asks for the password
Demo-grade. For production, replace with company single sign-on (Streamlit st.login + an OIDC provider).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

USERS_PATH = Path(os.environ.get("NR_USERS") or Path(__file__).resolve().parent.parent / "data" / "users.json")
ITER = 200_000


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), ITER).hex()


def load_users(path: Path = USERS_PATH) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def add_user(username: str, password: str, display_name: str = "", path: Path = USERS_PATH) -> None:
    users = load_users(path)
    salt = secrets.token_hex(16)
    users[username.strip().lower()] = {"name": display_name or username, "salt": salt, "hash": _hash(password, salt)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(users, indent=2), encoding="utf-8")


def check(username: str, password: str, path: Path = USERS_PATH) -> dict | None:
    u = load_users(path).get((username or "").strip().lower())
    if not u:
        return None
    if hmac.compare_digest(u["hash"], _hash(password or "", u["salt"])):
        return {"username": username.strip().lower(), "name": u.get("name") or username}
    return None


def autologin(path: Path = USERS_PATH) -> dict | None:
    """Demo convenience: NR_AUTOLOGIN=<username> signs that (existing) user in without a password prompt."""
    name = (os.environ.get("NR_AUTOLOGIN") or "").strip().lower()
    u = load_users(path).get(name) if name else None
    return {"username": name, "name": u.get("name") or name} if u else None


def enabled(path: Path = USERS_PATH) -> bool:
    return bool(load_users(path))
