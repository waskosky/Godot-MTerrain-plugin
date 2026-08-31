#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from web_evidence_common import load_object, sha256


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-dir", required=True, type=Path)
    parser.add_argument("--prior-dir", required=True, type=Path)
    parser.add_argument("--candidate-native-library", required=True, type=Path)
    parser.add_argument("--prior-native-library", required=True, type=Path)
    parser.add_argument("--godot", required=True, type=Path)
    parser.add_argument("--template-debug", required=True, type=Path)
    parser.add_argument("--template-receipt", required=True, type=Path)
    parser.add_argument(
        "--profile", choices=("web_core", "web_extended"), default="web_core"
    )
    parser.add_argument("--session-id", default=str(uuid.uuid4()))
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def package_module() -> Any:
    path = ROOT / "scripts" / "package_web_release.py"
    specification = importlib.util.spec_from_file_location("mterrain_package", path)
    if specification is None or specification.loader is None:
        raise SystemExit("Could not load the release verifier")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def release_index(directory: Path) -> tuple[Path, dict[str, Any]]:
    indices = sorted(directory.glob("Godot-MTerrain-*-release-index.json"))
    if len(indices) != 1:
        raise SystemExit(f"Expected exactly one release index in {directory}")
    return indices[0], load_object(indices[0], "release index")


def extract_profile(
    module: Any,
    release_dir: Path,
    index: dict[str, Any],
    profile: str,
    destination: Path,
) -> tuple[Path, Path]:
    profile_index = index["profiles"][profile]
    bundle_path = release_dir / profile_index["bundle"]["name"]
    members = module.safe_archive_members(bundle_path, index["source_date_epoch"])
    archive_root = profile_index["archive_root"]
    prefix = archive_root + "/"
    for name, data in members.items():
        if not name.startswith(prefix):
            raise SystemExit(f"Bundle member escaped its archive root: {name}")
        relative = Path(name.removeprefix(prefix))
        target = destination / relative
        resolved = target.resolve()
        if destination.resolve() not in resolved.parents:
            raise SystemExit(f"Bundle member escaped rollback staging: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return destination, bundle_path


def require_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise SystemExit(f"{label} is missing or empty: {resolved}")
    return resolved


def main() -> int:
    args = parse_args()
    if not args.session_id or len(args.session_id) > 96:
        raise SystemExit("Rollback session ID must contain 1..96 characters")
    candidate_dir = args.candidate_dir.expanduser().resolve()
    prior_dir = args.prior_dir.expanduser().resolve()
    if candidate_dir == prior_dir:
        raise SystemExit("Candidate and prior release directories must differ")
    for directory, label in ((candidate_dir, "candidate"), (prior_dir, "prior")):
        if not directory.is_dir():
            raise SystemExit(f"{label} release directory is missing: {directory}")
    godot = require_file(args.godot, "Godot editor")
    template = require_file(args.template_debug, "Web export template")
    template_receipt_path = require_file(args.template_receipt, "template receipt")
    template_receipt = load_object(template_receipt_path, "template receipt")
    if template_receipt.get("schema") != "mterrain-web-template-receipt-v1":
        raise SystemExit("Unexpected Web template-receipt schema")
    if template_receipt.get("artifact", {}).get("sha256") != sha256(template):
        raise SystemExit("Web template does not match its immutable receipt")

    output = args.output
    if output is None:
        output = ROOT / "build" / "rollback" / args.session_id
    output = output.expanduser().resolve()
    build_root = (ROOT / "build").resolve()
    if output == build_root or build_root not in output.parents:
        raise SystemExit(f"Rollback output must be below {build_root}: {output}")
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Rollback output already contains data: {output}")
    output.mkdir(parents=True, exist_ok=True)

    module = package_module()
    module.verify(candidate_dir)
    module.verify(prior_dir)
    candidate_index_path, candidate_index = release_index(candidate_dir)
    prior_index_path, prior_index = release_index(prior_dir)
    if candidate_index["version"] == prior_index["version"]:
        raise SystemExit("Candidate and prior release versions must differ")

    stages = [
        (
            "candidate",
            candidate_dir,
            candidate_index_path,
            candidate_index,
            require_file(args.candidate_native_library, "candidate native library"),
        ),
        (
            "prior",
            prior_dir,
            prior_index_path,
            prior_index,
            require_file(args.prior_native_library, "prior native library"),
        ),
    ]
    manifest: dict[str, Any] = {
        "schema": "mterrain-web-rollback-session-v1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "session_id": args.session_id,
        "profile": args.profile,
        "sequence": ["candidate", "prior"],
        "template_receipt": {
            "name": template_receipt_path.name,
            "sha256": sha256(template_receipt_path),
            "artifact_sha256": sha256(template),
        },
        "stages": {},
    }
    for stage, release_dir, index_path, index, native in stages:
        stage_dir = output / stage
        bundle_root, bundle_path = extract_profile(
            module,
            release_dir,
            index,
            args.profile,
            stage_dir / "bundle",
        )
        context = {
            "schema": "mterrain-web-rollback-context-v1",
            "session_id": args.session_id,
            "stage": stage,
            "profile": args.profile,
            "version": index["version"],
            "release_index_sha256": sha256(index_path),
            "bundle_name": bundle_path.name,
            "bundle_sha256": sha256(bundle_path),
            "native_library_sha256": sha256(native),
            "template_sha256": sha256(template),
        }
        context_path = stage_dir / "rollback-context.json"
        context_path.write_text(
            json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        export_dir = stage_dir / "export"
        command = [
            sys.executable,
            str(ROOT / "scripts" / "export_web_smoke.py"),
            "--godot",
            str(godot),
            "--template-debug",
            str(template),
            "--native-library",
            str(native),
            "--profile",
            args.profile,
            "--fixture",
            "rollback",
            "--bundle-root",
            str(bundle_root),
            "--rollback-context",
            str(context_path),
            "--output",
            str(export_dir),
        ]
        subprocess.run(command, cwd=ROOT, check=True)
        manifest["stages"][stage] = {
            **context,
            "export_relative": str(export_dir.relative_to(output)),
            "export_index_sha256": sha256(export_dir / "index.html"),
            "export_side_module_sha256": sha256(
                export_dir / "libMTerrain.web.template_debug.wasm32.nothreads.wasm"
            ),
        }

    manifest_path = output / "rollback-session.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(manifest_path)
    print(
        "Serve this directory over HTTPS or a trusted LAN. Open candidate/export/ "
        "and download its receipt before opening prior/export/."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
