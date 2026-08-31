#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS_ROOT="${1:-}"
COMPONENTS="${2:-web}"

if [[ -z "$TOOLS_ROOT" ]]; then
	printf 'Usage: %s /absolute/tool/root [host|web|browser]\n' "$0" >&2
	exit 2
fi
case "$COMPONENTS" in
	host|web|browser) ;;
	*)
		printf 'Components must be host, web, or browser.\n' >&2
		exit 2
		;;
esac
if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
	printf 'The clean-clone CI installer supports Linux x86_64 only.\n' >&2
	exit 2
fi

TOOLS_ROOT="$(python3 - "$TOOLS_ROOT" <<'PY'
import sys
from pathlib import Path
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
if [[ "$TOOLS_ROOT" == "/" ]]; then
	printf 'Refusing to use the filesystem root as a tool directory.\n' >&2
	exit 2
fi
mkdir -p "$TOOLS_ROOT/downloads"

IFS=$'\t' read -r GODOT_VERSION GODOT_URL GODOT_SHA GODOT_NAME SCONS_VERSION SCONS_URL SCONS_SHA EMSDK_VERSION EMSDK_COMMIT EMSDK_REPOSITORY BROTLI_VERSION BROTLI_COMMIT BROTLI_REPOSITORY < <(
	python3 - "$ROOT_DIR/tools/ci_toolchain.json" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
print(
    data["godot"]["version"],
    data["godot"]["asset_url"],
    data["godot"]["asset_sha256"],
    data["godot"]["executable"],
    data["scons"]["version"],
    data["scons"]["wheel_url"],
    data["scons"]["wheel_sha256"],
    data["emsdk"]["version"],
    data["emsdk"]["commit"],
    data["emsdk"]["repository"],
    data["brotli"]["version"],
    data["brotli"]["commit"],
    data["brotli"]["repository"],
    sep="\t",
)
PY
)

sha256_file() {
	sha256sum "$1" | awk '{print $1}'
}

download_checked() {
	local url="$1"
	local expected="$2"
	local destination="$3"
	if [[ -f "$destination" && "$(sha256_file "$destination")" == "$expected" ]]; then
		return
	fi
	local partial="$destination.partial.$$"
	trap 'rm -f "$partial"' RETURN
	curl --fail --location --retry 5 --retry-all-errors --output "$partial" "$url"
	local actual
	actual="$(sha256_file "$partial")"
	if [[ "$actual" != "$expected" ]]; then
		printf 'Download digest mismatch for %s: expected %s, got %s.\n' \
			"$url" "$expected" "$actual" >&2
		exit 1
	fi
	mv "$partial" "$destination"
	trap - RETURN
}

GODOT_ARCHIVE="$TOOLS_ROOT/downloads/${GODOT_URL##*/}"
GODOT_DIR="$TOOLS_ROOT/godot-$GODOT_VERSION"
GODOT_BIN="$GODOT_DIR/$GODOT_NAME"
download_checked "$GODOT_URL" "$GODOT_SHA" "$GODOT_ARCHIVE"
if [[ ! -x "$GODOT_BIN" ]]; then
	mkdir -p "$GODOT_DIR"
	unzip -q -o "$GODOT_ARCHIVE" -d "$GODOT_DIR"
	chmod +x "$GODOT_BIN"
fi
ACTUAL_GODOT_VERSION="$($GODOT_BIN --version)"
if [[ "$ACTUAL_GODOT_VERSION" != "$GODOT_VERSION" ]]; then
	printf 'Godot pin mismatch: expected %s, got %s.\n' \
		"$GODOT_VERSION" "$ACTUAL_GODOT_VERSION" >&2
	exit 1
fi

SCONS_WHEEL="$TOOLS_ROOT/downloads/${SCONS_URL##*/}"
SCONS_VENV="$TOOLS_ROOT/scons-$SCONS_VERSION"
SCONS_BIN="$SCONS_VENV/bin/scons"
download_checked "$SCONS_URL" "$SCONS_SHA" "$SCONS_WHEEL"
if [[ ! -x "$SCONS_BIN" ]]; then
	python3 -m venv "$SCONS_VENV"
	"$SCONS_VENV/bin/python" -m pip install \
		--disable-pip-version-check --no-deps --no-index "$SCONS_WHEEL"
