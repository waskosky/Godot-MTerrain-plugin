# MTerrain Web Runtime Roadmap

- Status: active delivery; Milestone 3/4 implementations and the first bounded
  `web_extended` projections locally verified on 2026-08-24; clean-clone Web
  builds, native regressions, split distribution bundles, and immutable
  prerelease automation added for `web-runtime-v0.1.0-rc.1` and a
  machine-readable, release-bound runtime contract prepared for
  `web-runtime-v0.1.0-rc.2` on 2026-08-25; phase timing, LOD/recreate/seam
  fixtures, a pinned source-built export template, hosted-browser workflow,
  fixed traversal capture, candidate-bound external-evidence verifier, hosted
  evidence aggregation, and independent core/extended whole-bundle rollback
  harnesses implemented locally on 2026-08-30; tiered foliage ceilings,
  joined-region navigation/profile validation, opt-in pre-baked path collision,
  bounded HLOD cross-fades, and a 256-stop extended moving-residency fixture
  implemented and locally verified on 2026-08-31; both required clean-clone
  workflows now run on the maintained `integration/next` review feed as well as
  `master`; the first feed run passed clean Web builds and native regressions,
  then exposed caller-umask drift in the browser-tree permission digest before
  browser export; canonical `0022` installation modes and diagnostic mismatch
  values are implemented for the rerun; representative hardware, calibration,
  physical-mobile, and actual rollback evidence remain open
- Primary target: Godot 4.7 stable, wasm32, Compatibility renderer, WebGL2,
  single-threaded GDExtension
- Secondary target: explicitly hosted threaded Web diagnostics
- Native target: preserve existing editor and runtime capabilities

## 1. Purpose

This roadmap turns MTerrain into a reproducible, bounded, independently usable
terrain runtime for browser exports while preserving its native authoring and
runtime strengths. It describes repository-local build, runtime, rendering,
physics, data, validation, and release work. It intentionally does not assume a
particular game architecture or external service.

The desired result is not “every editor feature runs in a browser.” The desired
result is a small, reliable Web runtime whose capabilities can be selected and
measured independently:

- heightfield rendering;
- camera-relative visual LOD;
- bounded height-tile updates;
- near-focus heightfield collision;
- constrained Compatibility materials;
- later, separately gated foliage, mesh HLOD, navigation, and paths.

The implemented method signatures, bounds, ownership rules, and error semantics
are maintained in `WEB_RUNTIME_API.md`; this document owns sequencing, decisions,
evidence, and release gates.

The Web runtime must remain optional. A project that never exports to Web should
retain the normal native MTerrain workflow and should not pay for Web-specific
fallbacks in its hot path.

## 2. Implemented baseline and remaining gaps

The source retains these useful foundations:

- a Compatibility-specific `start_opengl.gdshader` using vertex texture fetches;
- RenderingServer-based terrain, mesh, and MultiMesh realization;
- R32F height storage and RGB8 normal storage;
- height-map PhysicsServer collision;
- camera-relative terrain and object LOD;
- an MIT-licensed C++ GDExtension with a pinned `godot-cpp` submodule.

The implemented local release-candidate slice now includes:

- `full`, `runtime`, `web_core`, and `web_extended` source profiles exist. Web
  accepts only single-precision, no-thread core/extended profiles. Their shared
  C++ closure excludes editor, octree-object, native grass, navigation, path,
  mesh-HLOD, and decal sources; the extended features are a separately packaged,
  data-first runtime companion rather than the native authoring implementations.
- Godot 4.7 stable, its exact GDExtension API, `godot-cpp`, Emscripten, emsdk,
  Binaryen, SCons, and Brotli are pinned in `tools/web_toolchain.json` and
  `tools/web_extended_toolchain.json`.
- Debug and release wasm32 no-thread manifest entries, a trimmed binding profile,
  deterministic build script, artifact receipt writer, and target-separated
  MTerrain object and `godot-cpp` variant directories are checked in. Plugin
  objects wait for their target-width-specific binding library, preventing
  native/Web header races without forcing every invocation to regenerate it.
- A pinned, least-privilege source-contract workflow checks standalone
  governance, profile/manifest invariants, and Python/shell parsing. A separate
  clean-clone distribution workflow resolves digest/commit-pinned Linux host
  tools, compiles both Web profiles in debug/release, runs full/core/extended
  native regressions, packages and reverifies split bundles, retains review
  artifacts, and publishes only a fully assembled immutable tagged prerelease.
  Pull requests and pushes to `master` or the maintained `integration/next`
  review feed run both workflows, so the no-PR integration lane cannot bypass
  clean-clone evidence.
  Native builds still compile every full-profile MTerrain source while an
  explicit engine-class build profile bounds generated `godot-cpp` wrappers;
  this avoids host archive command-line limits without reducing the native
  MTerrain class registry.
- Web compiler inputs map checkout paths to `/mterrain`; build receipt and
  archive timestamps use the source commit epoch. Each release publishes an
  index binding source, profile, raw/Brotli artifact digests, companion digest,
  and bundle digests plus `SHA256SUMS`. This establishes a controlled clean-clone
  procedure without claiming cross-kernel byte identity that has not been
  separately measured.
- `runtime/web_runtime_contract.json` is the machine-readable release boundary
  for target, profile inheritance, public methods, API/state versions, formats,
  limits, required capabilities, and unsupported behavior. A repository-local
  verifier rejects drift against the C++ bindings, capability dictionary,
  scheduler/material bounds, toolchains, and extended companion. Both bundles
  and a standalone release asset carry identical contract bytes bound by the
  release index and `SHA256SUMS`.
- Core thread/future launch sites have explicit synchronous Web branches. The
  automatic legacy terrain and physics loops default off because runtime API v2
  owns bounded scheduling and collision residency.
