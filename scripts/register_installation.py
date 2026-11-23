from __future__ import annotations

import argparse
import json
from pathlib import Path

from web_app.integrations.installation import DEFAULT_SERVICE_URL, register_installation


def main() -> int:
    parser = argparse.ArgumentParser(description="Register this JSON_CODR installation for local connectors.")
    parser.add_argument("root", type=Path)
    parser.add_argument("--service-url", default=DEFAULT_SERVICE_URL)
    arguments = parser.parse_args()
    manifest = register_installation(arguments.root, arguments.service_url)
    print(json.dumps(manifest.as_json()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
