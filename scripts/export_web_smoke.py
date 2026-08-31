#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from web_evidence_common import load_object, sha256, threshold_contract_sha256


ROOT = Path(__file__).resolve().parents[1]
PERFORMANCE_FIXTURE_FILES = (
    "tests/web_performance/main.gd",
    "tests/web_performance/evidence_bridge.js",
    "tests/web_smoke/main.tscn",
    "tests/web_smoke/main.gd.uid",
    "tests/web_smoke/project.godot",
    "tests/web_smoke/fixtures/grass_cluster.obj",
    "tests/web_smoke/fixtures/grass_cluster.obj.import",
    "tests/web_smoke/fixtures/grass_material.tres",
    "tests/web_smoke/fixtures/road_strip.obj",
    "tests/web_smoke/fixtures/road_strip.obj.import",
    "tests/web_smoke/fixtures/road_material.tres",
    "tests/web_smoke/fixtures/road_collision.tres",
    "tests/web_smoke/fixtures/rock_near.obj",
    "tests/web_smoke/fixtures/rock_near.obj.import",
    "tests/web_smoke/fixtures/rock_far.obj",
    "tests/web_smoke/fixtures/rock_far.obj.import",
    "tests/web_smoke/fixtures/walkable_nav.tres",
)


def git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *arguments], text=True
    ).strip()


def fixture_source_context() -> dict[str, object]:
    return {
        "source": {
            "commit": git("rev-parse", "HEAD"),
            "tree": git("rev-parse", "HEAD^{tree}"),
            "dirty": bool(
                git(
                    "status",
                    "--porcelain",
                    "--untracked-files=normal",
                    "--ignore-submodules=dirty",
                )
            ),
        },
        "files": {
            relative: sha256(ROOT / relative)
            for relative in PERFORMANCE_FIXTURE_FILES
        },
    }


def runtime_export_payload(output: Path) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for path in sorted(output.iterdir(), key=lambda value: value.name):
        if not path.is_file() or path.name.startswith("mterrain_"):
            continue
        data = path.read_bytes()
        files.append(
            {
                "name": path.name,
                "sha256": sha256(path),
                "raw_bytes": len(data),
                "gzip_bytes": len(gzip.compress(data, compresslevel=9, mtime=0)),
            }
        )
    return {
        "schema": "mterrain-web-runtime-export-payload-v1",
        "compression": "gzip-9-mtime-0-per-file",
        "instrumentation_excluded": True,
        "file_count": len(files),
        "raw_bytes": sum(int(record["raw_bytes"]) for record in files),
        "gzip_bytes": sum(int(record["gzip_bytes"]) for record in files),
        "files": files,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--godot", required=True, type=Path)
    parser.add_argument("--template-debug", required=True, type=Path)
    parser.add_argument("--native-library", required=True, type=Path)
    parser.add_argument(
        "--profile",
        choices=("web_core", "web_extended"),
        default="web_core",
    )
    parser.add_argument(
        "--fixture",
        choices=("smoke", "performance", "rollback"),
        default="smoke",
    )
    parser.add_argument("--bundle-root", type=Path)
    parser.add_argument("--rollback-context", type=Path)
    parser.add_argument("--build-receipt", type=Path)
    parser.add_argument("--template-receipt", type=Path)
    parser.add_argument(
        "--web-library",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--output", type=Path, default=None
    )
    return parser.parse_args()


def require_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"{label} is missing or empty: {path}")
    return path


def export_preset(profile: str) -> str:
    return f"""[preset.0]

name="Web Smoke"
platform="Web"
runnable=false
dedicated_server=false
custom_features="mterrain_{profile}"
export_filter="all_resources"
include_filter=""
exclude_filter="web_templates/**"
export_path="build/index.html"
encryption_include_filters=""
encryption_exclude_filters=""
encrypt_pck=false
encrypt_directory=false

[preset.0.options]

custom_template/debug="res://web_templates/godot-web-debug.zip"
custom_template/release=""
variant/extensions_support=true
variant/thread_support=false
vram_texture_compression/for_desktop=true
vram_texture_compression/for_mobile=false
html/export_icon=false
html/custom_html_shell=""
html/head_include=""
html/canvas_resize_policy=2
html/focus_canvas_on_start=true
html/experimental_virtual_keyboard=false
progressive_web_app/enabled=false
progressive_web_app/offline_page=""
progressive_web_app/display=1
progressive_web_app/orientation=0
progressive_web_app/icon_144x144=""
progressive_web_app/icon_180x180=""
progressive_web_app/icon_512x512=""
"""


