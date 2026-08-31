#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
import platform
import stat
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "tools" / "ci_toolchain.json"
BROWSER_TREE_POLICY = {
    "schema": "mterrain-browser-immutable-tree-policy-v1",
    "excluded_exact": [
        "DEPENDENCIES_VALIDATED",
        "INSTALLATION_COMPLETE",
        "firefox/.parentlock",
    ],
    "excluded_prefixes": ["firefox/updates"],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def excluded_browser_tree_entry(relative: str) -> bool:
    if relative in BROWSER_TREE_POLICY["excluded_exact"]:
        return True
    return any(
        relative == prefix or relative.startswith(f"{prefix}/")
        for prefix in BROWSER_TREE_POLICY["excluded_prefixes"]
    )


def installation_tree(root: Path) -> dict[str, int | str]:
    digest = hashlib.sha256()
    regular_files = 0
    symlinks = 0
    directories = 0
    total_bytes = 0
    entries = sorted(root.rglob("*"), key=lambda value: value.relative_to(root).as_posix())
    for entry in entries:
        relative = entry.relative_to(root).as_posix()
        if excluded_browser_tree_entry(relative):
            continue
        metadata = entry.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISDIR(metadata.st_mode):
            record: list[Any] = ["directory", relative, mode]
            directories += 1
        elif stat.S_ISLNK(metadata.st_mode):
            record = ["symlink", relative, mode, os.readlink(entry)]
            symlinks += 1
        elif stat.S_ISREG(metadata.st_mode):
            file_digest = sha256(entry)
            record = ["file", relative, mode, metadata.st_size, file_digest]
            regular_files += 1
            total_bytes += metadata.st_size
        else:
            raise SystemExit(f"Unsupported browser-tree entry: {entry}")
        digest.update(
            json.dumps(record, separators=(",", ":"), ensure_ascii=True).encode(
                "utf-8"
            )
        )
        digest.update(b"\n")
    return {
        "tree_sha256": digest.hexdigest(),
        "regular_files": regular_files,
        "symlinks": symlinks,
        "directories": directories,
        "total_file_bytes": total_bytes,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browsers-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    browsers_root = args.browsers_root.expanduser().resolve()
    if not browsers_root.is_dir():
        raise SystemExit(f"Playwright browser directory is missing: {browsers_root}")
    configuration: dict[str, Any] = json.loads(CONFIG.read_text(encoding="utf-8"))
    expected = configuration["playwright"]
    if expected.get("linux_x86_64_tree_policy") != BROWSER_TREE_POLICY:
        raise SystemExit("Pinned Linux browser-tree policy is missing or inconsistent")
    actual_version = importlib.metadata.version("playwright")
    if actual_version != expected["version"]:
        raise SystemExit(
            f"Playwright version mismatch: expected {expected['version']}, got {actual_version}"
        )

    driver_root = Path(importlib.metadata.distribution("playwright").locate_file("playwright"))
    browsers_manifest = driver_root / "driver" / "package" / "browsers.json"
    if not browsers_manifest.is_file():
        raise SystemExit("Playwright browser revision manifest is missing")
    manifest = json.loads(browsers_manifest.read_text(encoding="utf-8"))
    selected_revisions = {
        record["name"]: {
            "revision": record["revision"],
            "browser_version": record.get("browserVersion"),
        }
        for record in manifest["browsers"]
        if record["name"] in expected["browsers"]
    }
    if set(selected_revisions) != set(expected["browsers"]):
        raise SystemExit("Playwright manifest omitted a required browser revision")
    executable_names = {
        "chromium": "chrome",
        "firefox": "firefox",
        "webkit": "pw_run.sh",
    }
    records: dict[str, Any] = {}
    expected_installations = expected.get("linux_x86_64_installations")
    if expected_installations is not None and set(expected_installations) != set(
        expected["browsers"]
    ):
        raise SystemExit("Pinned Linux browser-installation records are incomplete")
    for name in expected["browsers"]:
        revision = selected_revisions[name]["revision"]
        installation = browsers_root / f"{name}-{revision}"
        completion_marker = installation / "INSTALLATION_COMPLETE"
        if not completion_marker.is_file() or completion_marker.stat().st_size != 0:
            raise SystemExit(f"Pinned {name} browser installation is incomplete")
        candidates = sorted(installation.rglob(executable_names[name]))
        candidates = [
            candidate
            for candidate in candidates
            if candidate.is_file() and candidate.stat().st_size > 0
        ]
        if len(candidates) != 1:
            raise SystemExit(
                f"Expected one pinned {name} launcher under {installation}, got {len(candidates)}"
            )
        executable = candidates[0].resolve()
        tree = installation_tree(installation)
        expected_tree = (
            expected_installations.get(name)
            if isinstance(expected_installations, dict)
            else None
        )
        if expected_tree is not None:
            if expected_tree.get("revision") != revision:
                raise SystemExit(f"Pinned {name} installation revision drift")
            for key, value in tree.items():
                if expected_tree.get(key) != value:
                    raise SystemExit(
                        f"Pinned {name} browser installation drift: {key}; "
                        f"expected {expected_tree.get(key)!r}, got {value!r}"
                    )
        records[name] = {
            "installation_relative": str(installation.relative_to(browsers_root)),
            **tree,
            "executable_relative": str(executable.relative_to(browsers_root)),
            "executable_sha256": sha256(executable),
            "executable_size": executable.stat().st_size,
        }

    receipt = {
        "schema": "mterrain-browser-toolchain-receipt-v2",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "host": platform.platform(),
        "configuration": {
            "path": "tools/ci_toolchain.json",
            "sha256": sha256(CONFIG),
        },
        "playwright": {
            "version": actual_version,
            "wheels": expected["wheels"],
            "browser_revisions": selected_revisions,
            "installation_tree_policy": BROWSER_TREE_POLICY,
            "browsers": records,
        },
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
