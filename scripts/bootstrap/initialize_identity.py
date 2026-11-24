"""Secure stdin-only first-run identity initializer used by bootstrap.ps1."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from web_app.core.cli_identity import CliIdentityService, DpapiTokenStore
from web_app.core.identity import IdentityService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--username", default="Administrator")
    parser.add_argument("--origin", required=True)
    args = parser.parse_args()
    password = sys.stdin.readline().rstrip("\r\n")
    if not password:
        raise ValueError("Administrator password was not provided")
    root = Path(args.data_root)
    identity = IdentityService(root)
    result = identity.bootstrap_nonproduction_administrator(password, args.username)
    cli = CliIdentityService(identity, DpapiTokenStore(Path.home() / ".json_codr" / "credentials" / "cli.dpapi"))
    cli.login(args.username, password, machine="JSON_CODR bootstrap", server_origin=args.origin)
    print(json.dumps({"created": result.created, "account": result.user.username, "credential_policy": "non-expiring, revocable (non-production)"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
