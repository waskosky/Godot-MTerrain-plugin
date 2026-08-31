#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS_ROOT="${1:-}"
OUTPUT_DIR="${2:-$ROOT_DIR/build/web-template}"

if [[ -z "$TOOLS_ROOT" ]]; then
	printf 'Usage: %s /absolute/tool/root [/repository/build/output]\n' "$0" >&2
	exit 2
fi
TOOLS_ROOT="$(python3 - "$TOOLS_ROOT" <<'PY'
import sys
from pathlib import Path
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
OUTPUT_DIR="$(python3 - "$OUTPUT_DIR" "$ROOT_DIR/build" <<'PY'
import sys
from pathlib import Path
output = Path(sys.argv[1]).expanduser().resolve()
build = Path(sys.argv[2]).resolve()
if output == build or build not in output.parents:
    raise SystemExit(f"Template output must be below {build}: {output}")
print(output)
PY
)"
if [[ "$TOOLS_ROOT" == "/" ]]; then
	printf 'Refusing to use the filesystem root as a tool directory.\n' >&2
	exit 2
fi
if [[ ! -f "$TOOLS_ROOT/environment.sh" ]]; then
	printf 'Install the pinned Web toolchain before building the template.\n' >&2
	exit 1
fi
# shellcheck disable=SC1090
source "$TOOLS_ROOT/environment.sh"
if [[ -z "${SCONS_BIN:-}" || ! -x "$SCONS_BIN" || -z "${EMSDK_ENV:-}" ]]; then
	printf 'The pinned SCons/Emscripten environment is incomplete.\n' >&2
	exit 1
fi
# shellcheck disable=SC1090
source "$EMSDK_ENV" >/dev/null

IFS=$'\t' read -r GODOT_REPOSITORY GODOT_COMMIT GODOT_VERSION TEMPLATE_ARTIFACT EMSDK_VERSION EMSDK_COMMIT SCONS_VERSION < <(
	python3 - "$ROOT_DIR/tools/ci_toolchain.json" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print(
    data["godot_source"]["repository"],
    data["godot_source"]["commit"],
    data["godot"]["version"],
    data["godot_source"]["template"]["artifact"],
    data["emsdk"]["version"],
    data["emsdk"]["commit"],
    data["scons"]["version"],
    sep="\t",
)
PY
)
if [[ "$(emcc --version | head -n 1)" != *" $EMSDK_VERSION "* ]]; then
	printf 'Emscripten %s validation failed.\n' "$EMSDK_VERSION" >&2
	exit 1
fi
if [[ "$($SCONS_BIN --version | head -n 2 | tail -n 1)" != *"v$SCONS_VERSION"* ]]; then
	printf 'SCons %s validation failed.\n' "$SCONS_VERSION" >&2
	exit 1
fi

GODOT_SOURCE_DIR="$TOOLS_ROOT/godot-source-$GODOT_COMMIT"
if [[ ! -d "$GODOT_SOURCE_DIR/.git" ]]; then
	git clone --filter=blob:none --no-checkout "$GODOT_REPOSITORY" "$GODOT_SOURCE_DIR"
	git -C "$GODOT_SOURCE_DIR" checkout --detach "$GODOT_COMMIT"
fi
ACTUAL_GODOT_COMMIT="$(git -C "$GODOT_SOURCE_DIR" rev-parse HEAD)"
if [[ "$ACTUAL_GODOT_COMMIT" != "$GODOT_COMMIT" ]]; then
	printf 'Godot source cache mismatch: expected %s, got %s.\n' \
		"$GODOT_COMMIT" "$ACTUAL_GODOT_COMMIT" >&2
	exit 1
fi
if [[ -n "$(git -C "$GODOT_SOURCE_DIR" status --porcelain --untracked-files=no)" ]]; then
	printf 'Godot source cache has tracked modifications.\n' >&2
	exit 1
fi