- Runtime bridge API v2 reports immutable capabilities and exposes bounded
  queue/step/cancel/result/release operations. Work has stable keys, monotonic
  revisions, priority, staged input, incremental preflight/write/normal phases,
  per-region texture installation, sample- and region-budgeted rollback after
  partial writes/uploads, deterministic LRU eviction, bounded managed-region
  accounting without whole-grid scans, resident-region/estimated-byte ceilings,
  and closed-cardinality timing/count metrics. Ten fixed timing categories now
  report per-step deltas plus cumulative/longest/invocation totals, and the
  latest visual update reports a bounded LOD histogram/range, transition count,
  adjacent-level delta, camera, and terrain offset. The immediate API remains an
  idle-queue compatibility wrapper over that scheduler.
- Bounded profiles load no implicit camera region during grid creation. Scheduler
  load/unload is the sole visual-region owner, unloaded regions release their
  mesh instances immediately, and the visual search can follow scheduler-loaded
  regions beyond the creation camera. Topology fails before allocation above 256
  quads per axis, 65,536 points, or 1,024 regions; visual range is capped at 128
  quads.
- `runtime_memory_only` is mandatory in `web_core`; it cannot be disabled, and
  explicit save, editor directory creation, destructive layer-file operations,
  and eviction-time legacy saves fail closed. Packed read-only resources may
  still be loaded.
- The complete native debug/editor source profile compiles and links against the
  same Godot 4.7 API after replacing the removed `godot-cpp` VMap dependency with
  a small repository-owned sorted-vector map.
- Native and real dynamic-link Web fixtures create a four-region memory-only
  terrain; test cancellation rollback and revision coalescing; independently
  apply adjacent 67-by-67 plane tiles with an exact shared height border and
  continuous normals; raycast collision on both sides of the region/tile seam;
  exercise bounded texture-array/splat material configuration; release all RIDs
  and buffers; and perform a deterministic three-stop teleport under a two-tile,
  two-region LRU ceiling. The current fixtures additionally reject a mismatched
  shared edge before mutation, cycle deterministic near/far LOD promotion and
  demotion, reach maximum LOD, validate adjacent-level deltas, and destroy then
  recreate terrain at a negative world offset. Exercising the maximum exposed a
  shared native/Web edge-stitch gap; all 16 left/right/top/bottom combinations
  are now generated rather than silently using the main mesh for a three-edge
  case.
- A 256-stop, four-pass snake traversal fixture maintains eight visual regions
  and one near-focus collision region, emits fixed scheduler/LOD/memory maxima,
  and can download sanitized browser captures from real product browsers. Each
  export embeds a context binding its profile, build receipt, side module,
  source-built template receipt, exact traversal/bridge/project source hashes,
  deterministic per-file gzip size for the complete production runtime export,
  and threshold contract; the physical-evidence recorder rejects any mismatch.
  Those fixture sources also ship inside the candidate bundle, allowing the
  stable verifier to compare them to the measured context. The extended form
  moves bounded foliage, two adjacent navigation regions, a baked path with one
  supplied collision shape, and a two-level HLOD projection at every stop. It
  cycles low/medium/high foliage ceilings, limits ownership to 1/2/1/1, issues
  joined navigation queries and collision rays once per route, advances HLOD
  fades under a separate apply budget, and requires zero final ownership. The
  same fixture and budgets apply independently to core and extended profiles and
  record the selected profile.
  `web_performance_budgets.json` contains deliberately provisional desktop and
  mobile thresholds. Bundles retain a provisional
  `web_performance_calibration.json` template. After the immutable candidate and
  physical evidence exist, `approve_web_performance_calibration.py` emits a
  separate receipt binding reviewed evidence-file digests to that candidate's
  release-index digest. This avoids both a self-referential evidence/budget hash
  and an impossible rebuild-after-approval loop; the release verifier cannot
  accept the thresholds until that post-build receipt is supplied.
- Godot 4.7's exact source commit and Playwright 1.62.0 wheel/browser inputs are
  pinned, including full Linux installation-tree digests rather than
  launcher-only hashes. Browser installation uses a fixed `0022` umask and
  removes group/other-write bits before hashing, preserving executable-mode
  coverage without making the receipt depend on a developer shell's umask. A
  repository builder emits immutable template/browser receipts. Hosted CI now
  builds the no-thread dlink template before exporting
  and probing both profiles in headed Chromium and Firefox under a virtual
  display. A checked aggregator binds those four nonblank/error-free smokes and
  their headed state to the exact source, debug side modules, template receipt,
  and browser-toolchain receipt; the stable verifier requires that aggregate
  from the verified candidate. Pinned Playwright WebKit is retained as a
  non-blocking diagnostic: its current Linux engine reaches the fixture marker
  and nonblank frame but emits framebuffer feedback errors. Actual Safari is a
  separate physical gate. The first upstream hosted run is still required
  evidence; configuration alone is not a pass or hardware-performance evidence.
- The rollback harness independently verifies and safely extracts complete
  candidate/prior archives, binds their manifest/material/side-module/native and
  template hashes into one ordered session, exports a cross-candidate API v2
  baseline, and records only candidate-then-prior captures from the same named
  physical browser/GPU. Core and extended sessions are independent; the extended
  baseline also loads its packaged companion and checks its capability contract.
  The stable verifier independently requires the physical origin, operator,
  ordered timestamps, session-manifest digest, template digests, and a
  non-software renderer in every normalized result. It also verifies the named
  immutable prior release directory and matches its release-index/profile-bundle
  digests, instead of accepting a claimed prior version string. No actual
  representative rollback receipt has yet been produced. The bounded rollback
  fixture itself is locally green in headed Chromium 151 and Firefox 153 for
  both profiles; that proves the harness path, not cross-version restoration on
  representative hardware.