fi
if [[ "$($SCONS_BIN --version | head -n 2 | tail -n 1)" != *"v$SCONS_VERSION"* ]]; then
	printf 'SCons %s validation failed.\n' "$SCONS_VERSION" >&2
	exit 1
fi

ENVIRONMENT_FILE="$TOOLS_ROOT/environment.sh"
{
	printf 'export GODOT_BIN=%q\n' "$GODOT_BIN"
	printf 'export SCONS_BIN=%q\n' "$SCONS_BIN"
} > "$ENVIRONMENT_FILE"

if [[ "$COMPONENTS" != "host" ]]; then
	EMSDK_DIR="$TOOLS_ROOT/emsdk-$EMSDK_COMMIT"
	if [[ ! -d "$EMSDK_DIR/.git" ]]; then
		git clone --filter=blob:none "$EMSDK_REPOSITORY" "$EMSDK_DIR"
		git -C "$EMSDK_DIR" checkout --detach "$EMSDK_COMMIT"
	fi
	ACTUAL_EMSDK_COMMIT="$(git -C "$EMSDK_DIR" rev-parse HEAD)"
	if [[ "$ACTUAL_EMSDK_COMMIT" != "$EMSDK_COMMIT" ]]; then
		printf 'emsdk cache mismatch: expected %s, got %s.\n' \
			"$EMSDK_COMMIT" "$ACTUAL_EMSDK_COMMIT" >&2
		exit 1
	fi
	if [[ ! -x "$EMSDK_DIR/upstream/emscripten/emcc" ]]; then
		"$EMSDK_DIR/emsdk" install "$EMSDK_VERSION"
	fi
	"$EMSDK_DIR/emsdk" activate "$EMSDK_VERSION"
	# shellcheck disable=SC1091
	source "$EMSDK_DIR/emsdk_env.sh" >/dev/null
	if [[ "$(emcc --version | head -n 1)" != *" $EMSDK_VERSION "* ]]; then
		printf 'Emscripten %s validation failed.\n' "$EMSDK_VERSION" >&2
		exit 1
	fi

	{
		printf 'export EMSDK_ENV=%q\n' "$EMSDK_DIR/emsdk_env.sh"
		printf 'export WASM_OPT_BIN=%q\n' "$EMSDK_DIR/upstream/bin/wasm-opt"
	} >> "$ENVIRONMENT_FILE"
	if [[ "$COMPONENTS" == "web" ]]; then
		BROTLI_SOURCE="$TOOLS_ROOT/brotli-source-$BROTLI_COMMIT"
		BROTLI_BUILD="$TOOLS_ROOT/brotli-build-$BROTLI_COMMIT"
		BROTLI_BIN="$BROTLI_BUILD/brotli"
		if [[ ! -d "$BROTLI_SOURCE/.git" ]]; then
			git clone --filter=blob:none "$BROTLI_REPOSITORY" "$BROTLI_SOURCE"
			git -C "$BROTLI_SOURCE" checkout --detach "$BROTLI_COMMIT"
		fi
		ACTUAL_BROTLI_COMMIT="$(git -C "$BROTLI_SOURCE" rev-parse HEAD)"
		if [[ "$ACTUAL_BROTLI_COMMIT" != "$BROTLI_COMMIT" ]]; then
			printf 'brotli cache mismatch: expected %s, got %s.\n' \
				"$BROTLI_COMMIT" "$ACTUAL_BROTLI_COMMIT" >&2
			exit 1
		fi
		if [[ ! -x "$BROTLI_BIN" ]]; then
			cmake -S "$BROTLI_SOURCE" -B "$BROTLI_BUILD" -G Ninja \
				-DCMAKE_BUILD_TYPE=Release \
				-DBUILD_SHARED_LIBS=OFF \
				-DBROTLI_DISABLE_TESTS=ON
			cmake --build "$BROTLI_BUILD" --target brotli --parallel
		fi
		if [[ "$($BROTLI_BIN --version)" != *" $BROTLI_VERSION"* ]]; then
			printf 'Brotli %s validation failed.\n' "$BROTLI_VERSION" >&2
			exit 1
		fi
		printf 'export BROTLI_BIN=%q\n' "$BROTLI_BIN" >> "$ENVIRONMENT_FILE"
	fi
fi

if [[ "$COMPONENTS" == "browser" ]]; then
	if [[ "$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" != "3.12" ]]; then
		printf 'The pinned browser wheel set requires Python 3.12.\n' >&2
		exit 1
	fi
	PLAYWRIGHT_VERSION="$(python3 - "$ROOT_DIR/tools/ci_toolchain.json" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["playwright"]["version"])
