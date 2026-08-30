#!/usr/bin/env python3
"""Print short 'you are ready' summary (URLs, seed users, next steps)."""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--started", action="store_true", help="Dev servers were started")
    parser.add_argument("--seeded", action="store_true", help="ACL seed was attempted")
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  Enterprise Search — local setup complete")
    print("=" * 60)
    print()
    print("  URLs")
    print("    UI          http://localhost:5173")
    print("    API         http://localhost:8000")
    print("    API docs    http://localhost:8000/docs")
    print("    Keycloak    http://localhost:8080")
    print("    OpenSearch  http://localhost:9200")
    print("    MinIO API   http://localhost:9000")
    print("    MinIO UI    http://localhost:9001")
    print()
    print("  Seed users (local demo)")
    print("    realm-admin / adminpass   (search + admin)")
    print("    searcher    / searcherpass (search only)")
    print()
    print("  Next")
    if args.started:
        print("    Dev servers are running (Ctrl+C to stop).")
    else:
        print("    ./start-dev.sh")
        print("    # or: ./setup/setup.sh --start")
    print("    Open the UI, sign in, upload PDF/TXT/CSV.")
    if not args.seeded:
        print("    After upload: ./setup/setup.sh --skip-compose --skip-init --with-seed")
        print("    (or: cd backend && uv run python -m scripts.seed_file_acl_for_proofs)")
    print("    Admin ACL: /admin as realm-admin (if Task 6 UI is available).")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
