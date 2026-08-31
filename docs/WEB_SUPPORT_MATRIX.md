# MTerrain Web support matrix

This matrix describes the post-`web-runtime-v0.1.0-rc.2` work toward the next
bounded runtime candidate. It is not a claim that the native authoring plugin or
every native runtime subsystem works in browsers.

## Distribution profiles

| Capability | `web_core` | `web_extended` | Current boundary |
|---|---:|---:|---|
| Heightfield terrain and visual LOD | Yes | Yes | Runtime API v2, R32F metres |
| Bounded queue/step/cancel/rollback | Yes | Yes | Explicit sample and region budgets |
| Deterministic tile/region eviction | Yes | Yes | Caller-owned residency ceilings |
| Scheduler-owned visual residency | Yes | Yes | Zero implicit regions; topology/range hard caps |
| Closed per-phase timing metrics | Yes | Yes | Ten fixed plan/apply/rollback categories |
| Shared-edge mismatch rejection | Yes | Yes | Atomic validation before mutation |
| Near-focus heightfield collision | Yes | Yes | Main-thread, independently budgeted |
| Texture-optional Compatibility material | Yes | Yes | At most four samples from 16 layers |
| Bounded MultiMesh foliage | No | Yes | Supplied mesh, no foliage collision |
| Supplied/precomputed navigation | No | Yes | Path queries yes; runtime baking no |
| Baked mesh paths | No | Yes | No runtime deformation or collision |
| Mesh HLOD | No | Yes | One to four supplied levels, hysteretic |
| Native editor/sculpt/import tools | No | No | Native-only authoring surface |

Both profiles require Godot 4.7 stable, WebGL2, the Compatibility renderer, a
single-precision wasm32 export, GDExtension dynamic linking, and `threads=no`.
Requests outside the advertised capability dictionary must fail closed.

## Evidence status

| Environment | Core | Extended | What the result proves |
|---|---:|---:|---|
| Ubuntu 24.04 clean-clone CI | Required green | Required green | Pinned debug/release wasm builds, receipts, packages, and native regressions |
| Ubuntu 24.04 hosted browser CI | Workflow and aggregate gate added; first green run pending | Workflow and aggregate gate added; first green run pending | Source-built pinned dlink template and candidate-bound headed Chromium/Firefox correctness; WebKit diagnostic retained separately |
| Playwright Chromium 151 on local Linux/WSL2 virtual display | Pass | Pass | Current WebGL2 runtime fixtures, collision seam, and nonblank framebuffer; software-rendered correctness only |
| Playwright Firefox 153 on local Linux/WSL2 virtual display | Pass | Pass | Same current automated correctness fixture |
| Playwright WebKit 26.5 | Diagnostic failure on current source | Diagnostic rerun pending | Core reaches the success marker and a nonblank frame, then reports WebGL framebuffer feedback errors; this is not Safari-product evidence |
| Headed hardware Chrome/Chromium | Open | Open | Required for representative GPU/frame budgets |
| Headed hardware Firefox | Open | Open | Required for representative GPU/frame budgets |
| Safari on macOS | Open | Open | Required; Playwright WebKit is not a substitute |
| Android-class physical Chrome | Open | Open | Required before a mobile support claim |
| iPhone/iPad physical Safari | Open | Open | Required before a mobile support claim |

The automated browser passes exercise real exported dynamic-link side modules,
two adjacent height tiles, normals and collision across their seam, malformed
input and deliberate shared-edge mismatch rejection, cancellation and
replacement, bounded eviction, repeated near/far/max LOD transitions, negative
terrain offsets, destroy/recreate recovery, a teleport sequence, closed phase
timings, and direct framebuffer readback. The extended fixture additionally
uses exported foliage/road/HLOD/navigation resources and performs an actual
navigation path query.
The separate whole-bundle rollback fixture also passes locally in headed
Chromium 151 and Firefox 153 for both profiles, including bounded collision and
zero-residency eviction recovery. Those fixture passes validate the harness;
they are not candidate-to-prior physical rollback receipts.

The local Chromium run used software rendering and is correctness evidence only.
Neither a headless run nor a hosted virtual-display run is accepted as
representative performance evidence. No row marked Open should be inferred from
desktop emulation or a user-agent string.

## Release posture

- `web-runtime-v0.1.0-rc.2` is suitable for integration and human review behind
  explicit capability selection.
- Verify `runtime/web_runtime_contract.json` through the release index before
  loading either profile; reject target, API, method, format, limit, or live
  capability mismatches.
- `web_core` is the preferred first integration profile. Select
  `web_extended` only when its supplied-data projections have a named consumer.
- A stable general Web release remains gated on headed representative traversal,
  calibrated frame-time/memory/startup budgets, Safari proper, physical
  Android/iOS evidence, and candidate-to-`web-runtime-v0.1.0-rc.2` whole-profile
  rollback receipts on those same named lanes. Core and extended performance and
  rollback evidence are separate profile claims.
- `tools/web_release_gate.json`, the provisional
  `tools/web_performance_calibration.json` template, the post-build approval
  receipt emitted by `approve_web_performance_calibration.py`, and
  `verify_web_release_gate.py` are the
  fail-closed authority for those external rows. Playwright engines, software
  renderers, emulated mobile viewports, reversed rollback order, and unapproved
  provisional thresholds cannot satisfy them. Stable verification also requires
  a verified candidate asset directory and rejects hosted/performance/rollback
  evidence that is not bound to its indexed source, receipt, module, and bundle.
  Calibration approval additionally names the exact immutable candidate release
  index, so approving evidence never changes the package that was measured. The
  candidate also carries the exact traversal sources, and the budget covers the
  complete deterministic-gzip runtime export rather than only the plug-in wasm.
  Rollback verification independently loads both the candidate and prior release
  directories and matches both index/profile-bundle digests.
- Foliage collision, runtime navigation baking, runtime curve deformation,
  runtime mesh generation, path collision, caves, tunnels, and overhangs are not
  part of this candidate.

When a row changes, record the exact source tag, bundle digest, Godot template,
browser version, OS, GPU renderer, viewport, fixture, profile, and whether the
browser was headed on physical hardware.
