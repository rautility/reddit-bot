"""Tests for credential encryption/decryption.

Separated from test_credentials.py because the cryptography package
may not be available or functional in all environments.
"""

import pytest
from cryptography.fernet import InvalidToken

from bot.utils.credentials import decrypt_file, encrypt_file


class TestEncryption:
    def test_encrypt_decrypt(self, tmp_path):
        plain = tmp_path / "plain.txt"
        plain.write_text("user1|pass1\nuser2|pass2")
        encrypted = tmp_path / "encrypted.bin"

        encrypt_file(str(plain), str(encrypted), "testkey123")
        content = decrypt_file(str(encrypted), "testkey123")
        assert content == "user1|pass1\nuser2|pass2"

    def test_wrong_key_fails(self, tmp_path):
        plain = tmp_path / "plain.txt"
        plain.write_text("secret data")
        encrypted = tmp_path / "encrypted.bin"

        encrypt_file(str(plain), str(encrypted), "correctkey")
        with pytest.raises(InvalidToken):
            decrypt_file(str(encrypted), "wrongkey")
