from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        request = json.loads(sys.stdin.readline())
        if request.get("operation") == "health":
            response = {"ok": True, "result": {"status": "ready"}}
        else:
            response = {"ok": False, "error": "Unsupported connector operation"}
    except Exception as error:
        response = {"ok": False, "error": str(error)}
    sys.stdout.write(json.dumps(response) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
