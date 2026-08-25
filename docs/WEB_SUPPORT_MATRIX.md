# MTerrain Web support matrix

This matrix describes the `web-runtime-v0.1.0-rc.1` review candidate. It is a
bounded runtime candidate, not a claim that the native authoring plugin or every
native runtime subsystem works in browsers.

## Distribution profiles

| Capability | `web_core` | `web_extended` | Current boundary |
|---|---:|---:|---|
| Heightfield terrain and visual LOD | Yes | Yes | Runtime API v2, R32F metres |
| Bounded queue/step/cancel/rollback | Yes | Yes | Explicit sample and region budgets |
| Deterministic tile/region eviction | Yes | Yes | Caller-owned residency ceilings |
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
| Playwright Chromium 149 on macOS 15.7.1 x86_64 | Pass | Pass | Headless WebGL2 load, runtime fixtures, collision seam, nonblank framebuffer |
| Playwright Firefox 151 on macOS 15.7.1 x86_64 | Pass | Pass | Same automated correctness fixture |
| Playwright WebKit 26.5 on macOS 15.7.1 x86_64 | Pass | Pass | Same automated correctness fixture; this is not Safari-product evidence |
| Headed hardware Chrome/Chromium | Open | Open | Required for representative GPU/frame budgets |
| Headed hardware Firefox | Open | Open | Required for representative GPU/frame budgets |
| Safari on macOS | Open | Open | Required; Playwright WebKit is not a substitute |
| Android-class physical Chrome | Open | Open | Required before a mobile support claim |
| iPhone/iPad physical Safari | Open | Open | Required before a mobile support claim |

The automated browser passes exercise real exported dynamic-link side modules,
two adjacent height tiles, normals and collision across their seam, malformed
input rejection, cancellation and replacement, bounded eviction, a teleport
sequence, and direct framebuffer readback. The extended fixture additionally
uses exported foliage/road/HLOD/navigation resources and performs an actual
navigation path query.

The Chromium run used SwiftShader and is correctness evidence only. Firefox and
WebKit exposed renderer strings, but the headless harness is still not accepted
as representative performance evidence. No row marked Open should be inferred
from desktop emulation or a user-agent string.

## Release posture

- `web-runtime-v0.1.0-rc.1` is suitable for integration and human review behind
  explicit capability selection.
- `web_core` is the preferred first integration profile. Select
  `web_extended` only when its supplied-data projections have a named consumer.
- A stable general Web release remains gated on headed representative traversal,
  frame-time/memory/startup budgets, Safari proper, and physical Android/iOS
  evidence.
- Foliage collision, runtime navigation baking, runtime curve deformation,
  runtime mesh generation, path collision, caves, tunnels, and overhangs are not
  part of this candidate.

When a row changes, record the exact source tag, bundle digest, Godot template,
browser version, OS, GPU renderer, viewport, fixture, profile, and whether the
browser was headed on physical hardware.
