#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLCHAIN_FILE="$ROOT_DIR/tools/web_toolchain.json"
BUILD_MODE="${1:-all}"

case "$BUILD_MODE" in
	debug|release|all) ;;
	*)
		printf 'Usage: %s [debug|release|all]\n' "$0" >&2
		exit 2
		;;
esac

IFS=$'\t' read -r GODOT_PIN GODOT_COMMIT GODOT_CPP_PIN EMCC_PIN EMSDK_PIN BINARYEN_PIN SCONS_PIN BROTLI_PIN BROTLI_QUALITY < <(
	python3 - "$TOOLCHAIN_FILE" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
print(
    data["godot"]["version"],
    data["godot"]["commit"],
    data["godot_cpp_commit"],
    data["emscripten_version"],
    data["emsdk_commit"],
    data["binaryen_version"],
    data["scons_version"],
    data["brotli_version"],
    data["brotli_quality"],
    sep="\t",
)
PY
)

GODOT_BIN="${GODOT_BIN:-${GODOT_CMD:-}}"
if [[ -z "$GODOT_BIN" ]]; then
	GODOT_BIN="$(command -v godot || true)"
fi
if [[ -z "$GODOT_BIN" || ! -x "$GODOT_BIN" ]]; then
	printf 'Set GODOT_BIN to the pinned Godot %s editor executable.\n' "$GODOT_PIN" >&2
	exit 1
fi

SCONS_BIN="${SCONS_BIN:-$(command -v scons || true)}"
if [[ -z "$SCONS_BIN" || ! -x "$SCONS_BIN" ]]; then
	printf 'Set SCONS_BIN to a SCons %s executable.\n' "$SCONS_PIN" >&2
	exit 1
fi

if ! command -v emcc >/dev/null 2>&1; then
	if [[ -n "${EMSDK_ENV:-}" && -f "$EMSDK_ENV" ]]; then
		# shellcheck disable=SC1090
		source "$EMSDK_ENV" >/dev/null
	else
		printf 'Activate Emscripten %s or set EMSDK_ENV to emsdk_env.sh.\n' "$EMCC_PIN" >&2
		exit 1
	fi
fi

ACTUAL_GODOT_VERSION="$($GODOT_BIN --version)"
if [[ "$ACTUAL_GODOT_VERSION" != "$GODOT_PIN" ]]; then
	printf 'Godot pin mismatch: expected %s, got %s.\n' "$GODOT_PIN" "$ACTUAL_GODOT_VERSION" >&2
	exit 1
fi

ACTUAL_GODOT_CPP="$(git -C "$ROOT_DIR/gdextension/godot-cpp" rev-parse HEAD)"
if [[ "$ACTUAL_GODOT_CPP" != "$GODOT_CPP_PIN" ]]; then
	printf 'godot-cpp pin mismatch: expected %s, got %s.\n' "$GODOT_CPP_PIN" "$ACTUAL_GODOT_CPP" >&2
	exit 1
fi

ACTUAL_EMCC="$(emcc --version | head -n 1)"
if [[ "$ACTUAL_EMCC" != *" $EMCC_PIN "* ]]; then
	printf 'Emscripten pin mismatch: expected %s, got %s.\n' "$EMCC_PIN" "$ACTUAL_EMCC" >&2
	exit 1
fi
if [[ -z "${EMSDK:-}" || ! -d "$EMSDK/.git" ]]; then
	printf 'The active Emscripten SDK must expose its git checkout through EMSDK.\n' >&2
	exit 1
fi
ACTUAL_EMSDK="$(git -C "$EMSDK" rev-parse HEAD)"
if [[ "$ACTUAL_EMSDK" != "$EMSDK_PIN" ]]; then
	printf 'emsdk pin mismatch: expected %s, got %s.\n' "$EMSDK_PIN" "$ACTUAL_EMSDK" >&2
	exit 1
fi

WASM_OPT_BIN="${WASM_OPT_BIN:-$EMSDK/upstream/bin/wasm-opt}"
if [[ ! -x "$WASM_OPT_BIN" ]]; then
	printf 'The pinned wasm-opt executable is missing: %s\n' "$WASM_OPT_BIN" >&2
	exit 1
fi
ACTUAL_BINARYEN="$($WASM_OPT_BIN --version)"
if [[ "$ACTUAL_BINARYEN" != "$BINARYEN_PIN" ]]; then
	printf 'Binaryen pin mismatch: expected %s, got %s.\n' "$BINARYEN_PIN" "$ACTUAL_BINARYEN" >&2
	exit 1
fi

ACTUAL_SCONS="$($SCONS_BIN --version | head -n 2 | tail -n 1)"
if [[ "$ACTUAL_SCONS" != *"v$SCONS_PIN"* ]]; then
	printf 'SCons pin mismatch: expected %s, got %s.\n' "$SCONS_PIN" "$ACTUAL_SCONS" >&2
	exit 1