- Playwright Chromium and Firefox load both profiles with WebGL2, wasm32, no
  threads, the expected API v2 capability tuple, a nonblank directly captured
  framebuffer, and no console, page, request, or HTTP errors. The extended
  fixture additionally stages and releases bounded foliage, precomputed
  navigation, baked paths, and mesh-only HLOD. WebKit currently reaches the same
  marker and nonblank framebuffer but fails the strict error gate as described
  above. These are automated correctness checks, not headed-hardware or
  physical-device support claims.
- On 2026-08-31 the expanded extended fixture completed all 256 stops under
  local software-rendered Chromium: 1,280 projection installs, 32,768 foliage
  writes, 256 pre-baked path-collision installs, 256 HLOD swaps over 1,024 fade
  steps, four joined navigation queries, four collision rays, and zero final
  ownership. The companion's observed longest step was 10.8 ms. The run failed
  the provisional hardware frame/startup thresholds, as a software-rendered run
  should; it is bounded-correctness diagnostic evidence, not a calibrated lane.
- Binaryen inspection records the artifact feature set and rejects thread or
  shared-memory requirements. In the `rc.2` local reference build, core
  debug/release side modules are 931,933/904,382 raw bytes and
  139,334/138,809 bytes at Brotli quality 11; extended side modules are
  932,239/904,704 raw and 139,576/138,913 compressed. The current production
  debug export totaled 11,691,852 deterministic-gzip bytes for core and
  11,716,450 for extended, excluding evidence instrumentation. The extended
  profile packaged a separately hashed 33,220-byte companion script. The
  2026-08-31 companion and fixture additions intentionally supersede those local
  size observations; the next clean build receipts and release index are
  authoritative.

The remaining gaps are deliberately material:

1. The fixed long traversal and closed measurements now exist, but their
   provisional budgets need p50/p95/p99 frame time, worst-stall, heap/RID, and
   steady-state recovery calibration on every named representative lane.
2. Per-phase runtime timing and the missing LOD/offset/border/recreate fixtures
   are locally green. They still need the pinned Web builds and newly added
   hosted workflow to pass from a clean upstream checkout.
3. Hosted browser export and aggregate verification are implemented with a
   source-built, receipt-bound dynamic-link template. The first upstream headed
   Chromium/Firefox run remains open evidence and, even when green, is
   correctness rather than hardware performance or Safari-product evidence.
   Playwright WebKit remains a pinned diagnostic until its Godot/WebGL errors
   are fixed; it is not allowed to stand in for Safari.
4. Ordered core and extended whole-bundle rollback paths now exist, but each
   stable profile claim still needs candidate-to-`web-runtime-v0.1.0-rc.2`
   captures on every required physical browser lane. The verifier binds evidence
   to a verified candidate release index/bundle and correctly reports all such
   receipts absent today.
5. Headed Chrome, Firefox, and Safari plus physical Android- and iOS-class device
   evidence remain mandatory before a browser release claim. Budgets cannot be
   promoted from provisional until their exact evidence digests are reviewed.
6. Foliage, mesh HLOD, navigation, and paths have bounded data-first projection
   implementations plus exported-resource, moving-revision, and 256-stop
   residency fixtures. Navigation crosses supplied region joins with validated
   agent profiles; HLOD has hysteresis and bounded cross-fades; paths may install
   one explicitly supplied pre-baked collision shape; foliage has immutable
   quality-tier ceilings. Each still needs representative production content,
   calibrated memory/frame-time, and physical-device evidence. Foliage
   collision, runtime navigation baking, runtime mesh/curve deformation, and
   generated path collision remain explicitly unsupported.

These are engineering gaps, not evidence that bounded heightfield terrain cannot
work on WebGL2.

## 3. Accepted long-term decisions

### 3.1 Primary Web profile

The release-bearing Web profile is single-threaded wasm32 with GDExtension
support. This maximizes browser and hosting compatibility and gives the runtime
one deterministic place to enforce frame budgets.

A threaded build may be maintained for comparison. It requires cross-origin
isolation and a pre-sized Emscripten thread pool. It cannot become the only
supported Web path, and performance wins must include startup, download, memory,
deadlock, and mobile-browser evidence.

### 3.2 Renderer

Web uses Godot's Compatibility renderer over WebGL2. The runtime must not use
RenderingDevice or compute work. Forward+/Mobile-only objects are excluded or
replaced by explicit Compatibility projections.

### 3.3 Capability profiles

The native default remains feature-complete. Exported builds use source profiles
instead of linking every subsystem:

| Profile | Purpose | Initial capabilities |
|---|---|---|
| `full` | Native editor/runtime compatibility | Existing terrain, grass, navigation, octree, paths, HLOD, editor helpers where applicable |
| `runtime` | Native exported runtime | Runtime capabilities without editor-only C++ |
| `web_core` | First release-bearing browser runtime | Terrain height/visual LOD, API v2 scheduler/residency, bounded near-focus collision, and constrained Compatibility materials |
| `web_extended` | Opt-in browser runtime | The same native core plus separately selectable data-first foliage, precomputed navigation, baked-path, and mesh-HLOD projections |

The profile separation and fail-closed behavior are architectural requirements.
Both Web profiles deliberately share one trimmed native binding closure; the
extended companion is independently packaged and hashed so projects that need
only terrain do not import it.

### 3.4 Scheduling

Single-threaded Web work is expressed as explicit state machines. A work item has
a stable key, input revision, priority, operation-budgeted `step()` method,
cancellation, staged result, and main-thread `apply()` phase. A newer revision
invalidates an older staged result before installation.

