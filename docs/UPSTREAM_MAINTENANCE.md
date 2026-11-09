# Upstream maintenance

The fork's mainline is `origin/master`. Track the original project as
`upstream` (`https://github.com/mohsenph69/Godot-MTerrain-plugin.git`) and fetch
before comparing ancestry. Merge useful upstream changes into a dedicated
`agent/*` branch; preserve ancestry rather than copying patches without their
history. The 2026-11-09 synchronization incorporates upstream through
`e981512d5bfbec73a82b3df2936e78c1eda1e11d`:

- `061fc35`: ignored source/build paths;
- `0b01d71`: CMake frontend and registration split;
- `e1f24cb`: SCons registration shim;
- `e981512`: CMake follow-up.

The fork keeps the validated Godot 4.7 binding pin and explicit Web profiles.
Shared source selection prevents the native CMake frontend from accidentally
linking authoring code into Web or dropping native subsystems. Full native
debug/release CMake checks and a runtime debug embedding/link/load fixture run
within the existing native regression job, alongside SCons native checks. The
explicit editor capability prevents HLOD authoring helpers from leaking into
runtime debug archives. Web remains on its pinned SCons route.

## Contributions

Start small upstream branches directly from upstream `master`, without the
fork's Web history or application code. The existing C++
`MTerrain::get_active_layer_name()` lacks a script binding upstream. Its binding
is independently useful beside `set_active_layer_by_name()` and is proposed in
upstream [PR #112](https://github.com/mohsenph69/Godot-MTerrain-plugin/pull/112).
The one-line change was compiled against upstream's own 4.5 binding revision;
Godot 4.7 native registration fails the missing-method check before it and
reports a zero-argument `String` method afterward.

The six additional LOD edge masks belong to this fork's expanded scheduler.
Upstream defines and dispatches ten masks; it does not have six missing cases.
Do not present the fork's sixteen-mask extension as an upstream crash fix.
Compatibility HLOD fades currently live in the optional Web companion, so they
also require an explicit port and native reproduction before a separate native
PR is appropriate.

Coordinate the larger Web runtime design through upstream issue
[#29](https://github.com/mohsenph69/Godot-MTerrain-plugin/issues/29), and discuss
4.7 compatibility through
[#110](https://github.com/mohsenph69/Godot-MTerrain-plugin/issues/110).
Do not claim to fix #110's reported return-type error without reproducing it.
The existing CI proposal
[#89](https://github.com/mohsenph69/Godot-MTerrain-plugin/pull/89) should be
considered before proposing another broad upstream automation change.
Keep game streaming policies, seeded/diffusion content generation, adaptive
view distance, and the MTerrainTest experience in the consuming application.

## Qualification and consumer promotion

Require source-contract, clean-clone debug/release Web core/extended builds,
native regressions, and headed exported Chromium/Firefox correctness before
merging a synchronization. Preserve exact toolchain and artifact receipts.
These gates establish software correctness, not representative-hardware
performance or physical mobile/Safari release evidence.

Advance `integration/next` deliberately after mainline qualification. A consumer
pin is a separate reviewed change: replace its receipts and binaries together,
run its integration tests, and preserve a working preview until the replacement
has passed. Upstream synchronization alone does not authorize labeling an
unqualified consumer deployment as tested.
