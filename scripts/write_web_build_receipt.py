#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", "-C", str(cwd), *args], text=True
    ).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile", required=True, choices=("web_core", "web_extended")
    )
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--api", required=True, type=Path)
    parser.add_argument("--binding-profile", required=True, type=Path)
    parser.add_argument("--godot-version", required=True)
    parser.add_argument("--emcc-version", required=True)
    parser.add_argument("--scons-version", required=True)
    parser.add_argument("--wasm-opt-bin", required=True, type=Path)
    parser.add_argument("--wasm-opt-version", required=True)
    parser.add_argument("--brotli-bin", required=True, type=Path)
    parser.add_argument("--brotli-version", required=True)
    parser.add_argument("--brotli-quality", required=True, type=int)
    parser.add_argument("--target", required=True)
    parser.add_argument("--toolchain", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    toolchain = json.loads(args.toolchain.read_text(encoding="utf-8"))
    if toolchain.get("profile") != args.profile:
        raise SystemExit(
            "Toolchain profile mismatch: "
            f"expected {args.profile!r}, got {toolchain.get('profile')!r}"
        )
    expected_binding = str(args.binding_profile.resolve().relative_to(ROOT))
    if toolchain.get("binding_profile") != expected_binding:
        raise SystemExit(
            "Binding profile mismatch: "
            f"expected {expected_binding!r}, got {toolchain.get('binding_profile')!r}"
        )
    dirty = bool(
        git(
            "status",
            "--porcelain",
            "--untracked-files=normal",
            "--ignore-submodules=dirty",
        )
    )
    brotli = subprocess.check_output(
        [
            str(args.brotli_bin),
            f"--quality={args.brotli_quality}",
            "--stdout",
            "--",
            str(args.artifact),
        ]
    )
    wasm_features_output = subprocess.check_output(
        [str(args.wasm_opt_bin), str(args.artifact), "--print-features"],
        text=True,
        stderr=subprocess.STDOUT,
    )
    wasm_features = sorted(
        line.strip()
        for line in wasm_features_output.splitlines()
        if line.strip().startswith("--enable-")
    )
    extended = args.profile == "web_extended"
    receipt = {
        "schema": "mterrain-web-build-receipt-v2",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": {
            "mterrain_commit": git("rev-parse", "HEAD"),
            "mterrain_tree": git("rev-parse", "HEAD^{tree}"),
            "mterrain_dirty": dirty,
            "godot_cpp_commit": git(
                "rev-parse", "HEAD", cwd=ROOT / "gdextension" / "godot-cpp"
            ),
        },
        "target": {
            "platform": "web",
            "architecture": "wasm32",
            "target": args.target,
            "precision": "single",
            "threads": False,
            "dynamic_linking": True,
            "profile": args.profile,
            "capabilities": {
                "runtime_api_version": 2,
                "api_stability": "experimental",
                "height_formats": ["r32f_metres"],
                "max_height_tile_width": 67,
                "max_height_tile_height": 67,
                "max_height_tile_samples": 4489,
                "heightfield_terrain": True,
                "visual_lod": True,
                "heightfield_collision": True,
                "compatibility_materials": True,
                "height_tile_apply": True,
                "height_tile_release": True,
                "bounded_update_scheduler": True,
                "bounded_collision": True,
                "runtime_material_configuration": True,
                "foliage": extended,
                "navigation": extended,
                "paths": extended,
                "mesh_hlod": extended,
                "foliage_collision": False,
                "runtime_navigation_baking": False,
                "runtime_curve_deformation": False,
                "path_collision": False,
                "runtime_mesh_generation": False,
                "hlod_hysteresis": extended,
            },
        },
        "toolchain": {
            "pins": toolchain,
            "godot": args.godot_version,
            "emscripten": args.emcc_version,
            "scons": args.scons_version,
            "binaryen": args.wasm_opt_version,
            "brotli": args.brotli_version,
            "extension_api_sha256": sha256(args.api),
            "binding_profile_sha256": sha256(args.binding_profile),
        },
        "artifact": {
            "name": args.artifact.name,
            "sha256": sha256(args.artifact),
            "size": args.artifact.stat().st_size,
            "brotli": {
                "quality": args.brotli_quality,
                "sha256": hashlib.sha256(brotli).hexdigest(),
                "size": len(brotli),
            },
            "wasm_features": wasm_features,
        },
    }
    if extended:
        companion_path = ROOT / toolchain["runtime_companion"]
        receipt["runtime_companion"] = {
            "path": toolchain["runtime_companion"],
            "api_version": 1,
            "sha256": sha256(companion_path),
            "size": companion_path.stat().st_size,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