SOURCE_DATE_EPOCH="$(git -C "$GODOT_SOURCE_DIR" show -s --format=%ct HEAD)"
export SOURCE_DATE_EPOCH
JOBS="${MTERRAIN_BUILD_JOBS:-$(nproc 2>/dev/null || printf '4')}"
TEMPLATE_ARGUMENTS=(
	platform=web
	target=template_debug
	arch=wasm32
	threads=no
	dlink_enabled=yes
	production=no
)
"$SCONS_BIN" -C "$GODOT_SOURCE_DIR" "${TEMPLATE_ARGUMENTS[@]}" -j"$JOBS"

SOURCE_ARTIFACT="$GODOT_SOURCE_DIR/bin/$TEMPLATE_ARTIFACT"
if [[ ! -s "$SOURCE_ARTIFACT" ]]; then
	printf 'Godot did not produce the pinned dynamic-link template: %s\n' \
		"$SOURCE_ARTIFACT" >&2
	exit 1
fi
mkdir -p "$OUTPUT_DIR" "$ROOT_DIR/build/receipts"
OUTPUT_ARTIFACT="$OUTPUT_DIR/$TEMPLATE_ARTIFACT"
cp "$SOURCE_ARTIFACT" "$OUTPUT_ARTIFACT"

python3 - \
	"$ROOT_DIR" "$GODOT_SOURCE_DIR" "$OUTPUT_ARTIFACT" \
	"$GODOT_VERSION" "$GODOT_COMMIT" "$EMSDK_VERSION" "$EMSDK_COMMIT" \
	"$SCONS_VERSION" "$SOURCE_DATE_EPOCH" \
	"$ROOT_DIR/build/receipts/web-template-debug.json" <<'PY'
import datetime as dt
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

(
    root_text,
    source_text,
    artifact_text,
    godot_version,
    godot_commit,
    emsdk_version,
    emsdk_commit,
    scons_version,
    source_epoch_text,
    receipt_text,
) = sys.argv[1:]
root = Path(root_text)
source = Path(source_text)
artifact = Path(artifact_text)
receipt_path = Path(receipt_text)

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

members = []
with zipfile.ZipFile(artifact) as archive:
    for info in sorted(archive.infolist(), key=lambda value: value.filename):
        if info.is_dir():
            continue
        data = archive.read(info.filename)
        members.append(
            {
                "name": info.filename,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
member_names = {record["name"] for record in members}
if "godot.js" not in member_names or "godot.wasm" not in member_names:
    raise SystemExit("Dynamic-link template omitted the Godot JS/main wasm files")
if not any(name.endswith(".side.wasm") for name in member_names):
    raise SystemExit("Dynamic-link template omitted its engine side wasm module")

source_epoch = int(source_epoch_text)
receipt = {
    "schema": "mterrain-web-template-receipt-v1",
    "created_at": dt.datetime.fromtimestamp(
        source_epoch, tz=dt.timezone.utc
    ).isoformat(),
    "source_date_epoch": source_epoch,
    "source": {
        "repository": "https://github.com/godotengine/godot.git",
        "commit": godot_commit,
        "tree": subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD^{tree}"], text=True
        ).strip(),
        "tracked_dirty": bool(
            subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(source),
                    "status",
                    "--porcelain",
                    "--untracked-files=no",
                ],
                text=True,
            ).strip()
        ),
    },
    "target": {
        "godot": godot_version,
        "platform": "web",
        "target": "template_debug",
        "architecture": "wasm32",
        "precision": "single",
        "threads": False,
        "dynamic_linking": True,
        "production": False,
    },
    "toolchain": {
        "emscripten_version": emsdk_version,
        "emsdk_commit": emsdk_commit,
        "scons_version": scons_version,
        "configuration": {
            "path": "tools/ci_toolchain.json",
            "sha256": sha256(root / "tools" / "ci_toolchain.json"),
        },
    },
    "build_arguments": [
        "platform=web",
        "target=template_debug",
        "arch=wasm32",
        "threads=no",
        "dlink_enabled=yes",
        "production=no",
    ],
    "artifact": {
        "name": artifact.name,
        "size": artifact.stat().st_size,
        "sha256": sha256(artifact),
        "members": members,
    },
}
if receipt["source"]["tracked_dirty"]:
    raise SystemExit("Godot source was modified while building the template")
receipt_path.write_text(
    json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(receipt_path)
PY

printf '%s\n' "$OUTPUT_ARTIFACT"
