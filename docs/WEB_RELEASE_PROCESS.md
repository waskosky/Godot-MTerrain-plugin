# MTerrain Web release process

The Web release lane produces two independently selectable runtime bundles from
one clean source revision. Compiled files remain ignored locally and are
published only as CI review artifacts or immutable GitHub release assets.

Pushes to the maintained `integration/next` review feed run both the source
contract and full clean-clone distribution workflows. They produce
commit-addressed review artifacts but never publish a release. Pushes to
`master` run the same gates; tags and the deliberately restricted stable-version
dispatch remain the only publication paths. A branch-head movement is review
input, not artifact identity: every receipt and downstream consumer still binds
the exact source commit.

## Clean-clone reproduction

The canonical builder is Ubuntu 24.04 x86_64. It resolves every downloaded or
source-built tool through `tools/ci_toolchain.json`, validates those values
against the two Web toolchain contracts, and refuses dirty source trees. The
same contract now pins the Godot source used for the no-thread dynamic-link
export template and the Playwright wheels/browser revisions used by hosted
correctness CI.

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

The browser installer fixes its process umask at `0022` and removes
group/other-write bits from cached browser trees before hashing them. This keeps
the complete content-and-mode digest independent of the caller's shell umask
while retaining executable-mode validation. A different file, link target,
directory layout, executable bit, or remaining permission change still fails
closed, and a mismatch reports both expected and observed values.

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

## Dynamic-link template and hosted browser reproduction

The export template is built from the exact Godot 4.7 stable commit rather than
coming from an unrecorded editor cache. On Ubuntu 24.04 with Python 3.12:

```sh
BROWSER_TOOLS="$(mktemp -d)/mterrain-browser"
./scripts/install_web_ci_toolchain.sh "$BROWSER_TOOLS" browser
source "$BROWSER_TOOLS/environment.sh"
sudo "$PLAYWRIGHT_CLI" install-deps chromium firefox webkit
./scripts/build_web_export_template.sh "$BROWSER_TOOLS"
```

The result is
`build/web-template/godot.web.template_debug.wasm32.nothreads.dlink.zip` and an
`mterrain-web-template-receipt-v1` binding its Godot source tree, Emscripten,
SCons, build arguments, archive members, and digest. The browser installer emits
an `mterrain-browser-toolchain-receipt-v2` with exact wheel inputs, Playwright
browser revisions, launcher digests, and complete installed-tree digests.
Neither compiled template nor browser cache is committed.

The distribution workflow downloads only the already-green native and Web
artifacts, builds that template, exports both profiles, and requires headed
virtual-display Chromium and Firefox passes against real no-thread dynamic-link
exports. It emits one `mterrain-web-hosted-correctness-evidence-v1` aggregate
binding those four reports to the source, debug side modules, template receipt,
browser-toolchain receipt, and headed state. The pinned Playwright WebKit run is
retained separately as a non-blocking diagnostic because its Linux engine emits
framebuffer feedback errors with this Godot Web renderer. It is not Safari
product evidence, and hosted software rendering is not performance evidence.

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
- the versioned performance-budget, provisional calibration template, and
  stable-lane gate contracts inside both bundles and digest-bound by that
  release index;
- the exact traversal script, evidence bridge, scene, and project sources used
  by the candidate-bound performance gate;
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
asset. Published tags and assets therefore cannot be moved or replaced. This
automatic lane accepts only `web-runtime-vX.Y.Z-rc.N` names and fails a
stable-looking tag explicitly; stable publication must first supply the
candidate-bound physical, calibration, and rollback evidence to a reviewed
promotion lane.

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

`web-runtime-v0.1.0-rc.1` is the initial immutable rollback baseline and
`web-runtime-v0.1.0-rc.2` is the first candidate with a standalone runtime
contract. Retain and verify both complete releases. For the next stable
candidate, `tools/web_release_gate.json` names `rc.2` as the required prior
release; the final verifier loads those exact assets and matches their digests.
A stable claim still requires an actual candidate-to-`rc.2` project restoration
followed by the same load, height, seam, collision, eviction, and nonblank-frame
smokes on representative hardware.

