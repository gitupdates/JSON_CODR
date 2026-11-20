import hashlib
import json
from typing import Any


def configuration_hash(metadata: dict[str, Any]) -> str:
    canonical = json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
