"""Tokens de registro: se entregan a la persona y en la base solo se guarda su hash."""

import hashlib
import hmac
import secrets


def generar_token() -> str:
    """Crea un token aleatorio imposible de adivinar."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Convierte el token en un hash SHA-256 (64 caracteres) para guardarlo."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_coincide(token: str, hash_guardado: str | None) -> bool:
    """Compara el token recibido contra el hash guardado en la base."""
    if not hash_guardado:
        return False
    return hmac.compare_digest(hash_token(token), hash_guardado)