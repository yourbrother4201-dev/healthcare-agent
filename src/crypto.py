"""Field-level encryption for sensitive health text.

Values are encrypted with Fernet (AES-128-CBC with HMAC) using DATA_ENCRYPTION_KEY
from the .env file. Encrypted values are stored with a visible prefix so that
plain-text values written before encryption was added can still be read, and
are encrypted the next time the migration runs.

Losing DATA_ENCRYPTION_KEY means the encrypted values cannot be recovered.
"""
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from cryptography.fernet import Fernet, InvalidToken

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

PREFIX = "enc:v1:"


@lru_cache(maxsize=1)
def _fernet():
    key = os.getenv("DATA_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("DATA_ENCRYPTION_KEY is missing. Add it to your .env file.")
    return Fernet(key.encode())


def encrypt_text(value):
    """Encrypt a string. Empty values and already-encrypted values are returned unchanged."""
    if value is None or value == "":
        return value
    text = str(value)
    if text.startswith(PREFIX):
        return text
    return PREFIX + _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt_text(value):
    """Decrypt a value. Plain-text values from before encryption are returned as-is."""
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        # Wrong or changed key. Never show the raw ciphertext to the user.
        return "[unreadable: encryption key mismatch]"