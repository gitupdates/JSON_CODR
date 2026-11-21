"""Argon2id password hashing without password persistence or logging."""

from __future__ import annotations

from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2 import Type
from argon2.exceptions import InvalidHashError, VerificationError


class PasswordHasher:
    """Small adapter that fixes the password algorithm to Argon2id."""

    def __init__(self) -> None:
        self._hasher = Argon2PasswordHasher(type=Type.ID)

    def hash_password(self, password: str) -> str:
        if not isinstance(password, str):
            raise TypeError("password must be a string")
        if not password:
            raise ValueError("password must not be empty")
        return self._hasher.hash(password)

    def verify_password(self, password: str, password_hash: str) -> bool:
        if not isinstance(password, str) or not isinstance(password_hash, str):
            raise TypeError("password and password_hash must be strings")
        try:
            return self._hasher.verify(password_hash, password)
        except (InvalidHashError, VerificationError):
            return False
