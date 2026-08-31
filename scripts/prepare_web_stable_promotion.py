#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import package_web_release as packager
from web_evidence_common import load_object, sha256


ROOT = Path(__file__).resolve().parents[1]
STABLE_VERSION = re.compile(r"web-runtime-v[0-9]+\.[0-9]+\.[0-9]+\Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-dir", type=Path)
    parser.add_argument("--prior-dir", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-dir", type=Path)
    return parser.parse_args()


def release_index(directory: Path, label: str) -> tuple[Path, dict[str, Any]]:
    indices = sorted(directory.glob("Godot-MTerrain-*-release-index.json"))
    if len(indices) != 1:
        raise SystemExit(f"{label} must contain exactly one release index")
    return indices[0], load_object(indices[0], f"{label} release index")


def package_assets(directory: Path) -> list[Path]:
    checksums = directory / "SHA256SUMS"
    names = {"SHA256SUMS"}
    for line in checksums.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"[0-9a-f]{64}  ([A-Za-z0-9._-]+)", line)
        if match is None:
            raise SystemExit(f"Malformed candidate SHA256SUMS entry: {line!r}")
        names.add(match.group(1))
    assets = [directory / name for name in sorted(names)]
    if any(not path.is_file() for path in assets):
        raise SystemExit("Candidate package asset set is incomplete")
    return assets


def selected_evidence(
    status: dict[str, Any], evidence_dir: Path
) -> list[tuple[str, Path, str]]:
    records: list[tuple[str, Path, str]] = []
    hosted = status.get("hosted_correctness")
    if isinstance(hosted, dict):
        records.append(
            (
                f"{status['profile']}/hosted",
                evidence_dir / str(hosted.get("relative_path", "")),
                str(hosted.get("sha256", "")),
            )
        )
    for category in ("performance", "rollback"):
        for lane, record in sorted(status.get(category, {}).items()):
            if not isinstance(record, dict):
                raise SystemExit(f"Stable status has an invalid {category} record")
            records.append(
                (
                    f"{status['profile']}/{category}/{lane}",
                    evidence_dir / str(record.get("relative_path", "")),
                    str(record.get("sha256", "")),
                )
            )
    return records


