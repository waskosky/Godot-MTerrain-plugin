#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT="${1:-}"
GODOT_BIN="${GODOT_BIN:-${GODOT_CMD:-}}"

if [[ -z "$ARTIFACT" || ! -f "$ARTIFACT" ]]; then
	printf 'Usage: %s /absolute/path/to/libMTerrain.native.debug.library\n' "$0" >&2
	exit 2
fi
if [[ -z "$GODOT_BIN" || ! -x "$GODOT_BIN" ]]; then
	printf 'Set GODOT_BIN to the pinned Godot 4.7 editor executable.\n' >&2
	exit 1
fi

STAGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mterrain-native-smoke.XXXXXX")"
trap 'rm -rf "$STAGE_DIR"' EXIT
mkdir -p "$STAGE_DIR/.godot" "$STAGE_DIR/mterrain" "$STAGE_DIR/addons/m_terrain"
cp "$ROOT_DIR/tests/runtime_smoke/project.godot" "$STAGE_DIR/project.godot"
cp "$ROOT_DIR/tests/runtime_smoke/smoke.gd" "$STAGE_DIR/smoke.gd"
cp "$ROOT_DIR/tests/runtime_smoke/extension_list.cfg" "$STAGE_DIR/.godot/extension_list.cfg"
cp "$ROOT_DIR/gdextension/MTerrain.txt" "$STAGE_DIR/mterrain/MTerrain.gdextension"
cp "$ROOT_DIR/start_material_opengl.res" "$STAGE_DIR/addons/m_terrain/start_material_opengl.res"
cp "$ROOT_DIR/start_opengl.gdshader" "$STAGE_DIR/addons/m_terrain/start_opengl.gdshader"
cp "$ROOT_DIR/start_opengl.gdshader.uid" "$STAGE_DIR/addons/m_terrain/start_opengl.gdshader.uid"

case "$(uname -s)" in
	Darwin)
		cp "$ARTIFACT" "$STAGE_DIR/mterrain/libMTerrain.macos.template_debug.universal.dylib"
		;;
	Linux)
		cp "$ARTIFACT" "$STAGE_DIR/mterrain/libMTerrain.linux.template_debug.x86_64.so"
		;;
	*)
		printf 'Native core smoke is implemented for macOS and Linux hosts.\n' >&2
		exit 2
		;;
esac

OUTPUT="$($GODOT_BIN --headless --path "$STAGE_DIR" --script res://smoke.gd 2>&1)" || {
	printf '%s\n' "$OUTPUT" >&2
	exit 1
}
printf '%s\n' "$OUTPUT"
if [[ "$OUTPUT" != *"MTERRAIN_RUNTIME_SMOKE_OK"* ]]; then
	printf 'MTerrain runtime smoke did not emit its success marker.\n' >&2
	exit 1
fi
PERSISTED_TERRAIN_FILE="$(find "$STAGE_DIR" -type f \( -name 'x*_y*.res' -o -name '.save_config.ini' \) -print -quit)"
if [[ -n "$PERSISTED_TERRAIN_FILE" ]]; then
	printf 'Memory-only runtime smoke wrote terrain persistence files.\n' >&2
	exit 1
fi
