"""Server-side credential encryption for Growth Agent integrations.

Uses Fernet (AES-128-CBC + HMAC) with a separately configured key.
Tokens must never appear in browser storage, URLs, logs, source, or tests.
"""

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken


class CredentialCryptoError(ValueError):
    """Safe error code only; never includes ciphertext or plaintext."""


def _derive_fernet_key(raw: str) -> bytes:
    """Accept a Fernet key or derive one from a high-entropy secret string."""
    value = (raw or "").strip()
    if not value:
        raise CredentialCryptoError("CREDENTIAL_KEY_MISSING")
    try:
        # Already a url-safe base64 32-byte Fernet key.
        Fernet(value.encode("utf-8") if isinstance(value, str) else value)
        return value.encode("utf-8")
    except Exception:
        digest = hashlib.sha256(value.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=4)
def _fernet_for(key_material: str) -> Fernet:
    return Fernet(_derive_fernet_key(key_material))


def credential_key_configured() -> bool:
    return bool(str(os.getenv("NOVA_GA_CREDENTIAL_ENCRYPTION_KEY") or "").strip())


def encrypt_secret(plaintext: str, *, key_env: str = "NOVA_GA_CREDENTIAL_ENCRYPTION_KEY") -> str:
    if not isinstance(plaintext, str) or not plaintext:
        raise CredentialCryptoError("EMPTY_SECRET")
    raw_key = str(os.getenv(key_env) or "").strip()
    if not raw_key:
        raise CredentialCryptoError("CREDENTIAL_KEY_MISSING")
    token = _fernet_for(raw_key).encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(ciphertext: str, *, key_env: str = "NOVA_GA_CREDENTIAL_ENCRYPTION_KEY") -> str:
    if not isinstance(ciphertext, str) or not ciphertext:
        raise CredentialCryptoError("EMPTY_CIPHERTEXT")
    raw_key = str(os.getenv(key_env) or "").strip()
    if not raw_key:
        raise CredentialCryptoError("CREDENTIAL_KEY_MISSING")
    try:
        return _fernet_for(raw_key).decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise CredentialCryptoError("DECRYPT_FAILED") from exc


def clear_crypto_cache() -> None:
    """Test helper — drop cached Fernet instances after env changes."""
    _fernet_for.cache_clear()
