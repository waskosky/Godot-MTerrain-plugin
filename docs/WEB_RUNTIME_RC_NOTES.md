# MTerrain Web runtime 0.1.0 release candidate 2

This prerelease retains the bounded, single-threaded Godot 4.7 WebGL2 runtime
from release candidate 1 and adds a release-verifiable capability contract for
integration and human review.

- `web_core` contains runtime API v2 terrain height/LOD, bounded scheduling and
  eviction, near-focus heightfield collision, and constrained Compatibility
  materials.
- `web_extended` adds the separately gated data-first foliage, supplied
  navigation, baked-mesh path, and mesh-HLOD companion.
- Both bundles contain debug/release wasm32 no-thread side modules, exact build
  receipts, installation docs, the published support matrix, and byte-identical
  `mterrain-web-runtime-contract-v1` data.
- The runtime contract is also a standalone asset. The release index and
  `SHA256SUMS` bind it and every distributed artifact to this source revision;
  source CI rejects method, capability, limit, state-version, or target drift.
- Immutable release candidate 1 remains the prior complete-profile rollback
  baseline. Release candidate 2 supplies the second version needed for human
  candidate-to-prior restoration review.

This is not a native editor package or a blanket mobile-browser support claim.
Headed representative performance, Safari proper, and physical Android/iOS
evidence remain open before stable release. See `docs/WEB_SUPPORT_MATRIX.md` and
`docs/WEB_RELEASE_PROCESS.md` in the tagged source or either bundle.