fi

BROTLI_BIN="${BROTLI_BIN:-$(command -v brotli || true)}"
if [[ -z "$BROTLI_BIN" || ! -x "$BROTLI_BIN" ]]; then
	printf 'Set BROTLI_BIN to a Brotli %s executable.\n' "$BROTLI_PIN" >&2
	exit 1
fi
ACTUAL_BROTLI="$($BROTLI_BIN --version)"
if [[ "$ACTUAL_BROTLI" != *" $BROTLI_PIN" ]]; then
	printf 'Brotli pin mismatch: expected %s, got %s.\n' "$BROTLI_PIN" "$ACTUAL_BROTLI" >&2
	exit 1
fi

if [[ "${MTERRAIN_REQUIRE_CLEAN:-0}" == "1" ]]; then
	SOURCE_STATUS="$(git -C "$ROOT_DIR" status --porcelain --untracked-files=normal --ignore-submodules=dirty)"
	if [[ -n "$SOURCE_STATUS" ]]; then
		printf 'MTERRAIN_REQUIRE_CLEAN=1 refuses to build a dirty source tree.\n' >&2
		exit 1
	fi
fi

API_DIR="$ROOT_DIR/build/web/api"
OUTPUT_DIR="$ROOT_DIR/build/mterrain"
RECEIPT_DIR="$ROOT_DIR/build/receipts"
mkdir -p "$API_DIR" "$OUTPUT_DIR" "$RECEIPT_DIR"
(
	cd "$API_DIR"
	"$GODOT_BIN" --headless --dump-extension-api
)

python3 - "$API_DIR/extension_api.json" <<'PY'
import json
import sys

header = json.load(open(sys.argv[1], encoding="utf-8"))["header"]
actual = (
    header["version_major"],
    header["version_minor"],
    header["version_patch"],
    header["version_status"],
    header["precision"],
)
expected = (4, 7, 0, "stable", "single")
if actual != expected:
    raise SystemExit(f"GDExtension API mismatch: expected {expected!r}, got {actual!r}")
PY

JOBS="${MTERRAIN_BUILD_JOBS:-$(sysctl -n hw.logicalcpu 2>/dev/null || printf '4')}"

build_target() {
	local mode="$1"
	local target="template_$mode"
	"$SCONS_BIN" -C "$ROOT_DIR/gdextension" \
		platform=web \
		arch=wasm32 \
		target="$target" \
		precision=single \
		threads=no \
		api_version=4.7 \
		mterrain_profile=web_core \
		mterrain_output_dir="$OUTPUT_DIR" \
		custom_api_file="$API_DIR/extension_api.json" \
		build_profile="$ROOT_DIR/gdextension/web_core_build_profile.json" \
		-j"$JOBS"
	local artifact="$OUTPUT_DIR/libMTerrain.web.$target.wasm32.nothreads.wasm"
	if [[ ! -s "$artifact" ]]; then
		printf 'Expected Web side module was not produced: %s\n' "$artifact" >&2
		exit 1
	fi
	local wasm_features
	wasm_features="$($WASM_OPT_BIN "$artifact" --print-features 2>&1)"
	if [[ "$wasm_features" == *"--enable-threads"* || "$wasm_features" == *"--enable-shared-everything"* ]]; then
		printf 'No-thread Web artifact unexpectedly requires a shared-memory feature:\n%s\n' "$wasm_features" >&2
		exit 1
	fi
	python3 "$ROOT_DIR/scripts/write_web_build_receipt.py" \
		--artifact "$artifact" \
		--api "$API_DIR/extension_api.json" \
		--binding-profile "$ROOT_DIR/gdextension/web_core_build_profile.json" \
		--godot-version "$ACTUAL_GODOT_VERSION" \
		--emcc-version "$ACTUAL_EMCC" \
		--scons-version "$ACTUAL_SCONS" \
		--wasm-opt-bin "$WASM_OPT_BIN" \
		--wasm-opt-version "$ACTUAL_BINARYEN" \
		--brotli-bin "$BROTLI_BIN" \
		--brotli-version "$ACTUAL_BROTLI" \
		--brotli-quality "$BROTLI_QUALITY" \
		--target "$target" \
		--toolchain "$TOOLCHAIN_FILE" \
		--output "$RECEIPT_DIR/web-$target.json"
}

if [[ "$BUILD_MODE" == "debug" || "$BUILD_MODE" == "all" ]]; then
	build_target debug
fi
if [[ "$BUILD_MODE" == "release" || "$BUILD_MODE" == "all" ]]; then
	build_target release
fi
