#!/usr/bin/env python3
from __future__ import annotations

import argparse
import functools
from pathlib import Path

from run_web_smoke import SmokeHandler, ThreadingServer
from web_evidence_common import load_object


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-dir", required=True, type=Path)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8060)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session_dir = args.session_dir.expanduser().resolve()
    manifest_path = session_dir / "rollback-session.json"
    manifest = load_object(manifest_path, "rollback session")
    if manifest.get("schema") != "mterrain-web-rollback-session-v1":
        raise SystemExit("Unexpected rollback-session schema")
    if not 0 <= args.port <= 65535:
        raise SystemExit("Port must be between 0 and 65535")
    handler = functools.partial(SmokeHandler, directory=str(session_dir))
    with ThreadingServer((args.bind, args.port), handler) as server:
        port = server.server_address[1]
        print(f"Rollback session: {manifest['session_id']}")
        print(f"Candidate: http://{args.bind}:{port}/candidate/export/index.html")
        print(f"Prior:     http://{args.bind}:{port}/prior/export/index.html")
        print("Capture candidate first, then prior. Press Ctrl-C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
