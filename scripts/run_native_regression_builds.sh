#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GODOT_BIN="${GODOT_BIN:-${GODOT_CMD:-}}"
SCONS_BIN="${SCONS_BIN:-$(command -v scons || true)}"

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
	printf 'The clean-CI native regression build supports Linux x86_64 only.\n' >&2
	exit 2
fi
if [[ -z "$GODOT_BIN" || ! -x "$GODOT_BIN" ]]; then
	printf 'Set GODOT_BIN to the pinned Godot 4.7 editor executable.\n' >&2
	exit 1
fi
if [[ -z "$SCONS_BIN" || ! -x "$SCONS_BIN" ]]; then
	printf 'Set SCONS_BIN to the pinned SCons executable.\n' >&2
	exit 1
fi
if [[ "${MTERRAIN_REQUIRE_CLEAN:-0}" == "1" ]]; then
	SOURCE_STATUS="$(git -C "$ROOT_DIR" status --porcelain --untracked-files=normal --ignore-submodules=dirty)"
	if [[ -n "$SOURCE_STATUS" ]]; then
		printf 'MTERRAIN_REQUIRE_CLEAN=1 refuses to build a dirty source tree.\n' >&2
		exit 1
	fi
fi

API_DIR="$ROOT_DIR/build/native/api"
mkdir -p "$API_DIR"
(
	cd "$API_DIR"
	"$GODOT_BIN" --headless --dump-extension-api
)
API_FILE="$API_DIR/extension_api.json"
JOBS="${MTERRAIN_BUILD_JOBS:-$(nproc 2>/dev/null || printf '4')}"

build_profile() {
	local profile="$1"
	local target="$2"
	local output="$3"
	shift 3
	"$SCONS_BIN" -C "$ROOT_DIR/gdextension" \
		platform=linux arch=x86_64 target="$target" precision=single \
		api_version=4.7 custom_api_file="$API_FILE" \
		mterrain_profile="$profile" mterrain_output_dir="$output" \
		-j"$JOBS" "$@"
}

FULL_DEBUG="$ROOT_DIR/build/mterrain/native-full-debug"
FULL_RELEASE="$ROOT_DIR/build/mterrain/native-full-release"
CORE_DEBUG="$ROOT_DIR/build/mterrain/native-web-core"
EXTENDED_DEBUG="$ROOT_DIR/build/mterrain/native-web-extended"

build_profile full template_debug "$FULL_DEBUG"
GODOT_BIN="$GODOT_BIN" "$ROOT_DIR/scripts/run_native_full_smoke.sh" \
	"$FULL_DEBUG/libMTerrain.linux.template_debug.x86_64.so"

build_profile full template_release "$FULL_RELEASE"
test -s "$FULL_RELEASE/libMTerrain.linux.template_release.x86_64.so"

build_profile web_core template_debug "$CORE_DEBUG" \
	threads=no build_profile="$ROOT_DIR/gdextension/web_core_build_profile.json"
GODOT_BIN="$GODOT_BIN" "$ROOT_DIR/scripts/run_native_core_smoke.sh" \
	"$CORE_DEBUG/libMTerrain.linux.template_debug.x86_64.nothreads.so" web_core

build_profile web_extended template_debug "$EXTENDED_DEBUG" \
	threads=no build_profile="$ROOT_DIR/gdextension/web_core_build_profile.json"
GODOT_BIN="$GODOT_BIN" "$ROOT_DIR/scripts/run_native_core_smoke.sh" \
	"$EXTENDED_DEBUG/libMTerrain.linux.template_debug.x86_64.nothreads.so" \
	web_extended
GODOT_BIN="$GODOT_BIN" "$ROOT_DIR/scripts/run_extended_runtime_smoke.sh"

printf 'MTERRAIN_NATIVE_REGRESSIONS_OK\n'
