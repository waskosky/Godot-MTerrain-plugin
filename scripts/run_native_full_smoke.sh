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

STAGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mterrain-full-smoke.XXXXXX")"
trap 'rm -rf "$STAGE_DIR"' EXIT
mkdir -p "$STAGE_DIR/.godot" "$STAGE_DIR/mterrain"
cp "$ROOT_DIR/tests/full_profile_smoke/project.godot" "$STAGE_DIR/project.godot"
cp "$ROOT_DIR/tests/full_profile_smoke/smoke.gd" "$STAGE_DIR/smoke.gd"
cp "$ROOT_DIR/tests/full_profile_smoke/extension_list.cfg" "$STAGE_DIR/.godot/extension_list.cfg"
cp "$ROOT_DIR/gdextension/MTerrain.txt" "$STAGE_DIR/mterrain/MTerrain.gdextension"

case "$(uname -s)" in
	Darwin)
		cp "$ARTIFACT" "$STAGE_DIR/mterrain/libMTerrain.macos.template_debug.universal.dylib"
		;;
	Linux)
		cp "$ARTIFACT" "$STAGE_DIR/mterrain/libMTerrain.linux.template_debug.x86_64.so"
		;;
	*)
		printf 'Native full-profile smoke is implemented for macOS and Linux hosts.\n' >&2
		exit 2
		;;
esac

OUTPUT="$($GODOT_BIN --headless --path "$STAGE_DIR" --script res://smoke.gd 2>&1)" || {
	printf '%s\n' "$OUTPUT" >&2
	exit 1
}
printf '%s\n' "$OUTPUT"
if [[ "$OUTPUT" != *"MTERRAIN_FULL_PROFILE_SMOKE_OK"* ]]; then
	printf 'MTerrain full-profile smoke did not emit its success marker.\n' >&2
	exit 1
fi
