# MTerrain Web release process

The Web release lane produces two independently selectable runtime bundles from
one clean source revision. Compiled files remain ignored locally and are
published only as CI review artifacts or immutable GitHub release assets.

## Clean-clone reproduction

The canonical builder is Ubuntu 24.04 x86_64. It resolves every downloaded or
source-built tool through `tools/ci_toolchain.json`, validates those values
against the two Web toolchain contracts, and refuses dirty source trees.

```sh
git clone --recurse-submodules \
  https://github.com/waskosky/Godot-MTerrain-plugin.git
cd Godot-MTerrain-plugin
git checkout web-runtime-v0.1.0-rc.2

sudo apt-get update
sudo apt-get install --yes cmake ninja-build python3-venv

CI_TOOLS="$(mktemp -d)/mterrain-ci"
./scripts/install_web_ci_toolchain.sh "$CI_TOOLS" web
source "$CI_TOOLS/environment.sh"

export MTERRAIN_REQUIRE_CLEAN=1
./scripts/build_web.sh all web_core
./scripts/build_web.sh all web_extended
python3 scripts/package_web_release.py \
  --version web-runtime-v0.1.0-rc.2
python3 scripts/package_web_release.py \
  --verify-dir build/distribution
```

The installer is intentionally CI-host-specific; other hosts may provide their
own exact pinned tools to `build_web.sh`. Web compiler inputs normalize the
checkout prefix to `/mterrain`, and receipt/package timestamps use the source
commit epoch. The release index records the actual output digests. A successful
clean rebuild proves the source and toolchain procedure; byte-for-byte equality
across distinct kernels and filesystems is not claimed until a separate
two-environment reproducibility gate records it.

Run the native Linux regression lane independently:

```sh
HOST_TOOLS="$(mktemp -d)/mterrain-host"
./scripts/install_web_ci_toolchain.sh "$HOST_TOOLS" host
source "$HOST_TOOLS/environment.sh"
export MTERRAIN_REQUIRE_CLEAN=1
./scripts/run_native_regression_builds.sh
```

That lane compiles full native debug and release profiles, loads the registered
native authoring/runtime classes, loads native core and extended profiles, and
runs both bounded runtime smokes. The full MTerrain source still compiles; its
generated `godot-cpp` wrapper set is constrained by
`gdextension/native_full_build_profile.json` to the engine classes that source
uses. This keeps the Linux static archive below host command-line limits without
removing an MTerrain subsystem or changing the shipped native class registry.

## Published assets

Each release contains:

- a `web_core` archive with debug/release no-thread wasm side modules, the
  GDExtension manifest, Compatibility material resources, API/support docs, and
  matching receipts;
- a `web_extended` archive with the same categories plus the separately hashed
  extended runtime companion;
- one standalone `mterrain-web-runtime-contract-v1` document, also byte-identical
  inside both archives, listing the target tuple, required methods/capabilities,
  hard limits, state versions, and unsupported behavior;
- one machine-readable `mterrain-web-release-index-v1` document binding source,
  target, runtime contract, profile, artifact, companion, receipt, and bundle
  digests;
- `SHA256SUMS` covering both bundles, the runtime contract, and release index.

Always begin with the release index. Verify a downloaded directory without
extracting into a project:

```sh
python3 scripts/package_web_release.py --verify-dir /path/to/downloads
gh release verify web-runtime-v0.1.0-rc.2
gh release verify-asset web-runtime-v0.1.0-rc.2 \
  /path/to/downloads/Godot-MTerrain-web-runtime-v0.1.0-rc.2-web_core.tar.gz
```

The GitHub repository has release immutability enabled. The release workflow
creates a draft, attaches every asset, publishes once both Web and native jobs
are green, then verifies the generated release attestation and every local
asset. Published tags and assets therefore cannot be moved or replaced.

## Project integration

Extract exactly one profile. Copy its `mterrain/` directory and the three
Compatibility material files under `addons/m_terrain/` into the same relative
project paths. An extended consumer also copies
`runtime/web_extended_runtime.gd`. Use a Godot 4.7 Web template with
GDExtension dynamic linking and no threads, then perform a clean import/export
after changing profiles or versions.

These archives are Web runtime inputs, not a complete native editor package.
Keep or build a matching native MTerrain library for editor/native use. Do not
mix a side module, manifest, companion, or export template from different
receipts.

## Roll forward and rollback

Treat a complete profile archive as the atomic unit:

1. Retain the currently accepted archive, release index, and hashes.
2. Verify the candidate before extracting it into a staging project.
3. Replace the whole selected profile, clear only generated import/export state,
   and rebuild with the receipt-matched export template.
4. Require capability, load, height/seam/collision, update, eviction, and
   nonblank-frame smokes before promotion.
5. To roll back, repeat steps 2–4 with the retained prior archive; never copy an
   old wasm file over a newer manifest or companion in place.

`web-runtime-v0.1.0-rc.1` remains the immutable prior-artifact baseline and
`web-runtime-v0.1.0-rc.2` is the first candidate with a standalone runtime
contract. Retain and verify both complete releases. This establishes a real
cross-version artifact rollback pair; a stable claim still requires an actual
candidate-to-prior project restoration followed by the same load, height, seam,
collision, eviction, and nonblank-frame smokes on representative hardware.

## Maintainer publication sequence

1. Merge the release change to `master` only after source-contract and
   distribution workflows are green.
2. Create the annotated release tag on that exact `origin/master` commit and
   push it without force.
3. Let the tag workflow rebuild rather than uploading local binaries.
4. Require the Web artifact and native regression jobs before the draft may
   publish.
5. Verify the release is marked immutable and download/verify every asset.
6. Advance consumers by exact release commit and bundle/index digest.

`web-runtime-v0.1.0-rc.2` is a prerelease. Stable support additionally requires
the headed and physical-device gates in `WEB_SUPPORT_MATRIX.md`.
