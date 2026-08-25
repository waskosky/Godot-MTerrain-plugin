#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GODOT_BIN="${GODOT_BIN:-${GODOT_CMD:-}}"

if [[ -z "$GODOT_BIN" || ! -x "$GODOT_BIN" ]]; then
	printf 'Set GODOT_BIN to the pinned Godot 4.7 editor executable.\n' >&2
	exit 1
fi

STAGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mterrain-extended-smoke.XXXXXX")"
trap 'rm -rf "$STAGE_DIR"' EXIT
mkdir -p "$STAGE_DIR/runtime"
cp "$ROOT_DIR/tests/extended_runtime_smoke/project.godot" "$STAGE_DIR/project.godot"
cp "$ROOT_DIR/tests/extended_runtime_smoke/smoke.gd" "$STAGE_DIR/smoke.gd"
cp "$ROOT_DIR/runtime/web_extended_runtime.gd" "$STAGE_DIR/runtime/web_extended_runtime.gd"

OUTPUT="$($GODOT_BIN --headless --path "$STAGE_DIR" --script res://smoke.gd 2>&1)" || {
	printf '%s\n' "$OUTPUT" >&2
	exit 1
}
printf '%s\n' "$OUTPUT"
if [[ "$OUTPUT" != *"MTERRAIN_WEB_EXTENDED_SMOKE_OK"* ]]; then
	printf 'MTerrain extended runtime smoke did not emit its success marker.\n' >&2
	exit 1
fi
