import hashlib
import hmac
import os
import re
from datetime import datetime, timezone


def now_utc():
    return datetime.now(timezone.utc)


def password_is_valid(password: str) -> tuple[bool, str]:
    if password is None:
        return False, "La clave es obligatoria."

    if len(password) <= 4:
        return False, "La clave debe tener más de 4 caracteres."

    if not re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", password):
        return False, "La clave debe tener al menos una letra."

    if not re.search(r"\d", password):
        return False, "La clave debe tener al menos un número."

    return True, ""


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    iterations = 240_000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations_s, salt_hex, hash_hex = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(candidate, expected)
    except Exception:
        return False


def normalize_report_for_copy(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n+", text)

    normalized_blocks = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        normalized_blocks.append(" ".join(lines))

    result = "\n\n".join(normalized_blocks)
    result = re.sub(r"[ \t]+", " ", result)
    return result.strip()
