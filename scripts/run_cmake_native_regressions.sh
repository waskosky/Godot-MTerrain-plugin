#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GODOT_BIN="${GODOT_BIN:-${GODOT_CMD:-}}"
if [[ -z "$GODOT_BIN" || ! -x "$GODOT_BIN" ]]; then
	printf 'Set GODOT_BIN to the pinned Godot 4.7 editor.\n' >&2
	exit 1
fi
if [[ "${MTERRAIN_REQUIRE_CLEAN:-0}" == 1 && -n "$(git -C "$ROOT_DIR" status --porcelain --untracked-files=normal --ignore-submodules=dirty)" ]]; then
	printf 'MTERRAIN_REQUIRE_CLEAN=1 refuses dirty CMake regression sources.\n' >&2
	exit 1
fi
JOBS="${MTERRAIN_BUILD_JOBS:-4}"
case "$(uname -s)" in
	Darwin) platform=macos; extension=dylib ;;
	Linux) platform=linux; extension=so ;;
	*) printf 'Native CMake regression smoke supports macOS/Linux hosts.\n' >&2; exit 2 ;;
esac
case "$(uname -m)" in
	x86_64|amd64) arch=x86_64 ;;
	arm64|aarch64) arch=arm64 ;;
	*) printf 'Native CMake regression smoke requires x86_64 or arm64.\n' >&2; exit 2 ;;
esac
API_DIR="$ROOT_DIR/build/native/api"
mkdir -p "$API_DIR"
(
	cd "$API_DIR"
	"$GODOT_BIN" --headless --dump-extension-api
)
for target in template_debug template_release; do
	configuration=Debug
	if [[ "$target" == template_release ]]; then configuration=Release; fi
	build="$ROOT_DIR/build/cmake/full-$target"
	output="$ROOT_DIR/build/mterrain/cmake-full-$target"
	cmake -S "$ROOT_DIR/gdextension" -B "$build" \
		-DCMAKE_BUILD_TYPE="$configuration" -DMTERRAIN_PROFILE=full \
		-DGODOTCPP_TARGET="$target" -DGODOTCPP_API_VERSION=4.7 \
		-DGODOTCPP_ARCH="$arch" -DGODOTCPP_PRECISION=single \
		-DGODOTCPP_THREADS=ON -DGODOTCPP_DEV_BUILD=OFF \
		-DGODOTCPP_CUSTOM_API_FILE="$API_DIR/extension_api.json" \
		-DGODOTCPP_BUILD_PROFILE="$ROOT_DIR/gdextension/native_full_build_profile.json" \
		-DMTERRAIN_OUTPUT_DIR="$output"
	cmake --build "$build" --parallel "$JOBS"
	if [[ "$target" == template_debug ]]; then
		library="$output/libMTerrain.$platform.template_debug.$arch.$extension"
		GODOT_BIN="$GODOT_BIN" "$ROOT_DIR/scripts/run_native_full_smoke.sh" "$library" "$output/MTerrain.gdextension"
	fi
done

# Link the static runtime into an application-owned entry point. Building only
# the archive would miss unresolved references to excluded authoring sources.
embedded="$ROOT_DIR/build/cmake/embedded-runtime"
cmake -S "$ROOT_DIR/tests/cmake_embedding" -B "$embedded" \
	-DCMAKE_BUILD_TYPE=Debug -DGODOTCPP_TARGET=template_debug \
	-DGODOTCPP_API_VERSION=4.7 -DGODOTCPP_ARCH="$arch" \
	-DGODOTCPP_PRECISION=single -DGODOTCPP_THREADS=ON -DGODOTCPP_DEV_BUILD=OFF \
	-DGODOTCPP_CUSTOM_API_FILE="$API_DIR/extension_api.json" \
	-DGODOTCPP_BUILD_PROFILE="$ROOT_DIR/gdextension/native_full_build_profile.json"
cmake --build "$embedded" --parallel "$JOBS"
OUTPUT="$("$GODOT_BIN" --headless --path "$embedded/project" --script res://smoke.gd 2>&1)" || {
	printf '%s\n' "$OUTPUT" >&2
	exit 1
}
printf '%s\n' "$OUTPUT"
if [[ "$OUTPUT" != *"MTERRAIN_EMBEDDED_RUNTIME_OK"* ]]; then
	printf 'CMake embedding smoke did not emit its success marker.\n' >&2
	exit 1
fi
printf 'MTERRAIN_CMAKE_NATIVE_REGRESSIONS_OK\n'
