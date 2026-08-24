# MTerrain Web Runtime Roadmap

- Status: active delivery; repository contract complete and first initialized
  height-projection slice locally verified on 2026-08-24
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

The first implementation slice is now present:

- `full`, `runtime`, and fail-closed `web_core` source profiles exist. Web accepts
  only single-precision, no-thread `web_core`; its C++ closure excludes editor,
  octree-object, grass, navigation, path, mesh-HLOD, and decal sources.
- Godot 4.7 stable, its exact GDExtension API, `godot-cpp`, Emscripten, emsdk,
  Binaryen, SCons, and Brotli are pinned in `tools/web_toolchain.json`.
- Debug and release wasm32 no-thread manifest entries, a trimmed binding profile,
  deterministic build script, artifact receipt writer, and target-separated
  MTerrain object and `godot-cpp` variant directories are checked in. Plugin
  objects wait for their target-width-specific binding library, preventing
  native/Web header races without forcing every invocation to regenerate it.
- A pinned, least-privilege source-contract workflow checks standalone
  governance, profile/manifest invariants, and Python/shell parsing on pull
  requests and default-branch pushes. It does not yet compile Web artifacts.
- Core thread/future launch sites have explicit synchronous `web_core` branches.
  The automatic terrain and physics loops default off in that profile because
  their work is not yet a bounded state machine.
- Runtime bridge API v1 reports capabilities and accepts one validated,
  all-or-nothing, finite 67-by-67 R32F-metre height tile. It verifies every
  affected region, duplicate shared-border destination, normal destination, and
  height-source halo before mutation, expands normal regeneration by one sample,
  and coalesces the dirty upload.
- `runtime_memory_only` is mandatory in `web_core`; it cannot be disabled, and
  explicit save, editor directory creation, destructive layer-file operations,
  and eviction-time legacy saves fail closed. Packed read-only resources may
  still be loaded.
- The complete native debug/editor source profile compiles and links against the
  same Godot 4.7 API after replacing the removed `godot-cpp` VMap dependency with
  a small repository-owned sorted-vector map.
- A native fixture and real dynamic-link Web export create a four-region,
  memory-only terrain and apply one finite 67-by-67 height tile across both
  shared region borders. They verify the duplicated border height, a 69-by-69
  normal destination, rejection of a non-finite replacement without partial
  mutation, and a visible raised heightfield.
- Playwright Chromium, Firefox, and WebKit load the extension with WebGL2,
  wasm32, no threads, the expected capability tuple, a nonblank directly
  captured framebuffer, and no console, page, or request errors. Page and direct
  framebuffer captures are retained separately because some headless WebKit
  builds return a black compositor screenshot despite healthy WebGL pixels.
  These are local automated browser checks, not physical-device support claims.
- Binaryen inspection records the artifact feature set and rejects thread or
  shared-memory requirements. The locally built debug/release side modules are
  817,244/790,279 raw bytes and 119,402/118,026 bytes at Brotli quality 11.
  Final release evidence must be regenerated from the clean merged commit.

The remaining gaps are deliberately material:

1. The initialized canary proves one cross-region tile, but not two independently
   applied adjacent tiles, a visible equal-detail/LOD seam, collision traversal,
   revision replacement, eviction, or reload.
2. Terrain streaming, normals, uploads, and collision still need resumable,
   cancellable, revision-safe work with measured per-frame budgets. Synchronous
   fallback code is correctness scaffolding, not the final scheduler.
3. Per-region upload-count instrumentation and separate timing for validation,
   normal generation, texture apply, and collision remain open.
4. Collision admission/readiness, deterministic eviction, memory ceilings, and
   Compatibility material fallback still need implementation evidence.
5. Web compile/export/browser CI, clean-clone reproduction, immutable artifacts,
   and a published support matrix are not yet present; current CI is source-only.
6. Headed Chrome, Firefox, and Safari plus physical Android- and iOS-class device
   evidence remain mandatory before a browser release claim.
7. Foliage, mesh HLOD, navigation, and paths remain native-only until each earns
   an independently bounded `web_extended` implementation and gate.

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
| `web_core` | First release-bearing browser runtime | Terrain height, visual LOD, tile batch API, existing collision/material primitives; bounded collision and rendered-material proof remain gated |
| `web_extended` | Later opt-in browser runtime | Individually proven grass, mesh HLOD, navigation, and path projections |

The exact profile names may change once implemented, but the separation and
fail-closed behavior are architectural requirements.

### 3.4 Scheduling

Single-threaded Web work is expressed as explicit state machines. A work item has
a stable key, input revision, priority, deadline-aware `step()` method,
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

The public contract is versioned separately from C++ class layout. Proposed
runtime methods are:

```text
get_runtime_bridge_api_version() -> int
get_runtime_capabilities() -> Dictionary
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
```

`apply_height_tile()` is atomic from the caller's perspective:

