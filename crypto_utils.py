"""
crypto_utils.py
---------------
AES-256-CBC encryption and decryption using pycryptodome.
Used to optionally protect steganographic payloads with a password.
"""

import os
import base64
import hashlib
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad


# ─── Constants ────────────────────────────────────────────────────────────────
SALT_SIZE   = 16   # bytes  – random salt prepended to ciphertext
KEY_SIZE    = 32   # bytes  – AES-256
IV_SIZE     = 16   # bytes  – AES block size
ITERATIONS  = 200_000  # PBKDF2 iterations


def _derive_key(password: str, salt: bytes) -> bytes:
    """
    Derive a 256-bit AES key from a plaintext password using PBKDF2-HMAC-SHA256.

    Args:
        password: User-supplied plaintext password.
        salt:     Random 16-byte salt.

    Returns:
        32-byte derived key.
    """
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        ITERATIONS,
        dklen=KEY_SIZE,
    )


def encrypt_data(data: bytes, password: str) -> bytes:
    """
    Encrypt raw bytes with AES-256-CBC.

    Layout of output (all concatenated, then base64-encoded):
        [SALT (16 bytes)] [IV (16 bytes)] [CIPHERTEXT (padded)]

    Args:
        data:     Plaintext bytes to encrypt.
        password: User password string.

    Returns:
        Base64-encoded ciphertext blob (bytes).

    Raises:
        ValueError: If password is empty.
        Exception:  On any crypto error.
    """
    if not password:
        raise ValueError("Password must not be empty for encryption.")

    try:
        salt = os.urandom(SALT_SIZE)
        iv   = os.urandom(IV_SIZE)
        key  = _derive_key(password, salt)

        cipher = AES.new(key, AES.MODE_CBC, iv)
        ciphertext = cipher.encrypt(pad(data, AES.block_size))

        # Prepend salt and IV so decryption can recover them
        blob = salt + iv + ciphertext
        return base64.b64encode(blob)

    except Exception as exc:
        raise Exception(f"Encryption failed: {exc}") from exc


def decrypt_data(data: bytes, password: str) -> bytes:
    """
    Decrypt a blob produced by encrypt_data().

    Args:
        data:     Base64-encoded ciphertext blob (as returned by encrypt_data).
        password: User password string.

    Returns:
        Decrypted plaintext bytes.

    Raises:
        ValueError: On wrong password or corrupted data.
        Exception:  On any crypto error.
    """
    if not password:
        raise ValueError("Password must not be empty for decryption.")

    try:
        blob = base64.b64decode(data)

        if len(blob) < SALT_SIZE + IV_SIZE + AES.block_size:
            raise ValueError("Encrypted data is too short or corrupted.")

        salt       = blob[:SALT_SIZE]
        iv         = blob[SALT_SIZE:SALT_SIZE + IV_SIZE]
        ciphertext = blob[SALT_SIZE + IV_SIZE:]

        key    = _derive_key(password, salt)
        cipher = AES.new(key, AES.MODE_CBC, iv)

        plaintext = unpad(cipher.decrypt(ciphertext), AES.block_size)
        return plaintext

    except (ValueError, KeyError) as exc:
        raise ValueError(
            "Decryption failed — wrong password or corrupted data."
        ) from exc
    except Exception as exc:
        raise Exception(f"Decryption error: {exc}") from exc
