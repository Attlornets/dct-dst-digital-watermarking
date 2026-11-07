"""Authenticated encryption helpers for watermark metadata."""

from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

SALT_SIZE = 16
NONCE_SIZE = 12
KEY_SIZE = 32
PBKDF2_ITERATIONS = 600_000
MIN_ENCRYPTED_SIZE = SALT_SIZE + NONCE_SIZE + 16


class AuthenticationError(ValueError):
    """Raised when a watermark password is wrong or its payload was altered."""


def _derive_key(password: str, salt: bytes) -> bytes:
    if not password:
        raise ValueError("Password must not be empty.")
    if len(salt) != SALT_SIZE:
        raise ValueError(f"Salt must be exactly {SALT_SIZE} bytes.")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_SIZE,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt_metadata(metadata: str, password: str) -> bytes:
    """Encrypt UTF-8 metadata as salt || nonce || AES-GCM ciphertext-and-tag."""
    if not isinstance(metadata, str) or not metadata:
        raise ValueError("Owner metadata must be a non-empty string.")
    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)
    key = _derive_key(password, salt)
    ciphertext_and_tag = AESGCM(key).encrypt(nonce, metadata.encode("utf-8"), None)
    return salt + nonce + ciphertext_and_tag


def decrypt_metadata(payload: bytes, password: str) -> str:
    """Authenticate and decrypt a serialized watermark payload."""
    if len(payload) < MIN_ENCRYPTED_SIZE:
        raise ValueError("Encrypted watermark payload is truncated.")
    salt = payload[:SALT_SIZE]
    nonce = payload[SALT_SIZE : SALT_SIZE + NONCE_SIZE]
    ciphertext_and_tag = payload[SALT_SIZE + NONCE_SIZE :]
    key = _derive_key(password, salt)
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext_and_tag, None)
    except InvalidTag as exc:
        raise AuthenticationError(
            "Watermark authentication failed: wrong password or altered payload."
        ) from exc
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AuthenticationError("Authenticated watermark is not valid UTF-8.") from exc