The first implementation may reuse existing data structures, but it may not hide
unbounded synchronous work behind a method named “async.” No frame callback may
load an arbitrary set of regions, regenerate an arbitrary normal field, upload an
arbitrary number of textures, or rebuild an arbitrary number of collision shapes.

### 3.5 Runtime data

The Web runtime supports two input classes:

- packed, read-only imported resources included with the export;
- validated bounded memory buffers supplied at runtime.

Project resource mutation is editor-only. Runtime writes to `res://` are rejected
before mutation. Optional `user://` caching is versioned, bounded, checksummed,
recoverable, and disposable. It must never be required to reconstruct the
terrain supplied to the runtime.

### 3.6 Height transport inside the API

The first batch API accepts a row-major `PackedFloat32Array` of metre heights
because MTerrain's internal height images are R32F. The API validates dimensions,
sample count, coordinates, finite values, configured grid bounds, and a maximum
tile area before touching terrain state.

The public contract is versioned separately from C++ class layout. Runtime API
v2 methods are:

```text
get_runtime_bridge_api_version() -> int
get_runtime_capabilities() -> Dictionary
configure_runtime_limits(limits: Dictionary) -> Dictionary
queue_height_tile(
    work_key: String,
    revision: int,
    priority: int,
    start_x: int,
    start_y: int,
    width: int,
    height: int,
    heights_m: PackedFloat32Array,
    update_collision: bool
) -> Dictionary
step_runtime_work(max_sample_ops: int, max_region_ops: int) -> Dictionary
cancel_runtime_work(work_key: String, revision: int) -> Dictionary
take_runtime_work_result(work_key: String, revision: int) -> Dictionary
apply_height_tile(
    start_x: int,
    start_y: int,
    width: int,
    height: int,
    heights_m: PackedFloat32Array,
    update_collision: bool
) -> Dictionary
release_height_tile(
    start_x: int,
    start_y: int,
    width: int,
    height: int
) -> Dictionary
release_runtime_tile(work_key: String, revision: int) -> Dictionary
request_runtime_collision_focus(
    focus_x: int,
    focus_y: int,
    radius_regions: int,
    max_regions: int,
    revision: int
) -> Dictionary
get_runtime_state() -> Dictionary
configure_runtime_material(configuration: Dictionary) -> Dictionary
```

`queue_height_tile()` plus bounded `step_runtime_work()` is atomic at visible
installation; `apply_height_tile()` drains that same state machine as a bounded-
input compatibility call:

1. Validate all parameters and calculate affected regions.
2. Stage or copy the bounded input so caller mutation cannot race installation.
3. Write samples through a bulk internal path that preserves shared border pixels.
4. Regenerate normals for the tile plus a one-sample halo, clamped to the grid.
5. Upload affected dirty region images one region-budgeted operation at a time.
6. Admit or refresh only requested collision regions under their independent
   ceiling; a zero-region focus request releases collision residency.
7. Return written sample count, affected pixel/region bounds, normal bounds,
   collision disposition, and an error code with no terrain payload.

The initial maximum is one 67-by-67 sample tile (4,489 samples). Larger requests
must be tiled by the caller or admitted through a future explicitly budgeted API.

### 3.7 Height texture format

R32F with nearest sampling is the first Web implementation because it matches
existing storage and preserves height values without a shader decode. Acceptance
requires Chrome, Firefox, Safari, Android-class, and iOS-class evidence.

An RGBA8 encoded-height backend remains a contingency for driver correctness,
download, or texture-memory evidence. It should not be added preemptively: two
formats double shader and validation combinations. If introduced, the encoding,
range, precision, and decode math become a versioned contract with exact fixtures.

### 3.8 Feature ownership inside the plugin

- Terrain height and visual LOD are the first Web capability.
- Collision is independently admitted near a focus and can lag far visual LOD.
- Material roles are independent from stored height data.
- Grass, mesh HLOD, navigation, and paths consume terrain but are not required for
  terrain height to load.
- Holes require a separately validated representation. NaN height samples are not
  accepted by the first batch API.
- Caves, bridges, tunnels, and overhangs remain ordinary mesh/volume geometry,
  not special heightfield states.

### 3.9 Extended authored-data boundary

The first extended runtime accepts authored/exported resources and realizes them
under explicit ownership budgets; it does not move authoring algorithms into a
browser frame callback. Foliage quality tiers are immutable ceilings, supplied
navigation retains its agent profile and may join adjacent regions, and HLOD may
cross-fade through a bounded apply-step count. Paths may opt into one validated,
allowlisted pre-baked primitive/convex/concave shape per projection. That opt-in
does not imply curve deformation, terrain cutting, seam generation, or runtime
collision generation. Those remain separately gated designs.

## 4. Build and packaging design

### 4.1 Toolchain tuple

Every Web artifact receipt records:

- MTerrain commit;
- source tree identity, so a content-identical merge commit can be recognized;
- `godot-cpp` commit;
- Godot version and source/template commit;
- GDExtension API version;
- Emscripten version;
- wasm architecture and pointer width;
- `target`, `precision`, optimization, debug-symbol, and thread values;
- runtime profile and enabled capabilities;
- output byte size and SHA-256.
- Binaryen version and the exact required WebAssembly feature set.

An artifact is reusable only when the complete tuple and output digest match.

### 4.2 SCons behavior

`gdextension/SConstruct` now owns validated `full`, `runtime`, `web_core`, and
`web_extended` source profiles. The following requirements remain normative:

- Web build scripts select `platform=web` and `arch=wasm32` explicitly.
- Web release and debug builds are produced explicitly with `threads=no`.
- A threaded artifact, if added later, has a different suffix and receipt.
- Editor-only source is selected by an editor capability, not merely because the
  target contains debug symbols.