Prepare an actual whole-bundle candidate-to-prior session with matching native
editor-load libraries and the receipt-matched template:

```sh
python3 scripts/prepare_web_rollback_gate.py \
  --candidate-dir /verified/candidate-assets \
  --prior-dir /verified/web-runtime-v0.1.0-rc.2-assets \
  --candidate-native-library /matching/candidate/libMTerrain.so \
  --prior-native-library /matching/prior/libMTerrain.so \
  --godot "$GODOT_BIN" \
  --template-debug build/web-template/godot.web.template_debug.wasm32.nothreads.dlink.zip \
  --template-receipt build/receipts/web-template-debug.json \
  --profile web_core

python3 scripts/serve_web_rollback_gate.py \
  --session-dir build/rollback/SESSION_ID \
  --bind 0.0.0.0
```

Open and download the candidate capture first, then restore/open/download the
prior capture on the same named browser/device. Normalize them with
`record_web_rollback_evidence.py`. The recorder rejects mixed sessions,
file-level substitutions, reversed order, changed browser/GPU identity, blank
frames, software renderers, console/page errors, or bundle/context digest drift.
The final gate rechecks the physical origin, operator attestation, ordered
timestamps, session/template digests, renderer class, and candidate bundle/index
binding rather than trusting the recorder's `passed` flag alone. It also requires
`--prior-dir` and independently verifies that immutable prior release before
matching its release-index and profile-bundle digests to every rollback result.
Run a separate `--profile web_extended` session with its matching native
libraries before making an extended-profile stable claim; that baseline also
loads and checks the packaged companion.

## Representative performance and stable gate

`tests/web_performance` runs a fixed 256-stop moving-residency route under an
eight-region visual and one-region collision ceiling. It records startup,
first-tile/collision, frame percentiles, longest frame, recovery, region/memory
maxima, the runtime's exact ten closed per-phase timing counters, and a separate
longest scheduler-step budget. Under `web_extended`, every stop also replaces a
bounded foliage projection, two joined supplied navigation regions, a baked path
with one pre-baked collision shape, and a two-level HLOD projection. That lane
cycles all three foliage tiers, budgets instance/apply work independently,
requires joined path queries and path-collision rays, records companion maxima
and timings, and must recover to zero extended ownership. All fixture assets and
their import metadata are candidate-shipped and capture-bound. Export it with
`--fixture performance` with the exact debug build and template receipts:

```sh
python3 scripts/export_web_smoke.py \
  --fixture performance \
  --profile web_core \
  --godot "$GODOT_BIN" \
  --template-debug build/web-template/godot.web.template_debug.wasm32.nothreads.dlink.zip \
  --template-receipt build/receipts/web-template-debug.json \
  --build-receipt /verified/web_core/receipts/web-template_debug.json \
  --bundle-root /verified/web_core \
  --native-library /matching/native/libMTerrain.so
```

`run_web_performance.py` uses a 360-second harness watchdog so slow software
diagnostics still produce a failing budget report instead of losing their
bounded-state result. The watchdog is not a performance threshold and cannot
turn software-rendered evidence into a passing release lane.

The exported page provides a **Download MTerrain evidence** button so actual
Safari and physical Android/iOS browsers can produce bounded capture JSON
without pretending Playwright WebKit is Safari. Its downloaded context binds
the selected profile, source, side-module/build receipt, template receipt,
candidate-shipped fixture-source hashes, deterministic gzip size of every
production runtime-export file, and threshold contract; normalization rejects a
capture/receipt mismatch, blank or software-rendered frame, or recorded HTTP
failure. Instrumentation files are explicitly excluded from the production
payload total.