def verify(directory: Path, prior_dir: Path) -> None:
    directory = directory.expanduser().resolve()
    if not directory.is_dir():
        raise SystemExit(f"Stable promotion directory is missing: {directory}")
    checksum_path = directory / "STABLE_PROMOTION_SHA256SUMS"
    expected: dict[str, str] = {}
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if match is None or match.group(2) in expected:
            raise SystemExit(f"Malformed stable-promotion checksum: {line!r}")
        expected[match.group(2)] = match.group(1)
    actual_names = {
        path.name
        for path in directory.iterdir()
        if path.is_file() and path.name != checksum_path.name
    }
    if set(expected) != actual_names:
        raise SystemExit("Stable-promotion checksum set is incomplete or contains extras")
    for name, digest in expected.items():
        if sha256(directory / name) != digest:
            raise SystemExit(f"Stable-promotion checksum mismatch: {name}")

    packager.verify(directory)
    manifests = sorted(directory.glob("*-stable-promotion.json"))
    if len(manifests) != 1:
        raise SystemExit("Stable promotion must contain exactly one promotion manifest")
    manifest_path = manifests[0]
    manifest = load_object(manifest_path, "stable promotion manifest")
    if (
        manifest.get("schema") != "mterrain-web-stable-promotion-v1"
        or manifest.get("passed") is not True
        or not isinstance(manifest.get("version"), str)
        or STABLE_VERSION.fullmatch(manifest["version"]) is None
    ):
        raise SystemExit("Stable promotion manifest identity is invalid")
    index_path, index = release_index(directory, "stable promotion")
    if (
        index.get("version") != manifest["version"]
        or manifest.get("source") != index.get("source")
        or manifest.get("candidate", {}).get("release_index_name")
        != index_path.name
        or manifest.get("candidate", {}).get("release_index_sha256")
        != sha256(index_path)
    ):
        raise SystemExit("Stable promotion candidate binding is invalid")
    actual_assets = {
        path.name: {"sha256": sha256(path), "size": path.stat().st_size}
        for path in package_assets(directory)
    }
    manifest_assets = {
        record.get("name"): {
            "sha256": record.get("sha256"),
            "size": record.get("size"),
        }
        for record in manifest.get("candidate", {}).get("assets", [])
        if isinstance(record, dict)
    }
    if manifest_assets != actual_assets:
        raise SystemExit("Stable promotion candidate asset manifest is invalid")

    calibration_record = manifest.get("calibration", {})
    calibration_path = directory / str(calibration_record.get("name", ""))
    calibration = load_object(calibration_path, "stable calibration approval")
    if (
        calibration.get("schema") != "mterrain-web-performance-calibration-v1"
        or calibration.get("release_gate_eligible") is not True
        or calibration.get("candidate_release", {}).get("version")
        != manifest["version"]
        or calibration.get("candidate_release", {}).get("release_index_sha256")
        != sha256(index_path)
        or calibration_record.get("sha256") != sha256(calibration_path)
    ):
        raise SystemExit("Stable promotion calibration binding is invalid")
    calibration_digest = sha256(calibration_path)
    for profile in ("web_core", "web_extended"):
        record = manifest.get("gate_status", {}).get(profile, {})
        status_path = directory / str(record.get("name", ""))
        status = load_object(status_path, f"{profile} stable status")
        if (
            record.get("sha256") != sha256(status_path)
            or status.get("schema") != "mterrain-web-release-gate-status-v1"
            or status.get("profile") != profile
            or status.get("candidate_version") != manifest["version"]
            or status.get("stable_ready") is not True
            or status.get("candidate_release_bound") is not True
            or status.get("prior_release_bound") is not True
            or status.get("calibration_candidate_bound") is not True
            or status.get("calibration_contract_sha256") != calibration_digest
        ):
            raise SystemExit(f"Stable promotion gate status is invalid: {profile}")
    for record in manifest.get("evidence", []):
        if not isinstance(record, dict):
            raise SystemExit("Stable promotion has an invalid evidence record")
        evidence_path = directory / str(record.get("name", ""))
        if (
            not evidence_path.is_file()
            or record.get("sha256") != sha256(evidence_path)
            or not str(record.get("purpose", "")).strip()
        ):
            raise SystemExit("Stable promotion evidence binding is invalid")
    for profile in ("web_core", "web_extended"):
        command = [
            sys.executable,
            str(ROOT / "scripts" / "verify_web_release_gate.py"),
            "--profile",
            profile,
            "--candidate-dir",
            str(directory),
            "--prior-dir",
            str(prior_dir),
            "--candidate-version",
            manifest["version"],
            "--evidence-dir",
            str(directory),
            "--calibration",
            str(calibration_path),
            "--require-stable",
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if completed.returncode != 0:
            raise SystemExit(completed.stdout.rstrip())
    print(f"MTERRAIN_WEB_STABLE_PROMOTION_VERIFY_OK {manifest['version']}")


def main() -> int:
    args = parse_args()
    if args.verify_dir is not None:
        if args.prior_dir is None:
            raise SystemExit("--verify-dir requires the verified --prior-dir")
        if any(
            value is not None
            for value in (
                args.candidate_dir,
                args.evidence_dir,
                args.calibration,
                args.output,
            )
        ):
            raise SystemExit("--verify-dir cannot be combined with preparation inputs")
        verify(args.verify_dir, args.prior_dir.expanduser().resolve())
        return 0
    if any(
        value is None
        for value in (
            args.candidate_dir,
            args.prior_dir,
            args.evidence_dir,
            args.calibration,
        )
    ):
        raise SystemExit(
            "Preparation requires --candidate-dir, --prior-dir, --evidence-dir, "
            "and --calibration"
        )
    candidate_dir = args.candidate_dir.expanduser().resolve()
    prior_dir = args.prior_dir.expanduser().resolve()
    evidence_dir = args.evidence_dir.expanduser().resolve()
    calibration = args.calibration.expanduser().resolve()
    if candidate_dir == prior_dir:
        raise SystemExit("Candidate and prior release directories must differ")
    if not evidence_dir.is_dir() or not calibration.is_file():
        raise SystemExit("Stable evidence directory and calibration receipt must exist")
    packager.verify(candidate_dir)
    packager.verify(prior_dir)
    candidate_index_path, candidate_index = release_index(candidate_dir, "candidate")
    prior_index_path, prior_index = release_index(prior_dir, "prior")
    version = candidate_index.get("version")
    if not isinstance(version, str) or STABLE_VERSION.fullmatch(version) is None:
        raise SystemExit("Stable candidate version must match web-runtime-vX.Y.Z")
    if candidate_index.get("source", {}).get("mterrain_dirty") is not False:
        raise SystemExit("Stable candidate source must be clean")

    statuses: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="mterrain-stable-promotion-") as temporary:
        temporary_root = Path(temporary)
        for profile in ("web_core", "web_extended"):
            status_path = temporary_root / f"release-gate-{profile}.json"
            command = [
                sys.executable,
                str(ROOT / "scripts" / "verify_web_release_gate.py"),
                "--profile",
                profile,
                "--candidate-dir",
                str(candidate_dir),
                "--prior-dir",
                str(prior_dir),
                "--candidate-version",
                version,
                "--evidence-dir",
                str(evidence_dir),
                "--calibration",
                str(calibration),
                "--write-status",
                str(status_path),
                "--require-stable",
            ]
            completed = subprocess.run(
                command,
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if completed.returncode != 0:
                raise SystemExit(completed.stdout.rstrip())
            status = load_object(status_path, f"{profile} stable-gate status")
            if (
                status.get("stable_ready") is not True
                or status.get("candidate_release_bound") is not True
                or status.get("prior_release_bound") is not True
                or status.get("calibration_candidate_bound") is not True
            ):
                raise SystemExit(f"Stable gate returned an incomplete status for {profile}")
            statuses[profile] = status

        output = args.output
        if output is None:
            output = ROOT / "build" / "stable-promotion" / version
        output = output.expanduser().resolve()
        build_root = (ROOT / "build").resolve()
        if output == build_root or build_root not in output.parents:
            raise SystemExit(f"Stable promotion output must be below {build_root}: {output}")
        if output.exists() and any(output.iterdir()):
            raise SystemExit(f"Stable promotion output already contains data: {output}")
        output.mkdir(parents=True, exist_ok=True)

        candidate_assets: list[dict[str, Any]] = []
        for source in package_assets(candidate_dir):
            destination = output / source.name
            shutil.copy2(source, destination)
            candidate_assets.append(
                {"name": destination.name, "sha256": sha256(destination), "size": destination.stat().st_size}
            )
        calibration_output = output / "web-performance-calibration-approved.json"
        shutil.copy2(calibration, calibration_output)

        evidence_records: list[dict[str, str]] = []
        copied_evidence: dict[str, str] = {}
        for profile, status in statuses.items():
            status_output = output / f"web-release-gate-status-{profile}.json"
            status_output.write_text(
                json.dumps(status, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            for purpose, source, expected_digest in selected_evidence(
                status, evidence_dir
            ):
                resolved = source.expanduser().resolve()
                if evidence_dir != resolved and evidence_dir not in resolved.parents:
                    raise SystemExit(f"Selected evidence escaped its input directory: {resolved}")
                digest = sha256(resolved)
                if digest != expected_digest:
                    raise SystemExit(f"Selected evidence digest changed: {resolved}")
                destination_name = copied_evidence.get(digest)
                if destination_name is None:
                    destination_name = f"web-stable-evidence-{digest[:16]}.json"
                    shutil.copy2(resolved, output / destination_name)
                    copied_evidence[digest] = destination_name
                evidence_records.append(
                    {"purpose": purpose, "name": destination_name, "sha256": digest}
                )

    prior_profiles = {
        profile: {
            "bundle_sha256": value["bundle"]["sha256"],
            "bundle_name": value["bundle"]["name"],
        }
        for profile, value in sorted(prior_index["profiles"].items())
    }
    manifest = {
        "schema": "mterrain-web-stable-promotion-v1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "version": version,
        "source": candidate_index["source"],
        "candidate": {
            "release_index_name": candidate_index_path.name,
            "release_index_sha256": sha256(candidate_index_path),
            "assets": candidate_assets,
        },
        "prior": {
            "version": prior_index["version"],
            "release_index_sha256": sha256(prior_index_path),
            "profiles": prior_profiles,
        },
        "calibration": {
            "name": calibration_output.name,
            "sha256": sha256(calibration_output),
        },
        "evidence": sorted(evidence_records, key=lambda value: value["purpose"]),
        "gate_status": {
            profile: {
                "name": f"web-release-gate-status-{profile}.json",
                "sha256": sha256(output / f"web-release-gate-status-{profile}.json"),
            }
            for profile in sorted(statuses)
        },
        "passed": True,
    }
    manifest_path = output / f"{version}-stable-promotion.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    checksum_paths = sorted(
        (path for path in output.iterdir() if path.is_file()),
        key=lambda path: path.name,
    )
    (output / "STABLE_PROMOTION_SHA256SUMS").write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in checksum_paths),
        encoding="utf-8",
    )
    verify(output, prior_dir)
    print(output)
    print("MTERRAIN_WEB_STABLE_PROMOTION_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
