"""Tests for credential parsing and encryption."""

import json
import os

import pytest

from bot.utils.credentials import (
    read_accounts,
    read_accounts_from_env,
    Account,
)


class TestReadAccountsPipeDelimited:
    def test_basic(self, tmp_path):
        f = tmp_path / "accounts.txt"
        f.write_text("user1|pass1\nuser2|pass2\n")
        accounts = read_accounts(str(f))
        assert len(accounts) == 2
        assert accounts[0] == Account("user1", "pass1")
        assert accounts[1] == Account("user2", "pass2")

    def test_password_with_pipe(self, tmp_path):
        f = tmp_path / "accounts.txt"
        f.write_text("user1|pass|word\n")
        accounts = read_accounts(str(f))
        assert accounts[0].password == "pass|word"

    def test_empty_lines_skipped(self, tmp_path):
        f = tmp_path / "accounts.txt"
        f.write_text("user1|pass1\n\n\nuser2|pass2\n")
        accounts = read_accounts(str(f))
        assert len(accounts) == 2


class TestReadAccountsCsv:
    def test_csv_format(self, tmp_path):
        f = tmp_path / "accounts.csv"
        f.write_text("username,password\nuser1,pass1\nuser2,pass2\n")
        accounts = read_accounts(str(f))
        assert len(accounts) == 2
        assert accounts[0] == Account("user1", "pass1")


class TestReadAccountsJson:
    def test_json_format(self, tmp_path):
        f = tmp_path / "accounts.json"
        data = [
            {"username": "user1", "password": "pass1"},
            {"username": "user2", "password": "pass2"},
        ]
        f.write_text(json.dumps(data))
        accounts = read_accounts(str(f))
        assert len(accounts) == 2
        assert accounts[0] == Account("user1", "pass1")



# Encryption tests are in tests/test_encryption.py (separate file)
# to isolate cryptography import failures from the rest of the test suite.


class TestReadAccountsFromEnv:
    def test_env_accounts(self, monkeypatch):
        monkeypatch.setenv("REDDIT_ACCOUNT_1", "user1|pass1")
        monkeypatch.setenv("REDDIT_ACCOUNT_2", "user2|pass2")
        accounts = read_accounts_from_env()
        assert len(accounts) == 2
        assert accounts[0] == Account("user1", "pass1")

    def test_no_env_accounts(self, monkeypatch):
        monkeypatch.delenv("REDDIT_ACCOUNT_1", raising=False)
        accounts = read_accounts_from_env()
        assert len(accounts) == 0
