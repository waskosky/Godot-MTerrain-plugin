# MTerrain Web runtime 0.1.0 release candidate 1

This prerelease packages the first bounded, single-threaded Godot 4.7 WebGL2
runtime for integration and human review.

- `web_core` contains runtime API v2 terrain height/LOD, bounded scheduling and
  eviction, near-focus heightfield collision, and constrained Compatibility
  materials.
- `web_extended` adds the separately gated data-first foliage, supplied
  navigation, baked-mesh path, and mesh-HLOD companion.
- Both bundles contain debug/release wasm32 no-thread side modules, exact build
  receipts, installation docs, and a published support matrix.
- The release index and `SHA256SUMS` bind every distributed asset to this source
  revision. GitHub release attestation provides an additional immutable check.

This is not a native editor package or a blanket mobile-browser support claim.
Headed representative performance, Safari proper, and physical Android/iOS
evidence remain open before stable release. See `docs/WEB_SUPPORT_MATRIX.md` and
`docs/WEB_RELEASE_PROCESS.md` in the tagged source or either bundle.