- Invalid combinations stop before plugin compilation. Web builds reject every
  profile except `web_core`/`web_extended`; both reject `threads=yes` and double
  precision.
- Output filenames retain the complete `godot-cpp` suffix.
- Build and smoke scripts use deterministic staging without requiring users to
  rename their repository checkout manually.

### 4.3 Manifest entries

The generated/installed GDExtension manifest must select exact thread variants,
conceptually:

```ini
web.debug.wasm32 = "...web.template_debug.wasm32.nothreads.wasm"
web.release.wasm32 = "...web.template_release.wasm32.nothreads.wasm"
web.debug.threads.wasm32 = "...web.template_debug.wasm32.wasm"
web.release.threads.wasm32 = "...web.template_release.wasm32.wasm"
```

Only entries with built, verified libraries should ship. Export validation checks
that the selected library is present and that its thread mode matches the export
template. Switching thread mode without a clean import/export is tested because
stale side-module selection can otherwise produce WebAssembly link failures.

### 4.4 Binary-size control

The `web_core` and `web_extended` native artifacts exclude editor, grass,
navigation, path, HLOD, decal, and general object-octree sources unless the
terrain core has an actual compile-time dependency. They share the same trimmed
binding-generation profile. Extended behavior is data-first and present only
when packaging explicitly selects `web_extended`.

Each milestone records raw and Brotli-compressed side-module bytes plus incremental
page startup delay. A feature with no Web consumer does not enter the Web binary.

## 5. Runtime design

### 5.1 Initialization and capability reporting

Loading the extension registers only classes present in the selected profile.
The runtime exposes one immutable capability dictionary containing:

- API version;
- build profile;
- thread mode;
- supported height formats;
- maximum batch dimensions and samples;
- terrain, collision, material, foliage, HLOD, navigation, and path booleans;
- runtime-write policy;
- build receipt digest when supplied by packaging.

Callers can reject an unsuitable artifact before creating terrain. Missing
capabilities never silently pretend to succeed.

### 5.2 Terrain creation

Web terrain creation separates configuration from activation:

1. Validate grid dimensions, region divisibility, horizontal scale, material,
   resource mode, and memory ceilings.
2. Allocate only fixed topology/configuration structures.
3. Admit initial regions through bounded work.
4. Install visible meshes only after required height/normal textures are ready.
5. Install collision only after its independent request completes.

Warnings about an absent optional save configuration are removed from memory-fed
mode. Creating a runtime terrain cannot create directories or save resources.

### 5.3 Region work state machine

The existing terrain update sequence is decomposed into resumable work:

- calculate desired LOD/region bounds;
- diff desired and resident region sets;
- load or stage a bounded number of region payloads;
- correct shared edges;
- generate a bounded normal range;
- prepare mesh/texture changes;
- apply RenderingServer changes;
- prepare collision data;
- apply PhysicsServer changes;
- retire stale regions and release RIDs.

No more than one apply phase mutates a particular region at a time. Cancellation
before apply releases staged memory. Cancellation during a multi-step update keeps
the last complete visible/collision state until the replacement is ready.

### 5.4 LOD and seams

The terrain LOD contract requires:

- deterministic camera-to-LOD selection with hysteresis;
- shared border sample identity across adjacent regions;
- crack prevention through the existing topology/skirt strategy or a measured
  replacement;
- normals generated from a halo so lighting is continuous at equal-detail seams;
- stable custom AABBs covering displacement extrema;
- no simultaneous proxy/full surfaces for the same patch unless intentional
  cross-fade cost has been measured.

Tests cover equal LOD, one-level transitions, maximum allowed transition, world
edges, negative offsets, repeated promotion/demotion, and teleport replacement.

### 5.5 Collision

Web collision is a separately budgeted near-focus capability:

- one bounded height-map shape per admitted collision region;
- creation/update/removal on the main thread;
- exact sample lattice alignment with the visual surface;
- explicit readiness and generation counters;
- no per-frame rebuild;
- configurable region and memory ceilings;
- stale collision never survives after its owning terrain revision is replaced.

The first gate uses built-in Godot physics. Additional physics implementations are
validated independently with the same lattice and traversal fixtures.

### 5.6 Materials

The minimum Compatibility material provides readable base albedo, sampled height,
and normal use. It does not require lights, shadows, emission, or optional texture
assets to distinguish the surface.

Material milestones then add:

1. slope/height semantic tint;
2. a small texture-array palette;
3. bounded index/splat blending;
4. optional macro variation with no additional per-tile draw call;
5. quality-profile controls for texture samples, filtering, and shadows.

The initial Web limit is at most 16 texture-array layers and four terrain samples
per fragment. A larger array may be technically accepted by WebGL2 but requires a
new memory/startup/shader gate; the existing 256-index helper is not a release
budget by itself.

### 5.7 Eviction and recovery

Every runtime-owned RID, image buffer, staged work item, collision shape, and
region reference has an explicit release owner. Eviction is deterministic from
stable region keys and budgets, not garbage-collector timing.

Recovery tests repeatedly:

- enter and leave a region;
- cancel while loading and while preparing normals;
- teleport beyond the current resident set;
- replace a tile revision;
- destroy and recreate the terrain node;
- reload the browser page;
- reject malformed or oversized input.

Resident counts and estimated bytes must return to the configured steady-state
ceiling without reloading the page.

## 6. Later capability plans

### 6.1 Grass and foliage

The first foliage implementation uses RenderingServer MultiMesh instances already
present in MTerrain. Web requirements:

