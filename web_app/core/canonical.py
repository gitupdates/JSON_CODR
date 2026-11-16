from __future__ import annotations

import hashlib
from typing import Any

import rfc8785


def canonical_json(value: Any) -> bytes:
    return rfc8785.dumps(value)


def canonical_digest(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_json(value)).hexdigest()}"