PY
)"
	PLAYWRIGHT_VENV="$TOOLS_ROOT/playwright-$PLAYWRIGHT_VERSION"
	PLAYWRIGHT_BIN="$PLAYWRIGHT_VENV/bin/playwright"
	PLAYWRIGHT_WHEEL_PATHS=()
	while IFS=$'\t' read -r WHEEL_NAME WHEEL_VERSION WHEEL_URL WHEEL_SHA; do
		WHEEL_PATH="$TOOLS_ROOT/downloads/${WHEEL_URL##*/}"
		download_checked "$WHEEL_URL" "$WHEEL_SHA" "$WHEEL_PATH"
		PLAYWRIGHT_WHEEL_PATHS+=("$WHEEL_PATH")
	done < <(
		python3 - "$ROOT_DIR/tools/ci_toolchain.json" <<'PY'
import json
import sys
for wheel in json.load(open(sys.argv[1], encoding="utf-8"))["playwright"]["wheels"]:
    print(wheel["name"], wheel["version"], wheel["url"], wheel["sha256"], sep="\t")
PY
	)
	if [[ ! -x "$PLAYWRIGHT_BIN" ]]; then
		python3 -m venv "$PLAYWRIGHT_VENV"
		"$PLAYWRIGHT_VENV/bin/python" -m pip install \
			--disable-pip-version-check --no-deps --no-index \
			"${PLAYWRIGHT_WHEEL_PATHS[@]}"
	fi
	ACTUAL_PLAYWRIGHT_VERSION="$(
		"$PLAYWRIGHT_VENV/bin/python" -c \
		'import importlib.metadata; print(importlib.metadata.version("playwright"))'
	)"
	if [[ "$ACTUAL_PLAYWRIGHT_VERSION" != "$PLAYWRIGHT_VERSION" ]]; then
		printf 'Playwright pin mismatch: expected %s, got %s.\n' \
			"$PLAYWRIGHT_VERSION" "$ACTUAL_PLAYWRIGHT_VERSION" >&2
		exit 1
	fi
	"$PLAYWRIGHT_VENV/bin/python" - "$ROOT_DIR/tools/ci_toolchain.json" <<'PY'
import importlib.metadata
import json
import sys
for wheel in json.load(open(sys.argv[1], encoding="utf-8"))["playwright"]["wheels"]:
    actual = importlib.metadata.version(wheel["name"])
    if actual != wheel["version"]:
        raise SystemExit(
            f"Browser dependency mismatch for {wheel['name']}: "
            f"expected {wheel['version']}, got {actual}"
        )
PY
	PLAYWRIGHT_BROWSERS_PATH="$TOOLS_ROOT/playwright-browsers-$PLAYWRIGHT_VERSION"
	IFS=$'\t' read -r -a PLAYWRIGHT_BROWSERS < <(
		python3 - "$ROOT_DIR/tools/ci_toolchain.json" <<'PY'
import json
import sys
print(*json.load(open(sys.argv[1], encoding="utf-8"))["playwright"]["browsers"], sep="\t")
PY
	)
	PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" \
		"$PLAYWRIGHT_BIN" install "${PLAYWRIGHT_BROWSERS[@]}"
	BROWSER_RECEIPT="$TOOLS_ROOT/browser-toolchain-receipt.json"
	PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" \
		"$PLAYWRIGHT_VENV/bin/python" "$ROOT_DIR/scripts/write_browser_toolchain_receipt.py" \
		--browsers-root "$PLAYWRIGHT_BROWSERS_PATH" \
		--output "$BROWSER_RECEIPT"
	{
		printf 'export PLAYWRIGHT_PYTHON=%q\n' "$PLAYWRIGHT_VENV/bin/python"
		printf 'export PLAYWRIGHT_CLI=%q\n' "$PLAYWRIGHT_BIN"
		printf 'export PLAYWRIGHT_BROWSERS_PATH=%q\n' "$PLAYWRIGHT_BROWSERS_PATH"
		printf 'export BROWSER_TOOLCHAIN_RECEIPT=%q\n' "$BROWSER_RECEIPT"
	} >> "$ENVIRONMENT_FILE"
fi

chmod 0600 "$ENVIRONMENT_FILE"
printf '%s\n' "$ENVIRONMENT_FILE"