Normalize a downloaded capture with `record_web_device_evidence.py`. The
release-lane contract in `tools/web_release_gate.json` requires headed physical
Chrome/Chromium, Firefox, Safari, Android Chrome, and iOS Safari separately.
`tools/web_performance_budgets.json` holds the fixed fixture and thresholds.
`tools/web_performance_calibration.json` is deliberately a provisional template
inside the candidate bundles. Do not edit it to approve a candidate and rebuild:
that would change the source/index identity after the measurements were made.
Instead, after the immutable candidate and passing normalized evidence exist,
create a post-build approval receipt with explicit reviewed inputs:

```sh
python3 scripts/approve_web_performance_calibration.py \
  --candidate-dir /verified/web-runtime-vNEXT-assets \
  --operator "REVIEWER" \
  --evidence build/evidence/web-performance-web_core-headed_chrome_desktop.json \
  --evidence build/evidence/web-performance-web_core-headed_firefox_desktop.json \
  --evidence /path/to/each/additional/profile-and-lane-result.json \
  --output build/evidence/web-performance-calibration-approved.json
```

The approver independently verifies each result against the candidate's exact
source, build receipt, side module, threshold contract, and lane. The resulting
receipt binds the reviewed evidence digests back to the immutable candidate
release-index digest. It is release evidence, not a source input, which prevents
both evidence/budget hash self-reference and a rebuild-after-approval loop.
Audit the current state or fail closed for a stable promotion with:

```sh
python3 scripts/verify_web_release_gate.py
python3 scripts/verify_web_release_gate.py \
  --candidate-dir /verified/web-runtime-vNEXT-assets \
  --prior-dir /verified/web-runtime-v0.1.0-rc.2-assets \
  --candidate-version web-runtime-vNEXT \
  --calibration build/evidence/web-performance-calibration-approved.json \
  --require-stable
```

The second command independently verifies the candidate packages and must stay
red while the verified prior release, matching hosted aggregate, a named hardware
lane, calibration digest, or whole-bundle rollback receipt is absent. It also rejects evidence
whose source, build receipt, side module, release index, bundle, budget, or gate
contract does not match that candidate. It also rejects a calibration approval
that targets another release index or does not list the selected evidence. Core
and extended stable claims are evaluated independently; pass
`--profile web_extended` for the latter.

## Maintainer publication sequence

For a release candidate, merge to `master`, create its annotated `-rc.N` tag,
and let the automatic tag workflow rebuild, publish as a prerelease, and attest
the assets.

For a stable version, the artifact identity must exist before physical evidence:

1. Dispatch `web-runtime-distribution.yml` on `master` with
   `distribution_version=web-runtime-vX.Y.Z`. This builds the final-named
   candidate once, retains its exact packages for 90 days, and produces the
   candidate-bound hosted aggregate; it does not publish.
2. Download that exact distribution and hosted evidence. Run the physical
   performance and candidate-to-verified-`rc.2` rollback lanes without renaming
   or rebuilding any candidate asset.
3. Create the post-build calibration receipt, then require both independent
   profile gates to pass.
4. Assemble and reverify the exact publishable candidate/evidence set:

   ```sh
   python3 scripts/prepare_web_stable_promotion.py \
     --candidate-dir /verified/web-runtime-vX.Y.Z-assets \
     --prior-dir /verified/web-runtime-v0.1.0-rc.2-assets \
     --evidence-dir build/evidence \
     --calibration build/evidence/web-performance-calibration-approved.json

   python3 scripts/prepare_web_stable_promotion.py \
     --verify-dir build/stable-promotion/web-runtime-vX.Y.Z \
     --prior-dir /verified/web-runtime-v0.1.0-rc.2-assets
   ```

5. Review the promotion manifest and checksums, create the stable tag on the
   exact commit named by its candidate release index, and publish the staged
   assets without rebuilding or renaming them. GitHub release attestation and
   immutability remain required.
6. Advance consumers by exact release commit and bundle/index digest.

`web-runtime-v0.1.0-rc.2` is a prerelease. Stable support additionally requires
the headed, calibrated-performance, whole-bundle rollback, and physical-device
gates in `WEB_SUPPORT_MATRIX.md`; the automatic prerelease publisher cannot
bypass that promotion sequence.