def main() -> int:
    args = parse_args()
    bundle_root: Path | None = None
    if args.bundle_root is not None:
        bundle_root = args.bundle_root.expanduser().resolve()
        if not bundle_root.is_dir():
            raise SystemExit(f"Extracted runtime bundle is missing: {bundle_root}")
    if args.fixture == "rollback" and args.rollback_context is None:
        raise SystemExit("Rollback exports require --rollback-context")
    if args.web_library is None:
        if bundle_root is not None:
            args.web_library = (
                bundle_root
                / "mterrain"
                / "libMTerrain.web.template_debug.wasm32.nothreads.wasm"
            )
        else:
            profile_dir = Path() if args.profile == "web_core" else Path("web_extended")
            args.web_library = (
                ROOT
                / "build"
                / "mterrain"
                / profile_dir
                / "libMTerrain.web.template_debug.wasm32.nothreads.wasm"
            )
    if args.output is None:
        suffix = {
            "smoke": "web-smoke",
            "performance": "web-performance",
            "rollback": "web-rollback",
        }[args.fixture]
        if args.profile == "web_extended":
            suffix += "-extended"
        args.output = ROOT / "build" / suffix
    godot = require_file(args.godot, "Godot editor")
    template = require_file(args.template_debug, "Web debug template")
    native_library = require_file(args.native_library, "native editor library")
    web_library = require_file(args.web_library, "Web side module")
    performance_context: dict[str, object] | None = None
    if args.fixture == "performance":
        if args.build_receipt is None or args.template_receipt is None:
            raise SystemExit(
                "Performance exports require --build-receipt and --template-receipt"
            )
        build_receipt_path = require_file(args.build_receipt, "Web build receipt")
        template_receipt_path = require_file(
            args.template_receipt, "Web template receipt"
        )
        build_receipt = load_object(build_receipt_path, "Web build receipt")
        template_receipt = load_object(template_receipt_path, "Web template receipt")
        if build_receipt.get("schema") != "mterrain-web-build-receipt-v2":
            raise SystemExit("Unexpected Web build-receipt schema")
        if template_receipt.get("schema") != "mterrain-web-template-receipt-v1":
            raise SystemExit("Unexpected Web template-receipt schema")
        if build_receipt.get("target", {}).get("profile") != args.profile:
            raise SystemExit("Performance build receipt has the wrong runtime profile")
        if build_receipt.get("target", {}).get("target") != "template_debug":
            raise SystemExit("Performance export requires the debug Web build receipt")
        if build_receipt.get("artifact", {}).get("sha256") != sha256(web_library):
            raise SystemExit("Performance Web side module differs from its build receipt")
        if template_receipt.get("artifact", {}).get("sha256") != sha256(template):
            raise SystemExit("Performance export template differs from its receipt")
        budgets_path = ROOT / "tools" / "web_performance_budgets.json"
        budgets = load_object(budgets_path, "Web performance budgets")
        performance_context = {
            "schema": "mterrain-web-performance-context-v1",
            "profile": args.profile,
            "source": build_receipt.get("source"),
            "build_receipt": {
                "name": build_receipt_path.name,
                "sha256": sha256(build_receipt_path),
                "artifact_name": build_receipt["artifact"]["name"],
                "artifact_sha256": build_receipt["artifact"]["sha256"],
            },
            "template_receipt": {
                "name": template_receipt_path.name,
                "sha256": sha256(template_receipt_path),
                "artifact_name": template_receipt["artifact"]["name"],
                "artifact_sha256": template_receipt["artifact"]["sha256"],
            },
            "performance_budget": {
                "sha256": sha256(budgets_path),
                "threshold_contract_sha256": threshold_contract_sha256(budgets),
            },
            "fixture_source": fixture_source_context(),
        }
    output = args.output.expanduser().resolve()
    build_root = (ROOT / "build").resolve()
    if output == build_root or build_root not in output.parents:
        raise SystemExit(
            f"Web smoke output must be a child of the repository build directory: {build_root}"
        )
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    with tempfile.TemporaryDirectory(prefix="mterrain-web-smoke-") as temp:
        stage = Path(temp)
        shutil.copytree(ROOT / "tests" / "web_smoke", stage, dirs_exist_ok=True)
        if args.fixture == "performance":
            shutil.copy2(ROOT / "tests" / "web_performance" / "main.gd", stage / "main.gd")
        elif args.fixture == "rollback":
            shutil.copy2(ROOT / "tests" / "web_rollback" / "main.gd", stage / "main.gd")
        if args.profile == "web_core" or args.fixture == "rollback":
            shutil.rmtree(stage / "fixtures", ignore_errors=True)
        # Never let a local import/cache directory influence the staged export.
        shutil.rmtree(stage / ".godot", ignore_errors=True)
        (stage / ".godot").mkdir()
        (stage / ".godot" / "extension_list.cfg").write_text(
            "res://mterrain/MTerrain.gdextension\n", encoding="utf-8"
        )
        extension_dir = stage / "mterrain"
        extension_dir.mkdir()
        manifest_source = (
            bundle_root / "mterrain" / "MTerrain.gdextension"
            if bundle_root is not None
            else ROOT / "gdextension" / "MTerrain.txt"
        )
        shutil.copy2(
            require_file(manifest_source, "GDExtension manifest"),
            extension_dir / "MTerrain.gdextension",
        )
        shutil.copy2(
            web_library,
            extension_dir
            / "libMTerrain.web.template_debug.wasm32.nothreads.wasm",
        )
        addon_dir = stage / "addons" / "m_terrain"
        addon_dir.mkdir(parents=True)
        asset_root = bundle_root if bundle_root is not None else ROOT
        for asset in (
            "start_material_opengl.res",
            "start_opengl.gdshader",
            "start_opengl.gdshader.uid",
        ):
            asset_source = (
                asset_root / "addons" / "m_terrain" / asset
                if bundle_root is not None
                else asset_root / asset
            )
            shutil.copy2(require_file(asset_source, asset), addon_dir / asset)
        if args.profile == "web_extended":
            runtime_dir = stage / "runtime"
            runtime_dir.mkdir()
            companion_source = (
                bundle_root / "runtime" / "web_extended_runtime.gd"
                if bundle_root is not None
                else ROOT / "runtime" / "web_extended_runtime.gd"
            )
            shutil.copy2(
                require_file(companion_source, "extended runtime companion"),
                runtime_dir / "web_extended_runtime.gd",
            )
        if platform.system() == "Darwin":
            native_name = "libMTerrain.macos.template_debug.universal.dylib"
        elif platform.system() == "Linux":
            native_name = "libMTerrain.linux.template_debug.x86_64.so"
        else:
            raise SystemExit("Web smoke export supports macOS and Linux editor hosts")
        shutil.copy2(native_library, extension_dir / native_name)
        template_dir = stage / "web_templates"
        template_dir.mkdir()
        shutil.copy2(template, template_dir / "godot-web-debug.zip")
        (stage / "export_presets.cfg").write_text(
            export_preset(args.profile), encoding="utf-8"
        )

        command = [
            str(godot),
            "--headless",
            "--path",
            str(stage),
            "--export-debug",
            "Web Smoke",
            str(output / "index.html"),
        ]
        completed = subprocess.run(command, text=True, capture_output=True)
        combined = completed.stdout + completed.stderr
        print(combined, end="")
        if completed.returncode != 0:
            raise SystemExit(completed.returncode)

    expected = [
        output / "index.html",
        output / "index.js",
        output / "index.wasm",
        output / "index.side.wasm",
        output / "index.pck",
        output / web_library.name,
    ]
    missing = [str(path) for path in expected if not path.is_file()]
    if missing:
        raise SystemExit("Web export omitted required artifacts: " + ", ".join(missing))
    if args.fixture == "performance":
        if performance_context is None:
            raise SystemExit("Performance export context was not initialized")
        performance_context["runtime_export_payload"] = runtime_export_payload(output)
        bridge_source = ROOT / "tests" / "web_performance" / "evidence_bridge.js"
        bridge_output = output / "mterrain_evidence_bridge.js"
        shutil.copy2(bridge_source, bridge_output)
        (output / "mterrain_performance_context.json").write_text(
            json.dumps(performance_context, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        index_path = output / "index.html"
        index_source = index_path.read_text(encoding="utf-8")
        bridge_tag = '<script src="mterrain_evidence_bridge.js"></script>'
        if "</head>" not in index_source:
            raise SystemExit("Godot Web export omitted a closing head element")
        index_path.write_text(
            index_source.replace("</head>", bridge_tag + "\n</head>", 1),
            encoding="utf-8",
        )
    elif args.fixture == "rollback":
        context_path = require_file(args.rollback_context, "rollback context")
        context = json.loads(context_path.read_text(encoding="utf-8"))
        if context.get("schema") != "mterrain-web-rollback-context-v1":
            raise SystemExit("Unexpected rollback-context schema")
        bridge_source = ROOT / "tests" / "web_rollback" / "evidence_bridge.js"
        shutil.copy2(bridge_source, output / "mterrain_rollback_evidence_bridge.js")
        shutil.copy2(context_path, output / "mterrain_rollback_context.json")
        index_path = output / "index.html"
        index_source = index_path.read_text(encoding="utf-8")
        bridge_tag = '<script src="mterrain_rollback_evidence_bridge.js"></script>'
        if "</head>" not in index_source:
            raise SystemExit("Godot Web export omitted a closing head element")
        index_path.write_text(
            index_source.replace("</head>", bridge_tag + "\n</head>", 1),
            encoding="utf-8",
        )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
