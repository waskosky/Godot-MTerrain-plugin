#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "build" / "distribution"
RUNTIME_CONTRACT_RELATIVE = "runtime/web_runtime_contract.json"
PERFORMANCE_BUDGETS_RELATIVE = "tools/web_performance_budgets.json"
PERFORMANCE_CALIBRATION_RELATIVE = "tools/web_performance_calibration.json"
RELEASE_GATE_RELATIVE = "tools/web_release_gate.json"
VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")
PROFILES = {
    "web_core": {
        "artifact_dir": ROOT / "build" / "mterrain",
        "receipt_prefix": "web",
        "runtime_companion": None,
    },
    "web_extended": {
        "artifact_dir": ROOT / "build" / "mterrain" / "web_extended",
        "receipt_prefix": "web-extended",
        "runtime_companion": ROOT / "runtime" / "web_extended_runtime.gd",
    },
}
TARGETS = ("template_debug", "template_release")
PERFORMANCE_FIXTURE_FILES = (
    "tests/web_performance/main.gd",
    "tests/web_performance/evidence_bridge.js",
    "tests/web_smoke/main.tscn",
    "tests/web_smoke/project.godot",
)
COMMON_FILES = (
    "LICENSE",
    "README.md",
    "docs/WEB_RUNTIME_API.md",
    "docs/WEB_RUNTIME_ROADMAP.md",
    "docs/WEB_RELEASE_PROCESS.md",
    "docs/WEB_SUPPORT_MATRIX.md",
    RUNTIME_CONTRACT_RELATIVE,
    PERFORMANCE_BUDGETS_RELATIVE,
    PERFORMANCE_CALIBRATION_RELATIVE,
    RELEASE_GATE_RELATIVE,
    "start_material_opengl.res",
    "start_opengl.gdshader",
    "start_opengl.gdshader.uid",
    *PERFORMANCE_FIXTURE_FILES,
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def threshold_contract_sha256(budgets: dict[str, Any]) -> str:
    contract = {
        "schema": budgets.get("schema"),
        "fixture": budgets.get("fixture"),
        "profiles": budgets.get("profiles"),
    }
    encoded = json.dumps(
        contract, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256_bytes(encoded)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", "-C", str(cwd), *args], text=True
    ).strip()


def require_file(path: Path, label: str) -> Path:
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"{label} is missing or empty: {path}")
    return path


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"Invalid JSON file {path}: {error}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"Expected a JSON object in {path}")
    return value


def source_epoch() -> int:
    return int(git("show", "-s", "--format=%ct", "HEAD"))


def iso8601(epoch: int) -> str:
    return dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc).isoformat()


def archive_bytes(files: dict[str, bytes], epoch: int) -> bytes:
    compressed = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        fileobj=compressed,
        compresslevel=9,
        mtime=epoch,
    ) as gzip_handle:
        with tarfile.open(
            fileobj=gzip_handle, mode="w", format=tarfile.USTAR_FORMAT
        ) as archive:
            for name in sorted(files):
                data = files[name]
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                info.mode = 0o644
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = epoch
                archive.addfile(info, io.BytesIO(data))
    return compressed.getvalue()


def bundle_common_files(archive_root: str) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for relative in COMMON_FILES:
        source = require_file(ROOT / relative, relative)
        destination = relative
        if relative.startswith("start_"):
            destination = f"addons/m_terrain/{relative}"
        files[f"{archive_root}/{destination}"] = source.read_bytes()
    return files


def validated_receipt(
    path: Path,
    *,
    profile: str,
    target: str,
    artifact: Path,
    commit: str,
    tree: str,
    godot_cpp_commit: str,
    expected_capabilities: dict[str, Any],
) -> dict[str, Any]:
    receipt = read_json(path)
    if receipt.get("schema") != "mterrain-web-build-receipt-v2":
        raise SystemExit(f"Unexpected receipt schema in {path}")
    source = receipt.get("source", {})
    expected_source = {
        "mterrain_commit": commit,
        "mterrain_tree": tree,
        "mterrain_dirty": False,
        "godot_cpp_commit": godot_cpp_commit,
    }
    for key, expected in expected_source.items():
        if source.get(key) != expected:
            raise SystemExit(
                f"Receipt source mismatch in {path}: {key} must be {expected!r}"
            )
    receipt_target = receipt.get("target", {})
    if receipt_target.get("profile") != profile:
        raise SystemExit(f"Receipt profile mismatch in {path}")
    if receipt_target.get("target") != target:
        raise SystemExit(f"Receipt target mismatch in {path}")
    receipt_capabilities = receipt_target.get("capabilities", {})
    for key, expected in expected_capabilities.items():
        if receipt_capabilities.get(key) != expected:
            raise SystemExit(
                f"Receipt capability mismatch in {path}: {key} must be {expected!r}"
            )
    artifact_record = receipt.get("artifact", {})
    if artifact_record.get("name") != artifact.name:
        raise SystemExit(f"Receipt artifact name mismatch in {path}")
    if artifact_record.get("size") != artifact.stat().st_size:
        raise SystemExit(f"Receipt artifact size mismatch in {path}")
    if artifact_record.get("sha256") != sha256_file(artifact):
        raise SystemExit(f"Receipt artifact digest mismatch in {path}")
    return receipt