- deterministic prevalidated transforms or deterministic bounded generation;
- density and visible-instance ceilings by quality profile;
- mesh/material allowlist supplied by the project export;
- no required shadows or dynamic GI;
- separate visual and collision residency;
- no threaded generation in the single-thread profile;
- bounded buffer upload and deterministic release.

Grass collision is deferred until visual foliage meets frame and memory budgets.

Implementation status: `MTerrainWebExtendedRuntime.queue_foliage()` validates a
project-exported allowlisted mesh/material (or explicitly enabled in-memory test
resource), finite transforms, mesh size, and an instance ceiling. It stages
MultiMesh transforms under an instance-operation budget and retains the previous
complete projection until atomic installation. Revision coalescing/cancellation,
installed-key reservation, deterministic release, exported crossed-blade grass,
and moving-revision fixtures are present. Low/medium/high profiles now enforce
fixed instance and per-square-metre ceilings, and the 256-stop fixture cycles all
three under a separate 64-write step budget. Representative production art,
calibrated frame/memory budgets, physical-device shadows-off evidence, and all
foliage collision work remain open.

### 6.2 Mesh HLOD

Mesh-only HLOD may enter `web_extended` after terrain and foliage. Decal items,
dynamic GI assumptions, arbitrary lights, and threaded resource pipelines are
excluded initially. Packed mesh resources are prevalidated, loads are bounded,
and LOD swaps retain the last complete level until the replacement is ready.

Implementation status: the companion accepts one to four prevalidated mesh
levels with strictly increasing finite distances and changes at most one level
per apply operation. It excludes decals, lights, GI, threaded loads, and arbitrary
resource paths. Index as well as vertex counts are bounded, installed ownership
fails closed, and configurable distance hysteresis prevents threshold thrash.
Optional 0–16-step cross-fades retain active/incoming ownership and consume one
apply operation per start, step, or cancellation. Exported near/far rock,
moving-revision, and 256-stop four-step fixtures are present. Representative
memory/frame-time and physical-device gates remain open.

### 6.3 Navigation

Navigation is independent of rendering. The Web path uses bounded precomputed or
incrementally supplied navigation data near active agents. Runtime baking is not
performed in an unbounded frame callback, and no `std::async` path exists in the
single-thread artifact.

Acceptance includes region joins, agent radius/slope fixtures, moving residency,
unload/reload, and a frame-time budget during navigation updates.

Implementation status: the companion installs bounded, already baked
`NavigationMesh` resources only. It validates finite vertices, polygon and total
index counts, index bounds, resource scope, revision, and transform, and owns
deterministic replacement/release. Runtime baking remains false in the capability
contract. A real NavigationServer path-query fixture and exported navigation
resource/moving-revision fixture are present. Agent radius, height, and slope
are validated and reported; native/exported fixtures cross two adjacent regions,
and the 256-stop route repeats joined queries under moving ownership. Production
navigation complexity, calibrated performance, and physical-device gates remain
open.

### 6.4 Paths

Authoring and mesh baking remain native-editor strengths. The first browser path
capability loads or receives already validated curve/mesh data and realizes it
without editor controls. Runtime curve deformation is considered only after it
has resumable bounded work and seam/collision fixtures.

Implementation status: the companion realizes only pre-baked bounded `Mesh`
resources with a finite transform and optional allowlisted material. Authoring,
Bezier deformation, road/river collision generation, and seam creation are not
part of the browser runtime. An exported road strip, allowlisted material, and
moving-revision fixture are present. Terrain-seam conformance, generated
collision, and runtime deformation are not implied. One opt-in allowlisted
pre-baked box/capsule/cylinder/convex/concave shape is bounded by projection,
point, extent, layer, and mask limits; smoke and 256-stop fixtures require
physics rays and zero final ownership. Production road complexity, calibrated
performance, and physical-device gates remain open.

## 7. Testing strategy

### 7.1 Deterministic fixtures

Keep fixtures small and generated from code where possible:

- flat 17-by-17 and 67-by-67 tiles;
- signed hills/valleys including negative heights;
- adjacent tiles sharing exact borders;
- a deliberate border mismatch that must fail;
- malformed dimensions/sample counts;
- NaN/infinity rejection;
- out-of-grid placement;
- repeated revision update;
- LOD transition and teleport route;
- collision lattice traversal.

Fixtures have stable hashes and no large texture or terrain binaries.

### 7.2 Static and compile checks

Web CI verifies:

- no editor sources in runtime artifacts;
- no banned thread APIs in the single-thread source closure;
- all requested manifest libraries exist;
- library suffixes match target/thread/precision;
- no unresolved wasm imports;
- the minimal OpenGL shader imports under Compatibility;
- build receipts match outputs;
- source-built export-template and browser receipts match their pinned inputs;
- both profiles export and pass hosted headed Chromium/Firefox correctness;
- the four required hosted reports aggregate against the candidate source, side modules,
  template receipt, and browser-toolchain receipt;
- pinned Playwright WebKit diagnostics are retained without being accepted as
  Safari evidence or blocking the real Safari lane;
- native build outputs and class registration remain intact.

### 7.3 Browser correctness smoke

The automated browser fixture must:

1. load the wasm extension;
2. report the expected capability/profile tuple;
3. create a bounded terrain;
4. apply at least two adjacent height tiles through the batch API;
5. render a nonblank frame with expected terrain pixels;
6. traverse their shared seam with collision enabled;
7. update one tile and reject one malformed tile;
8. evict/reload terrain;
9. finish without console, WebGL, GDExtension, or uncaught promise errors.

Screenshots are inspected, not merely captured. A blank frame with a successful
process exit is a failure.

### 7.4 Performance fixture

The fixed traversal reports:

- complete production runtime-export raw/deterministic-gzip bytes plus the
  plug-in side-module size;
