"""Shared source selection and exact library manifests for native/Web builders."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


PROFILES = ("full", "runtime", "web_core", "web_extended")
NATIVE_GROUPS = ("hlod", "grass", "navmesh", "octmesh", "path")


def select_sources(root: Path, profile: str, target: str) -> dict:
    if profile not in PROFILES:
        raise ValueError("Unknown MTerrain profile: " + profile)
    if target not in ("template_debug", "template_release", "editor"):
        raise ValueError("Unknown Godot target: " + target)
    patterns = ["src/*.cpp", "src/util/*.cpp", "src/height_brushes/*.cpp", "src/color_brushes/*.cpp"]
    bounded = profile in ("web_core", "web_extended")
    definitions = []
    if bounded:
        definitions.extend(("MTERRAIN_CORE_ONLY", "MTERRAIN_MEMORY_ONLY_DEFAULT",
                            "MTERRAIN_BOUNDED_RUNTIME", "MTERRAIN_SINGLE_THREADED"))
    else:
        patterns.extend("src/" + group + "/*.cpp" for group in NATIVE_GROUPS)
        if profile == "full" and target != "template_release":
            patterns.append("src/editor/*.cpp")
    definitions.append("MTERRAIN_PROFILE_" + profile.upper())
    sources = {str(path.relative_to(root)) for pattern in patterns for path in root.glob(pattern)}
    if bounded:
        sources.difference_update(("src/moctree.cpp", "src/mtool.cpp"))
    sources.add("register_types.cpp")
    return {"profile": profile, "sources": sorted(sources), "definitions": definitions}


def write_manifest(source: Path, output: Path, platform: str, target: str,
                   arch: str, library: str, *, threads: bool = True) -> None:
    if target not in ("template_debug", "template_release", "editor"):
        raise ValueError("Unknown Godot target: " + target)
    for value in (platform, arch, library):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise ValueError("Invalid manifest tuple component")
    build = "release" if target == "template_release" else "debug"
    key = platform + "." + build + "." + arch
    if platform == "web" and not threads:
        key += ".nothreads"
    text = source.read_text(encoding="utf-8")
    section = text.split("[libraries]", 1)
    if len(section) != 2:
        raise ValueError("Manifest requires a library section")
    entries = {key: library}
    # A debug and release build may share one output directory. Preserve exact
    # entries for libraries still present there; rebuilding one target must not
    # make the other target fall back to a differently named universal library.
    if output.is_file():
        previous = output.read_text(encoding="utf-8").split("[libraries]", 1)
        if len(previous) == 2:
            libraries = previous[1].split("[", 1)[0]
            for old_key, old_library in re.findall(
                    r'(?m)^([A-Za-z0-9_.-]+)\s*=\s*"res://mterrain/([A-Za-z0-9_.-]+)"\s*$', libraries):
                if old_key != key and (output.parent / old_library).is_file():
                    entries[old_key] = old_library
    tail = section[1]
    for exact_key in entries:
        tail = re.sub(r"(?m)^" + re.escape(exact_key) + r"\s*=.*\n?", "", tail)
    generated = "\n".join(name + ' = "res://mterrain/' + entries[name] + '"' for name in sorted(entries))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(section[0] + "[libraries]\n" + generated + "\n" + tail.lstrip("\n"), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--profile", choices=PROFILES, default="full")
    parser.add_argument("--target", required=True)
    parser.add_argument("--manifest-source", type=Path)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--platform")
    parser.add_argument("--arch")
    parser.add_argument("--library")
    args = parser.parse_args()
    if args.manifest_source:
        if not all((args.manifest_output, args.platform, args.arch, args.library)):
            parser.error("Manifest emission requires output, platform, arch and library")
        write_manifest(args.manifest_source, args.manifest_output, args.platform,
                       args.target, args.arch, args.library)
    else:
        print(json.dumps(select_sources(args.root, args.profile, args.target), sort_keys=True))


if __name__ == "__main__":
    main()
