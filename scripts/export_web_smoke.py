#!/usr/bin/env python3
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--godot", required=True, type=Path)
    parser.add_argument("--template-debug", required=True, type=Path)
    parser.add_argument("--native-library", required=True, type=Path)
    parser.add_argument(
        "--web-library",
        type=Path,
        default=ROOT
        / "build"
        / "mterrain"
        / "libMTerrain.web.template_debug.wasm32.nothreads.wasm",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "build" / "web-smoke"
    )
    return parser.parse_args()


def require_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"{label} is missing or empty: {path}")
    return path


def export_preset() -> str:
    return """[preset.0]

name="Web Smoke"
platform="Web"
runnable=false
dedicated_server=false
custom_features="mterrain_web_core"
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
    godot = require_file(args.godot, "Godot editor")
    template = require_file(args.template_debug, "Web debug template")
    native_library = require_file(args.native_library, "native editor library")
    web_library = require_file(args.web_library, "Web side module")
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
        # Never let a local import/cache directory influence the staged export.
        shutil.rmtree(stage / ".godot", ignore_errors=True)
        (stage / ".godot").mkdir()
        (stage / ".godot" / "extension_list.cfg").write_text(
            "res://mterrain/MTerrain.gdextension\n", encoding="utf-8"
        )
        extension_dir = stage / "mterrain"
        extension_dir.mkdir()
        shutil.copy2(
            ROOT / "gdextension" / "MTerrain.txt",
            extension_dir / "MTerrain.gdextension",
        )
        shutil.copy2(
            web_library,
            extension_dir
            / "libMTerrain.web.template_debug.wasm32.nothreads.wasm",
        )
        addon_dir = stage / "addons" / "m_terrain"
        addon_dir.mkdir(parents=True)
        for asset in (
            "start_material_opengl.res",
            "start_opengl.gdshader",
            "start_opengl.gdshader.uid",
        ):
            shutil.copy2(ROOT / asset, addon_dir / asset)
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
        (stage / "export_presets.cfg").write_text(export_preset(), encoding="utf-8")

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
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