- page startup and extension-link time;
- first terrain and first collision time;
- p50/p95/p99 frame time and worst main-thread stall;
- exact ten-category terrain step/apply timing plus a longest-step budget;
- resident region, RID, collision, texture, and estimated heap counts;
- tile update and normal generation time;
- teleport recovery and steady-state eviction time;
- renderer, browser, OS, hardware, viewport, and exact source tuple.

Budgets are established from representative devices, stored in a versioned
threshold contract, and never weakened solely to make a regression pass. The
fixed fixture, capture bridge, provisional configuration, product-browser
recorder, post-build calibration-approval receipt, and fail-closed lane verifier
are implemented. The bundled template keeps `release_gate_eligible=false`.
After physical receipts calibrate the thresholds, approval is emitted outside
the candidate and points back to its immutable release-index digest. Stable
verification requires both that receipt and the fully verified candidate, so
evidence cannot float independently from the indexed bundle and approval never
requires rebuilding the artifact it approves.

## 8. Delivery milestones and gates

### Milestone 0 — Repository contract — complete 2026-08-24

- Repository guidance and this roadmap are reviewed and on the default branch.
- Toolchain and source-profile decisions are explicit.
- No runtime claim is made.

### Milestone 1 — Reproducible Web compile/load — locally verified 2026-08-24

- Pinned Godot 4.7/`godot-cpp`/Emscripten tuple.
- `web_core` debug and release wasm32 no-thread libraries.
- Exact GDExtension manifest entries.
- Native host builds still compile.
- Browser loads the extension and returns a capability dictionary.
- Artifact receipt and binary-size report exist.

The local gate is green for debug/release Web compilation, full native
debug/release compilation, native core/extended loading, export, and current
headed Chromium/Firefox load and framebuffer probes. Playwright WebKit reaches
the marker and nonblank probe but fails on WebGL feedback errors. The
release-candidate lane now reproduces both Web profiles
from a clean checkout, adds native release compilation and regression smokes,
and publishes only CI-produced, receipt-bound immutable assets. Representative
browser performance remains a higher support gate.

### Milestone 2 — Batch height projection — implementation locally verified 2026-08-24

- Versioned batch API with strict bounds and finite-value validation.
- Memory-fed/no-save runtime mode.
- Adjacent 67-by-67 tiles render with shared borders and continuous normals.
- Invalid input cannot partially mutate terrain.
- Each dirty height/normal image uploads once per affected region and committed
  update.

API v2, memory-only policy, bounded validation, shared-border and normal-source
preflight, normal halo calculation, and coalesced dirty upload are implemented.
Native and current Chromium/Firefox fixtures initialize four RAM-backed regions,
apply two independent 67-by-67 tiles, inspect their exact shared height border
and neighboring normals, render the raised heightfield, prove a non-finite
replacement cannot partially mutate it, and bound upload counts to the two dirty
runtime images per affected region. A mismatched one-sample shared edge now fails
before mutation; the matching edge then installs and retains continuous normals.

### Milestone 3 — Bounded single-thread residency — implementation locally verified 2026-08-24

- Terrain update work is resumable, cancellable, coalesced, and revision-safe.
- Teleport and long traversal remain within configured time/memory ceilings.
- Deterministic eviction releases RIDs and buffers.
- No forced thread API remains in the `web_core` closure.

The API v2 state machine is resumable by sample/region budgets, stages caller
data, exposes phase progress, rolls back cancellation after partial height writes,
coalesces newer revisions, marks regenerated normals dirty, and restores texture
state under the region budget if cancellation follows a partial upload.
Stable-key LRU eviction detaches rendering materials, removes collision, unloads
images/buffers, and returns a three-stop teleport fixture to its two-region then
zero-region ceilings. Native core/extended and automated Chromium/Firefox checks
are green; WebKit remains diagnostic. The milestone is not release-complete until a longer traversal
passes representative headed/mobile frame, stall, RID, and heap budgets. That
fixed traversal and its receipts now exist, while all representative lanes and
budget calibration remain open.

### Milestone 4 — Collision/material candidate — implementation locally verified; release gate open

- Near-focus collision has readiness and exact visual alignment evidence.
- Seam traversal passes across LOD and tile boundaries.
- Minimal and texture-enhanced Compatibility materials pass missing-texture and
  unshaded readability tests.
- Chrome, Firefox, Safari, Android-class, and iOS-class evidence is green.

Near-focus collision has independent region/revision ceilings, automatic bounded
admission for compatibility `update_collision=true`, explicit focus movement,
zero-region release, readiness state, generation accounting, and one-region-per-
step apply. Rapid focus replacement cannot strand an old body, and edits refresh
already-active collision even without requesting new admission. Native and
browser fixtures raycast on both sides of the independently
applied tile/region seam and compare hits with the visual heightfield. The
Compatibility shader supplies height/slope semantic albedo without textures and
optionally blends at most four samples from a maximum 16-layer, 2048-pixel array;
both missing-texture and two-layer fixtures are green. Current headed Chromium
and Firefox satisfy the local strict correctness contract. Repeated near/far
and maximum LOD, one-level adjacency, negative offset, and destroy/recreate are
now locally green, including all 16 edge-stitch meshes. The new hosted workflow,
headed hardware performance, Safari proper, and physical Android/iOS evidence
keep the release gate open.

### Milestone 5 — Web runtime prerelease distribution — second candidate prepared; stable gate open

- `web-runtime-v0.1.0-rc.1` is the versioned review baseline; the tag workflow
  publishes core/extended bundles and receipts only after clean Web and native
  jobs pass, with repository release immutability and GitHub attestation.
