"""Credential management — file parsing, encryption, and environment variables."""

from __future__ import annotations

import base64
import csv
import json
import os
from dataclasses import dataclass


def _get_fernet_and_kdf():
    """Lazy import of cryptography to avoid import errors when not needed."""
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    return Fernet, hashes, PBKDF2HMAC


@dataclass
class Account:
    username: str
    password: str


def _derive_key(passphrase: str, salt: bytes = b"reddit-bot-salt") -> bytes:
    """Derive a Fernet key from a passphrase."""
    Fernet, hashes, PBKDF2HMAC = _get_fernet_and_kdf()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def encrypt_file(input_path: str, output_path: str, passphrase: str) -> None:
    """Encrypt a file with a passphrase."""
    Fernet, _, _ = _get_fernet_and_kdf()
    key = _derive_key(passphrase)
    fernet = Fernet(key)
    with open(input_path, "rb") as f:
        data = f.read()
    encrypted = fernet.encrypt(data)
    with open(output_path, "wb") as f:
        f.write(encrypted)


def decrypt_file(input_path: str, passphrase: str) -> str:
    """Decrypt a file and return its contents as a string."""
    Fernet, _, _ = _get_fernet_and_kdf()
    key = _derive_key(passphrase)
    fernet = Fernet(key)
    with open(input_path, "rb") as f:
        data = f.read()
    return fernet.decrypt(data).decode()


def read_accounts(
    path: str,
    encrypted: bool = False,
    passphrase: str | None = None,
) -> list[Account]:
    """Read accounts from a file (pipe-delimited, CSV, or JSON).

    Supports:
      - Pipe-delimited: username|password
      - CSV: username,password
      - JSON: [{"username": "...", "password": "..."}]
      - Encrypted versions of any of the above
    """
    if encrypted:
        if not passphrase:
            passphrase = os.environ.get("REDDIT_BOT_KEY", "")
        if not passphrase:
            raise ValueError("No passphrase provided for encrypted credentials")
        content = decrypt_file(path, passphrase)
    else:
        with open(path) as f:
            content = f.read()

    content = content.strip()
    if not content:
        return []

    # JSON format
    if content.startswith("["):
        data = json.loads(content)
        return [Account(username=d["username"], password=d["password"]) for d in data]

    lines = [line.strip() for line in content.splitlines() if line.strip()]

    # CSV format (has header with comma)
    if "," in lines[0] and "|" not in lines[0]:
        accounts = []
        reader = csv.DictReader(lines)
        for row in reader:
            accounts.append(Account(username=row["username"], password=row["password"]))
        return accounts

    # Pipe-delimited format (default)
    accounts = []
    for line in lines:
        parts = line.split("|", maxsplit=1)
        if len(parts) == 2:
            accounts.append(Account(username=parts[0].strip(), password=parts[1].strip()))
    return accounts


def read_accounts_from_env() -> list[Account]:
    """Read accounts from environment variables.

    Expects REDDIT_ACCOUNT_1=username|password, REDDIT_ACCOUNT_2=..., etc.
    """
    accounts = []
    i = 1
    while True:
        value = os.environ.get(f"REDDIT_ACCOUNT_{i}")
        if value is None:
            break
        parts = value.split("|", maxsplit=1)
        if len(parts) == 2:
            accounts.append(Account(username=parts[0].strip(), password=parts[1].strip()))
        i += 1
    return accounts
