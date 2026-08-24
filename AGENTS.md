# MTerrain Agent Guidance

## Scope and first checks

- This file applies to the entire repository. Its purpose is to keep MTerrain's
  Web runtime work reproducible, bounded, portable, and independently useful.
- Start every task with `git status -sb`, `git log -5 --oneline --decorate`, and
  `git submodule status`. Preserve unrelated work. If the checkout is dirty,
  use a dedicated worktree and an `agent/*` branch.
- Read `docs/WEB_RUNTIME_ROADMAP.md` before selecting or implementing Web work.
  Update it in the same change whenever a decision, milestone, validation gate,
  supported capability, or toolchain pin moves.
- The repository's default branch is `master`. Treat `origin/master` as the
  mainline unless the repository owner deliberately changes the GitHub default.
- Initialize the pinned binding submodule before compiling:

  ```sh
  git submodule update --init --recursive
  ```

## Product boundary

- MTerrain is a Godot terrain runtime and native authoring plugin. Web support
  must remain useful without assuming a particular game, backend, networking
  layer, content service, or persistence service.
- The primary Web target is Godot 4.7 stable, wasm32, the Compatibility renderer,
  WebGL2, and a single-threaded GDExtension export template.
- A threaded Web build is an optional diagnostic profile. It must never be the
  only way to render terrain in a browser.
- Native editor and runtime behavior must continue to work. Web-specific code
  belongs behind explicit build/runtime capabilities, not platform-shaped hacks
  spread through unrelated classes.
- Runtime classes must be usable without enabling the editor plugin. Editor UI,
  import tools, baking, sculpting, and project-file mutation are authoring-only.
- Runtime data may be supplied from packed read-only resources or bounded
  in-memory buffers. Exported Web code must not require writes to `res://`.
  `user://` is an optional disposable cache, never required world state.

## Web architecture invariants

- Keep the default native build feature-complete. Add a deliberate Web runtime
  profile that compiles only capabilities proven on WebGL2.
- Web libraries and their export template must use the same Godot version,
  GDExtension API, `godot-cpp` revision, Emscripten version, pointer width,
  precision, target, and thread mode. Record the complete tuple in build receipts.
- A single-threaded build must not compile or invoke `std::thread`, forced
  `std::async`, blocking future waits, or work that assumes a populated
  `WorkerThreadPool`. Mutexes are not a substitute for a scheduling design.
- Long terrain work must expose explicit bounded plan/step/apply phases. Work is
  cancellable by stable identifier, stale revisions cannot install, and rendering
  or physics server mutation occurs on the Godot main thread.
- Batch APIs are mandatory for height-tile ingestion. Do not perform one dynamic
  language/native call per sample in production paths.
- Apply height changes in this order: validate the entire request, stage sample
  data, update shared borders, regenerate an expanded normal rectangle, upload
  textures once, and optionally refresh bounded collision once. A failed request
  must not partially advance the visible tile.
- Keep terrain height/LOD, collision, materials, foliage, navigation, paths, and
  HLOD as separately selectable capabilities. A browser build must not link every
  subsystem merely because the native editor supports it.
- WebGL2 uses the Compatibility renderer. Do not depend on RenderingDevice,
  compute shaders, decals, dynamic GI, volumetric effects, or other
  Forward+/Mobile-only behavior in the Web profile.
- Texture-array materials need explicit layer, sampler, memory, and shader-cost
  limits. A format compiling on desktop OpenGL is not Web evidence.
- Terrain visibility must have an intentional unshaded/texture-missing base
  appearance. Optional textures enhance it rather than providing the only
  readable surface.
- Heightfield collision is near-focus only and budgeted independently from visual
  LOD. Caves, overhangs, bridges, and tunnels are not encoded as heightfield
  exceptions.
- Never silently select a different runtime capability during a benchmark or
  release test. Unsupported requested capabilities fail closed with a useful
  reason; an application may explicitly select its own fallback.

## Source and build organization

- `gdextension/src/` owns runtime C++ code. Keep editor-only bindings and source
  under `gdextension/src/editor/` and exclude them from exported runtime profiles.
- `gdextension/SConstruct` owns feature selection and output naming. New build
  switches require deterministic defaults, validation of invalid combinations,
  and documentation in the Web roadmap.
- `gdextension/MTerrain.txt` and `MTerrain_double.txt` are source manifests.
  Generated manifests may add exact feature-tagged Web entries, but library names
  must match `godot-cpp` suffixes, especially `.wasm32.nothreads.wasm`.
- `start_opengl.gdshader` is the minimal Compatibility reference. Preserve a
  shader-import test for it before extending Web materials.
- Do not commit compiled libraries, export templates, browser profiles, caches,
  imported `.godot/` state, screenshots, or raw benchmark output. Commit small
  deterministic fixtures and sanitized machine-readable receipts only when they
  form part of a reviewed contract.
- Keep the upstream MIT notice intact. Isolate fork-specific changes so useful
  fixes can be proposed upstream without dragging in application-specific code.

## Validation ladder

Run the smallest relevant checks during iteration and every applicable higher
gate before calling a milestone complete:

1. Formatting/static checks and source-profile assertions.
2. Native host debug and release compilation with the pinned submodule.
3. wasm32 single-thread debug and release compilation.
4. GDExtension manifest and exported side-module verification.
5. Godot 4.7 Compatibility project import and extension registration smoke.
6. Headed browser smoke with a nonblank terrain frame and no console/WebGL error.
7. Height-tile integrity, border, normal, collision, update, cancellation, and
   unload/reload tests.
8. Representative Chrome/Chromium, Firefox, and Safari coverage; include mobile
   Safari and Android-class hardware before release claims.
9. Performance evidence: compressed download bytes, startup delay, first-tile
   latency, p50/p95/p99 frame time, longest main-thread stall, texture/heap
   estimates, resident regions, collision activation, and eviction recovery.
10. Native editor/runtime regressions for every capability touched by Web work.

A compile is not runtime evidence, desktop Compatibility is not browser evidence,
and emulation is not physical-mobile evidence. Record exact revisions, browser,
OS, GPU renderer, viewport, thread profile, fixture, and quality profile.

## Engineering defaults

- Make the smallest Web capability pass end to end before porting the next one.
- Prefer explicit capability tables and build profiles over preprocessor branches
  at individual call sites.
- Preserve public methods or introduce a versioned replacement and compatibility
  window. Validate all arrays, dimensions, bounds, finite values, and byte sizes
  before mutation.
- Avoid allocation, file I/O, resource loading, texture construction, normal
  regeneration, and collision rebuilding in unbounded frame callbacks.
- Use closed-cardinality counters and timings. Do not log terrain payloads,
  filesystem contents, or unbounded per-sample diagnostics.
- Treat browser memory as constrained. Use bounded residency and explicit
  eviction; do not validate a nominal multi-kilometre terrain by loading every
  region at once.
- When a Web workaround would weaken native correctness, introduce a shared
  primitive or a capability-specific implementation instead of changing the
  meaning of the native path.

## Current priority

The active sequence is:

1. Reproducible wasm32 single-thread build and load canary.
2. Minimal runtime-only source profile.
3. Versioned native height-tile batch API and no-save memory-fed mode.
4. Bounded single-thread terrain update/LOD work.
5. Near-focus collision and deterministic eviction.
6. Compatibility material limits and representative browser evidence.
7. Optional foliage, mesh HLOD, navigation, and path projections, one proven
   capability at a time.

Do not skip directly to broad feature parity. The detailed acceptance gates and
decision points are maintained in `docs/WEB_RUNTIME_ROADMAP.md`.