- `web-runtime-v0.1.0-rc.2` adds the checked machine-readable runtime contract as
  a standalone/index-bound asset and inside both complete profile archives.
- `WEB_RELEASE_PROCESS.md` is the clean-clone build, verification, integration,
  promotion, and rollback contract.
- `WEB_SUPPORT_MATRIX.md` publishes the exact capability/browser evidence and
  keeps headed Safari, Android, iOS, and representative performance rows open.
- Full native debug/release, full-profile registration, native core/extended,
  and extended companion regressions are mandatory CI jobs.
- Hosted CI now source-builds the receipt-bound dlink template and requires both
  exported profiles to pass headed virtual-display Chromium/Firefox correctness
  before a tag may publish. Pinned WebKit remains a retained non-blocking
  diagnostic. A green required run emits a
  candidate/source/module/template/browser-bound aggregate consumed by the
  stable gate. Pushes to `integration/next` exercise this same required lane and
  retain commit-addressed review artifacts without publishing a release.
- The automatic tag publisher is deliberately prerelease-only and rejects a
  stable-looking tag. This prevents a green compile/hosted-correctness run from
  bypassing the still-external physical, calibrated-performance, and rollback
  gates.
- A manual dispatch can now build the exact final stable version name from
  `master` before physical testing. After both profile gates pass, the stable
  promotion preparer stages those unchanged candidate assets, normalized
  evidence, candidate-index-bound calibration, per-profile statuses, a promotion
  manifest, and complete checksums, then independently reverifies the directory.
- The immutable first candidate and second candidate establish a real artifact
  rollback pair. Stable release still requires an actual whole-profile
  candidate-to-prior project restoration and repeated runtime smokes on
  representative hardware; file-level substitution is never accepted. The
  prepare/serve/capture/record tooling now covers core and extended independently,
  and the candidate-index-bound machine gate names every absent rollback lane.

### Milestone 6+ — Extended capabilities — bounded maturation locally verified 2026-08-31

`web_extended` packages the same bounded terrain core plus a separately hashed
companion. Foliage, mesh HLOD, navigation, and paths each have revision-safe,
cancellable, bounded data-first projection/replacement/release fixtures. The
suite now includes exported grass/road/rock/navigation resources, actual
NavigationServer pathfinding, strict mesh/navigation index ceilings, fail-closed
installed ownership, moving revisions, and HLOD hysteresis. Fresh local
current Chromium 151 and Firefox 153 runs load the same extended side-module
hash, execute those exported-resource fixtures, return a real navigation route,
perform an HLOD swap, capture a nonblank framebuffer, and report no console,
page, request, or HTTP errors. On 2026-08-31 the fixtures added foliage quality
ceilings, navigation profile/join queries, opt-in pre-baked path collision, HLOD
cross-fades, and exact 256-stop moving-residency accounting. The local software
run completed the bounded contract but failed provisional hardware timing
thresholds and therefore does not close any representative lane. Playwright
WebKit 26.5 reaches the marker and
nonblank framebuffer but reports Godot WebGL feedback errors, so it remains a
diagnostic. Each capability still requires
its own representative-content, long-traversal performance/memory,
physical-device, and native-regression gate; they do not share one blanket
“feature parity” approval. Clean-merge compilation and packaging are now common
release gates; each extended capability still owns its representative-content
and physical-device evidence.

## 9. Major decision checkpoints

The following decisions remain evidence-driven:

| Decision | Default | Evidence that could change it |
|---|---|---|
| R32F versus encoded RGBA8 height textures | R32F nearest | Browser correctness, texture memory, or driver failures |
| Single-thread versus threaded release | Single-thread | Broad hosting/mobile support plus material frame-time win without deadlock risk |
| Existing grid LOD versus redesigned topology | Preserve existing | Seam, CPU, memory, or draw-call evidence showing it cannot meet budgets |
| Per-region texture versus atlas/array storage | Preserve per-region initially | Texture/RID overhead dominates representative profiles |
| Synchronous collision apply versus further staging | Bounded main-thread apply | Collision activation exceeds accepted stall budget |
| Optional disk cache | None initially | Network/startup evidence plus a bounded versioned recovery design |
| Foliage in core versus extended binary | Extended | Small binary/startup cost and a required first consumer |
| Runtime navigation baking | Precomputed/supplied | Incremental baking meets mobile-Web frame and memory budgets |
| Pre-baked path collision | Explicit opt-in; one bounded allowlisted shape | Representative road physics and device stalls pass independently |
| HLOD transition | Immediate by default; optional bounded cross-fade | Representative content establishes a different safe default |

Record a decision in this document before changing a default. Keep the old path
until migration and rollback evidence exists.

## 10. Explicit non-goals

- Running the native MTerrain editor UI inside the browser.
- Making browser-local files the authority for terrain.
- Loading all regions of the nominal maximum terrain simultaneously.
- Requiring cross-origin isolation merely to display terrain.
- Reimplementing Forward+/Mobile rendering features in Compatibility.
- Treating decals, compute shaders, dynamic GI, or volumetric effects as Web
  terrain requirements.
- Porting every native subsystem before the height runtime is release-ready.
- Hiding missing capability behind silent fallback during validation.

## 11. Definition of done for the long-term Web program

The program is complete when a clean clone can reproducibly build a versioned,
single-threaded wasm32 MTerrain runtime; that runtime can stream, update, render,
collide, evict, and reload bounded heightfield regions under representative
desktop and mobile browsers; its capability and artifact provenance are
machine-readable; malformed data fails closed; frame, memory, download, and
startup budgets pass; and native editor/runtime behavior remains green.

Extended foliage, HLOD, navigation, and path support may continue afterward as
independent capabilities. Their absence does not invalidate a complete and useful
heightfield Web runtime.