def package(version: str, output: Path) -> None:
    if not VERSION_PATTERN.fullmatch(version):
        raise SystemExit(
            "Version must contain only letters, digits, dots, underscores, or dashes"
        )
    dirty = git(
        "status",
        "--porcelain",
        "--untracked-files=normal",
        "--ignore-submodules=dirty",
    )
    if dirty:
        raise SystemExit("Release packaging refuses to use a dirty source tree")

    commit = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    godot_cpp_commit = git(
        "rev-parse", "HEAD", cwd=ROOT / "gdextension" / "godot-cpp"
    )
    epoch = source_epoch()
    output = output.expanduser().resolve()
    build_root = (ROOT / "build").resolve()
    if output == build_root or build_root not in output.parents:
        raise SystemExit(
            f"Distribution output must be below the build directory: {build_root}"
        )
    output.mkdir(parents=True, exist_ok=True)

    manifest = require_file(
        ROOT / "build" / "mterrain" / "MTerrain.gdextension",
        "generated Web manifest",
    )
    support_matrix = require_file(
        ROOT / "docs" / "WEB_SUPPORT_MATRIX.md", "Web support matrix"
    )
    runtime_contract_path = require_file(
        ROOT / RUNTIME_CONTRACT_RELATIVE, "Web runtime contract"
    )
    runtime_contract = read_json(runtime_contract_path)
    if runtime_contract.get("schema") != "mterrain-web-runtime-contract-v1":
        raise SystemExit("Unexpected Web runtime contract schema")
    if runtime_contract.get("contract_version") != 1:
        raise SystemExit("Unexpected Web runtime contract version")
    contract_profiles = runtime_contract.get("profiles", {})
    if set(contract_profiles) != set(PROFILES):
        raise SystemExit("Web runtime contract must describe both release profiles")
    runtime_contract_name = f"Godot-MTerrain-{version}-runtime-contract.json"
    runtime_contract_output = output / runtime_contract_name
    runtime_contract_output.write_bytes(runtime_contract_path.read_bytes())
    performance_budgets_path = require_file(
        ROOT / PERFORMANCE_BUDGETS_RELATIVE, "Web performance budgets"
    )
    performance_calibration_path = require_file(
        ROOT / PERFORMANCE_CALIBRATION_RELATIVE, "Web performance calibration"
    )
    release_gate_path = require_file(
        ROOT / RELEASE_GATE_RELATIVE, "Web release gate"
    )
    performance_budgets = read_json(performance_budgets_path)
    performance_calibration = read_json(performance_calibration_path)
    if performance_budgets.get("schema") != (
        "mterrain-web-performance-budgets-v1"
    ):
        raise SystemExit("Unexpected Web performance-budget schema")
    if performance_calibration.get("schema") != (
        "mterrain-web-performance-calibration-v1"
    ):
        raise SystemExit("Unexpected Web performance-calibration schema")
    if performance_calibration.get("threshold_contract_sha256") != (
        threshold_contract_sha256(performance_budgets)
    ):
        raise SystemExit("Performance calibration targets different thresholds")
    if performance_calibration.get("release_gate_eligible") is not False:
        raise SystemExit(
            "Release packages must carry the provisional calibration template; "
            "candidate-bound approval is post-build evidence"
        )
    if read_json(release_gate_path).get("schema") != (
        "mterrain-web-release-gate-v1"
    ):
        raise SystemExit("Unexpected Web release-gate schema")
    index: dict[str, Any] = {
        "schema": "mterrain-web-release-index-v1",
        "version": version,
        "created_at": iso8601(epoch),
        "source_date_epoch": epoch,
        "source": {
            "mterrain_commit": commit,
            "mterrain_tree": tree,
            "mterrain_dirty": False,
            "godot_cpp_commit": godot_cpp_commit,
        },
        "target": {
            "godot": "4.7.stable.official.5b4e0cb0f",
            "platform": "web",
            "architecture": "wasm32",
            "renderer": "Compatibility",
            "web_api": "WebGL2",
            "precision": "single",
            "threads": False,
            "dynamic_linking": True,
        },
        "support_matrix": {
            "path": "docs/WEB_SUPPORT_MATRIX.md",
            "sha256": sha256_file(support_matrix),
        },
        "runtime_contract": {
            "name": runtime_contract_name,
            "bundle_path": RUNTIME_CONTRACT_RELATIVE,
            "schema": runtime_contract["schema"],
            "contract_version": runtime_contract["contract_version"],
            "sha256": sha256_file(runtime_contract_output),
            "size": runtime_contract_output.stat().st_size,
        },
        "performance_budgets": {
            "path": PERFORMANCE_BUDGETS_RELATIVE,
            "schema": "mterrain-web-performance-budgets-v1",
            "sha256": sha256_file(performance_budgets_path),
            "size": performance_budgets_path.stat().st_size,
        },
        "performance_calibration": {
            "path": PERFORMANCE_CALIBRATION_RELATIVE,
            "schema": "mterrain-web-performance-calibration-v1",
            "sha256": sha256_file(performance_calibration_path),
            "size": performance_calibration_path.stat().st_size,
        },
        "release_gate": {
            "path": RELEASE_GATE_RELATIVE,
            "schema": "mterrain-web-release-gate-v1",
            "sha256": sha256_file(release_gate_path),
            "size": release_gate_path.stat().st_size,
        },
        "profiles": {},
    }

    for profile, configuration in PROFILES.items():
        archive_root = f"Godot-MTerrain-{version}-{profile}"
        files = bundle_common_files(archive_root)
        files[f"{archive_root}/mterrain/MTerrain.gdextension"] = (
            manifest.read_bytes()
        )
        profile_index: dict[str, Any] = {
            "archive_root": archive_root,
            "capability_contract": contract_profiles[profile][
                "capability_contract"
            ],
            "artifacts": {},
        }
        expected_capabilities = {
            **contract_profiles["web_core"]["required_capabilities"],
            **contract_profiles["web_core"]["unsupported_capabilities"],
        }
        if profile == "web_extended":
            expected_capabilities.update(
                contract_profiles[profile]["native_required_capabilities"]
            )
        for target in TARGETS:
            artifact = require_file(
                configuration["artifact_dir"]
                / f"libMTerrain.web.{target}.wasm32.nothreads.wasm",
                f"{profile} {target} artifact",
            )
            receipt_path = require_file(
                ROOT
                / "build"
                / "receipts"
                / f"{configuration['receipt_prefix']}-{target}.json",
                f"{profile} {target} receipt",
            )
            receipt = validated_receipt(
                receipt_path,
                profile=profile,
                target=target,
                artifact=artifact,
                commit=commit,
                tree=tree,
                godot_cpp_commit=godot_cpp_commit,
                expected_capabilities=expected_capabilities,
            )
            artifact_name = f"{archive_root}/mterrain/{artifact.name}"
            receipt_name = f"{archive_root}/receipts/{receipt_path.name}"
            files[artifact_name] = artifact.read_bytes()
            files[receipt_name] = receipt_path.read_bytes()
            profile_index["artifacts"][target] = {
                "path": f"mterrain/{artifact.name}",
                "sha256": receipt["artifact"]["sha256"],
                "size": receipt["artifact"]["size"],
                "brotli": receipt["artifact"]["brotli"],
                "receipt": f"receipts/{receipt_path.name}",
            }

        companion = configuration["runtime_companion"]
        if companion is not None:
            companion = require_file(companion, "extended runtime companion")
            companion_path = "runtime/web_extended_runtime.gd"
            files[f"{archive_root}/{companion_path}"] = companion.read_bytes()
            profile_index["runtime_companion"] = {
                "path": companion_path,
                "api_version": contract_profiles[profile]["companion"][
                    "api_version"
                ],
                "sha256": sha256_file(companion),
                "size": companion.stat().st_size,
            }

        bundle_name = f"Godot-MTerrain-{version}-{profile}.tar.gz"
        bundle_path = output / bundle_name
        bundle_path.write_bytes(archive_bytes(files, epoch))
        profile_index["bundle"] = {
            "name": bundle_name,
            "sha256": sha256_file(bundle_path),
            "size": bundle_path.stat().st_size,
        }
        index["profiles"][profile] = profile_index

    index_name = f"Godot-MTerrain-{version}-release-index.json"
    index_path = output / index_name
    index_path.write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    checksummed = [
        output / profile["bundle"]["name"]
        for profile in index["profiles"].values()
    ] + [index_path, runtime_contract_output]
    (output / "SHA256SUMS").write_text(
        "".join(
            f"{sha256_file(path)}  {path.name}\n"
            for path in sorted(checksummed, key=lambda value: value.name)
        ),
        encoding="utf-8",
    )
    verify(output)
    print(output)