1. Validate all parameters and calculate affected regions.
2. Stage or copy the bounded input so caller mutation cannot race installation.
3. Write samples through a bulk internal path that preserves shared border pixels.
4. Regenerate normals for the tile plus a one-sample halo, clamped to the grid.
5. Upload each dirty region texture at most once.
6. Rebuild only requested, already-admitted collision regions.
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

`gdextension/SConstruct` now owns the validated `full`, `runtime`, and
`web_core` source profiles. The following requirements remain normative:

- Web build scripts select `platform=web` and `arch=wasm32` explicitly.
- Web release and debug builds are produced explicitly with `threads=no`.
- A threaded artifact, if added later, has a different suffix and receipt.
- Editor-only source is selected by an editor capability, not merely because the
  target contains debug symbols.
- Invalid combinations stop before plugin compilation. Current Web builds reject
  every profile except `web_core`; `web_core` also rejects `threads=yes` and
  double precision.
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

The first `web_core` artifact excludes editor, grass, navigation, path, HLOD,
decal, and general object-octree sources unless the terrain core has an actual
compile-time dependency. A binding-generation profile should trim unused Godot
classes after the source profile is stable.

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

### 6.2 Mesh HLOD

Mesh-only HLOD may enter `web_extended` after terrain and foliage. Decal items,
dynamic GI assumptions, arbitrary lights, and threaded resource pipelines are
excluded initially. Packed mesh resources are prevalidated, loads are bounded,
and LOD swaps retain the last complete level until the replacement is ready.

### 6.3 Navigation

Navigation is independent of rendering. The Web path uses bounded precomputed or
incrementally supplied navigation data near active agents. Runtime baking is not
performed in an unbounded frame callback, and no `std::async` path exists in the
single-thread artifact.

Acceptance includes region joins, agent radius/slope fixtures, moving residency,
unload/reload, and a frame-time budget during navigation updates.

### 6.4 Paths

Authoring and mesh baking remain native-editor strengths. The first browser path
capability loads or receives already validated curve/mesh data and realizes it
without editor controls. Runtime curve deformation is considered only after it
has resumable bounded work and seam/collision fixtures.

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

- main and side-module raw/compressed bytes;
- page startup and extension-link time;
- first terrain and first collision time;
- p50/p95/p99 frame time and worst main-thread stall;
- per-category terrain step/apply timing;
- resident region, RID, collision, texture, and estimated heap counts;
- tile update and normal generation time;
- teleport recovery and steady-state eviction time;
- renderer, browser, OS, hardware, viewport, and exact source tuple.

Budgets are established from representative devices, stored in one versioned
configuration, and never weakened solely to make a regression pass.

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

The local gate is green for debug/release Web compilation, full native debug
compilation, native core loading, export, and Chromium/Firefox/WebKit load and
framebuffer probes. Before treating this as a distributable milestone, reproduce
it from the clean merged commit, add native release and clean-clone CI evidence,
and publish immutable artifacts/receipts.

### Milestone 2 — Batch height projection — first projection locally verified

- Versioned batch API with strict bounds and finite-value validation.
- Memory-fed/no-save runtime mode.
- Adjacent 67-by-67 tiles render with shared borders and continuous normals.
- Invalid input cannot partially mutate terrain.
- One texture upload per affected region per committed update.

API v1, memory-only policy, bounded validation, shared-border and normal-source
preflight, normal halo calculation, and coalesced dirty upload are implemented.
Native and Chromium/Firefox/WebKit fixtures initialize four RAM-backed regions,
apply one 67-by-67 tile across both shared borders, inspect a duplicated border
sample, render the raised heightfield, and prove that a non-finite replacement
does not partially mutate it. An independently applied adjacent-tile seam and
normal proof, collision traversal, and upload-count instrumentation remain open;
therefore the full milestone is not complete.

### Milestone 3 — Bounded single-thread residency

- Terrain update work is resumable, cancellable, coalesced, and revision-safe.
- Teleport and long traversal remain within configured time/memory ceilings.
- Deterministic eviction releases RIDs and buffers.
- No forced thread API remains in the `web_core` closure.

### Milestone 4 — Collision and material release candidate

- Near-focus collision has readiness and exact visual alignment evidence.
- Seam traversal passes across LOD and tile boundaries.
- Minimal and texture-enhanced Compatibility materials pass missing-texture and
  unshaded readability tests.
- Chrome, Firefox, Safari, Android-class, and iOS-class evidence is green.

### Milestone 5 — First Web runtime release

- Versioned source tag and immutable artifacts/receipts.
- Clean-clone build instructions reproduce the artifacts.
- Browser support and capability matrix is published.
- Rollback to the previous runtime artifact is tested.
- Native editor and runtime regression suites are green.

### Milestone 6+ — Extended capabilities

Foliage, mesh HLOD, navigation, and paths each require their own implementation,
browser correctness, performance, memory, eviction, and native-regression gate.
They do not share one blanket “feature parity” approval.

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