def safe_archive_members(
    archive_path: Path, expected_epoch: int
) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive.getmembers():
            pure_name = PurePosixPath(member.name)
            if pure_name.is_absolute() or ".." in pure_name.parts:
                raise SystemExit(f"Unsafe archive path in {archive_path}: {member.name}")
            if not member.isfile():
                raise SystemExit(
                    f"Only regular files may ship in {archive_path}: {member.name}"
                )
            if member.name in members:
                raise SystemExit(f"Duplicate archive path: {member.name}")
            if (
                member.uid != 0
                or member.gid != 0
                or member.mode != 0o644
                or member.mtime != expected_epoch
            ):
                raise SystemExit(f"Non-normalized archive metadata: {member.name}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise SystemExit(f"Could not read archive member: {member.name}")
            members[member.name] = extracted.read()
    return members


def verify(output: Path) -> None:
    output = output.expanduser().resolve()
    indices = sorted(output.glob("Godot-MTerrain-*-release-index.json"))
    if len(indices) != 1:
        raise SystemExit(f"Expected exactly one release index in {output}")
    index_path = indices[0]
    index = read_json(index_path)
    if index.get("schema") != "mterrain-web-release-index-v1":
        raise SystemExit("Unexpected release-index schema")
    epoch = index.get("source_date_epoch")
    if not isinstance(epoch, int) or epoch <= 0:
        raise SystemExit("Release index has an invalid source_date_epoch")
    if index.get("source", {}).get("mterrain_dirty") is not False:
        raise SystemExit("Release index must record a clean source tree")
    if index.get("target", {}).get("threads") is not False:
        raise SystemExit("Release index must record the no-thread target")

    expected_checksums: dict[str, str] = {}
    for line in require_file(output / "SHA256SUMS", "SHA256SUMS").read_text(
        encoding="utf-8"
    ).splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if match is None:
            raise SystemExit(f"Malformed SHA256SUMS entry: {line!r}")
        expected_checksums[match.group(2)] = match.group(1)
    if expected_checksums.get(index_path.name) != sha256_file(index_path):
        raise SystemExit("Release-index checksum mismatch")

    runtime_contract_index = index.get("runtime_contract")
    runtime_contract_data: bytes | None = None
    runtime_contract: dict[str, Any] | None = None
    if runtime_contract_index is not None:
        if not isinstance(runtime_contract_index, dict):
            raise SystemExit("Release-index runtime contract must be an object")
        runtime_contract_path = require_file(
            output / str(runtime_contract_index.get("name", "")),
            "runtime contract",
        )
        runtime_contract_data = runtime_contract_path.read_bytes()
        if runtime_contract_index.get("sha256") != sha256_bytes(runtime_contract_data):
            raise SystemExit("Runtime-contract digest mismatch")
        if runtime_contract_index.get("size") != len(runtime_contract_data):
            raise SystemExit("Runtime-contract size mismatch")
        if expected_checksums.get(runtime_contract_path.name) != sha256_bytes(
            runtime_contract_data
        ):
            raise SystemExit("Runtime-contract SHA256SUMS mismatch")
        runtime_contract = json.loads(runtime_contract_data.decode("utf-8"))
        if runtime_contract.get("schema") != "mterrain-web-runtime-contract-v1":
            raise SystemExit("Unexpected runtime-contract schema")
        if runtime_contract.get("contract_version") != 1:
            raise SystemExit("Unexpected runtime-contract version")
        if runtime_contract_index.get("schema") != runtime_contract["schema"]:
            raise SystemExit("Release-index runtime-contract schema mismatch")
        if runtime_contract_index.get("contract_version") != runtime_contract[
            "contract_version"
        ]:
            raise SystemExit("Release-index runtime-contract version mismatch")
    elif index.get("version") != "web-runtime-v0.1.0-rc.1":
        raise SystemExit("Only the immutable rc.1 baseline may omit a runtime contract")

    profiles = index.get("profiles", {})
    if set(profiles) != set(PROFILES):
        raise SystemExit("Release index must contain exactly core and extended profiles")
    machine_contracts = (
        (
            "performance_budgets",
            PERFORMANCE_BUDGETS_RELATIVE,
            "mterrain-web-performance-budgets-v1",
        ),
        (
            "performance_calibration",
            PERFORMANCE_CALIBRATION_RELATIVE,
            "mterrain-web-performance-calibration-v1",
        ),
        ("release_gate", RELEASE_GATE_RELATIVE, "mterrain-web-release-gate-v1"),
    )
    legacy_without_stable_gate = index.get("version") in {
        "web-runtime-v0.1.0-rc.1",
        "web-runtime-v0.1.0-rc.2",
    }
    for field, relative, schema in machine_contracts:
        record = index.get(field)
        if record is None and legacy_without_stable_gate:
            continue
        if not isinstance(record, dict):
            raise SystemExit(f"Release index omitted {field}")
        if record.get("path") != relative or record.get("schema") != schema:
            raise SystemExit(f"Release index has an invalid {field} contract")
    for profile, profile_index in profiles.items():
        bundle = profile_index.get("bundle", {})
        bundle_path = require_file(output / str(bundle.get("name", "")), profile)
        bundle_sha = sha256_file(bundle_path)
        if bundle.get("sha256") != bundle_sha:
            raise SystemExit(f"Bundle digest mismatch for {profile}")
        if bundle.get("size") != bundle_path.stat().st_size:
            raise SystemExit(f"Bundle size mismatch for {profile}")
        if expected_checksums.get(bundle_path.name) != bundle_sha:
            raise SystemExit(f"SHA256SUMS mismatch for {profile}")
        archive_root = profile_index.get("archive_root")
        if not isinstance(archive_root, str) or not archive_root:
            raise SystemExit(f"Missing archive root for {profile}")
        members = safe_archive_members(bundle_path, epoch)
        required_paths = {
            f"{archive_root}/mterrain/MTerrain.gdextension",
            f"{archive_root}/LICENSE",
            f"{archive_root}/docs/WEB_RUNTIME_API.md",
            f"{archive_root}/docs/WEB_SUPPORT_MATRIX.md",
        }
        if not legacy_without_stable_gate:
            required_paths.update(
                f"{archive_root}/{relative}"
                for _, relative, _ in machine_contracts
            )
            required_paths.update(
                f"{archive_root}/{relative}" for relative in PERFORMANCE_FIXTURE_FILES
            )
        if runtime_contract_data is not None:
            bundle_contract_path = runtime_contract_index.get("bundle_path")
            if bundle_contract_path != RUNTIME_CONTRACT_RELATIVE:
                raise SystemExit("Unexpected runtime-contract bundle path")
            required_paths.add(f"{archive_root}/{bundle_contract_path}")
        if not required_paths.issubset(members):
            raise SystemExit(f"Bundle {profile} is missing common runtime files")
        if not legacy_without_stable_gate:
            for field, relative, schema in machine_contracts:
                record = index[field]
                data = members[f"{archive_root}/{relative}"]
                if record.get("sha256") != sha256_bytes(data):
                    raise SystemExit(f"Bundle {profile} {field} digest mismatch")
                if record.get("size") != len(data):
                    raise SystemExit(f"Bundle {profile} {field} size mismatch")
                if json.loads(data.decode("utf-8")).get("schema") != schema:
                    raise SystemExit(f"Bundle {profile} {field} schema mismatch")
            bundled_budgets = json.loads(
                members[f"{archive_root}/{PERFORMANCE_BUDGETS_RELATIVE}"].decode(
                    "utf-8"
                )
            )
            bundled_calibration = json.loads(
                members[
                    f"{archive_root}/{PERFORMANCE_CALIBRATION_RELATIVE}"
                ].decode("utf-8")
            )
            if bundled_calibration.get("threshold_contract_sha256") != (
                threshold_contract_sha256(bundled_budgets)
            ):
                raise SystemExit(
                    f"Bundle {profile} calibration targets different thresholds"
                )
            if bundled_calibration.get("release_gate_eligible") is not False:
                raise SystemExit(
                    f"Bundle {profile} must carry the provisional calibration template"
                )
        if runtime_contract_data is not None:
            bundled_contract = members[
                f"{archive_root}/{runtime_contract_index['bundle_path']}"
            ]
            if bundled_contract != runtime_contract_data:
                raise SystemExit(f"Bundle {profile} runtime contract differs")
            expected_capability_contract = runtime_contract["profiles"][profile][
                "capability_contract"
            ]
            if profile_index.get("capability_contract") != expected_capability_contract:
                raise SystemExit(f"Capability contract mismatch for {profile}")
        for target, artifact_index in profile_index.get("artifacts", {}).items():
            if target not in TARGETS:
                raise SystemExit(f"Unexpected target {target} in {profile}")
            artifact_path = f"{archive_root}/{artifact_index['path']}"
            receipt_path = f"{archive_root}/{artifact_index['receipt']}"
            if artifact_path not in members or receipt_path not in members:
                raise SystemExit(f"Bundle {profile} omitted {target}")
            artifact_data = members[artifact_path]
            receipt = json.loads(members[receipt_path].decode("utf-8"))
            artifact_sha = sha256_bytes(artifact_data)
            if receipt.get("schema") != "mterrain-web-build-receipt-v2":
                raise SystemExit(f"Unexpected receipt schema for {profile}/{target}")
            if artifact_index.get("sha256") != artifact_sha:
                raise SystemExit(f"Index artifact digest mismatch for {profile}/{target}")
            if artifact_index.get("size") != len(artifact_data):
                raise SystemExit(f"Index artifact size mismatch for {profile}/{target}")
            if receipt.get("artifact", {}).get("sha256") != artifact_sha:
                raise SystemExit(f"Receipt digest mismatch for {profile}/{target}")
            if receipt.get("artifact", {}).get("size") != len(artifact_data):
                raise SystemExit(f"Receipt size mismatch for {profile}/{target}")
            if receipt.get("artifact", {}).get("name") != PurePosixPath(
                artifact_path
            ).name:
                raise SystemExit(f"Receipt artifact name mismatch for {profile}/{target}")
            if receipt.get("target", {}).get("profile") != profile:
                raise SystemExit(f"Receipt profile mismatch for {profile}/{target}")
            if receipt.get("target", {}).get("target") != target:
                raise SystemExit(f"Receipt target mismatch for {profile}/{target}")
            receipt_source = receipt.get("source", {})
            index_source = index.get("source", {})
            if (
                receipt_source.get("mterrain_commit")
                != index_source.get("mterrain_commit")
                or receipt_source.get("mterrain_tree")
                != index_source.get("mterrain_tree")
                or receipt_source.get("godot_cpp_commit")
                != index_source.get("godot_cpp_commit")
                or receipt_source.get("mterrain_dirty") is not False
            ):
                raise SystemExit(f"Receipt source mismatch for {profile}/{target}")
            if artifact_index.get("brotli") != receipt.get("artifact", {}).get(
                "brotli"
            ):
                raise SystemExit(f"Receipt Brotli record mismatch for {profile}/{target}")
        if set(profile_index.get("artifacts", {})) != set(TARGETS):
            raise SystemExit(f"Bundle {profile} must contain debug and release artifacts")
        if profile == "web_extended":
            companion = profile_index.get("runtime_companion", {})
            companion_path = f"{archive_root}/{companion.get('path', '')}"
            if companion_path not in members:
                raise SystemExit("Extended bundle omitted its runtime companion")
            if companion.get("sha256") != sha256_bytes(members[companion_path]):
                raise SystemExit("Extended companion digest mismatch")
            if runtime_contract is not None and companion.get("api_version") != (
                runtime_contract["profiles"][profile]["companion"]["api_version"]
            ):
                raise SystemExit("Extended companion API version mismatch")
        elif "runtime_companion" in profile_index:
            raise SystemExit("Core bundle must not advertise the extended companion")
    expected_names = {index_path.name} | {
        value["bundle"]["name"] for value in profiles.values()
    }
    if runtime_contract_index is not None:
        expected_names.add(runtime_contract_index["name"])
    if set(expected_checksums) != expected_names:
        raise SystemExit("SHA256SUMS contains an unexpected or missing asset")
    print(f"MTERRAIN_WEB_RELEASE_VERIFY_OK {index.get('version')}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.verify_dir is not None:
        if args.version is not None:
            raise SystemExit("--version and --verify-dir are mutually exclusive")
        verify(args.verify_dir)
        return 0
    if args.version is None:
        raise SystemExit("--version is required when creating packages")
    package(args.version, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
