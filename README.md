# Godot M Terrain
MTerrain is an optimized terrain system/editor for Godot Engine.

Web runtime work is governed by the standalone
[Web Runtime Roadmap](docs/WEB_RUNTIME_ROADMAP.md); see the
[Web Runtime API](docs/WEB_RUNTIME_API.md) for exact methods, limits, ownership,
and failure semantics. The primary browser target is
Godot 4.7, wasm32, the Compatibility renderer, WebGL2, and a single-threaded
GDExtension build. Experimental runtime API v2 now provides bounded,
cancellable, revision-safe height work, deterministic tile/region eviction,
near-focus collision kept aligned across later edits, and constrained
texture-optional materials. It also reports ten closed timing phases and bounded
visual-LOD transition state, rejects mismatched shared tile edges atomically,
and covers maximum LOD plus negative-offset destroy/recreate recovery. The opt-in
`web_extended` package adds bounded data-first foliage, precomputed navigation,
baked-path, and hysteretic mesh-HLOD projections without linking the native
authoring subsystems. Its fixtures include exported grass/road/rock/navigation
resources, moving revisions, and a real navigation path query. The
`web-runtime-v0.1.0-rc.2` review candidate adds clean-clone debug/release builds,
native regressions, immutable profile bundles and receipts, and an index-bound
machine-readable runtime contract alongside the published
[support matrix](docs/WEB_SUPPORT_MATRIX.md). The repository now pins and builds
its Godot dynamic-link template, defines candidate-bound hosted-browser
correctness, and provides receipt-bound fixed traversal/device-capture plus
independent core/extended whole-bundle rollback gates. Bundles carry a
provisional threshold/calibration template; reviewed evidence is approved later
by a separate receipt bound to the immutable candidate release index, avoiding
any rebuild-and-retest cycle. Candidate bundles also carry the exact traversal
sources, and performance budgets measure the deterministic compressed size of
the complete runtime export rather than only the plug-in side module. Local
headed Chromium/Firefox correctness checks are green for both profiles.
Playwright WebKit reaches the fixture marker and a nonblank frame but its pinned
Linux engine reports Godot framebuffer feedback errors, so it is retained as a
diagnostic rather than mislabeled Safari evidence. The first hosted workflow
run, calibrated headed representative-hardware performance, Safari proper,
physical Android/iOS, and actual candidate-to-prior rollback receipts remain
before a stable Web runtime claim.

![Screenshot_20230707_104154](https://github.com/mohsenph69/Godot-MTerrain-plugin/assets/52196206/7e3eb7da-af57-4ae5-8f55-f9fc1c8b26f8)


## Features
* Terrain that uses an octree based LOD system for terrain sizes as big as 16km x 16km
* Terrain shader with support for splatmapping, bitwise, and index mapping
* Navigation integration with Godot's navigation system
* Grass system with collision for things like trees, grass, rocks, etc
* Path system based on bezier curves with mesh deformation for roads, rivers, etc.
* Octree system for optimized control of LOD allowing for large number of objects in the world 
* Editor tools for Terrain sculpting, Grass painting, Navigation painting, Path editing, and importing/exporting heightmaps and splatmaps
  
![Screenshot_20230719_144752](https://github.com/mohsenph69/Godot-MTerrain-plugin/assets/52196206/704c51a8-7554-4345-907b-efc635a67dd0)

# Getting Started

To use this plugin you will need to learn some concepts - this terrain plugin will not work out of the box.
Please read the [wiki](https://github.com/mohsenph69/Godot-MTerrain-plugin/wiki/)  

Or watch this video will be helpful:
https://www.youtube.com/watch?v=PcAkWClET4U

This video shows how to use use height brushes to sculpt the terrain:
https://www.youtube.com/watch?v=e7nplXnemGo

This video shows how to use Texture painting:
https://www.youtube.com/watch?v=0zEYzKEMWR8

## Patreon

You can support me with patreon [Click here](https://patreon.com/mohsenzare?utm_medium=clipboard_copy&utm_source=copyLink&utm_campaign=creatorshare_creator&utm_content=join_link)

![Screenshot_20230719_144757](https://github.com/mohsenph69/Godot-MTerrain-plugin/assets/52196206/ef78652f-c4cc-4226-948e-9f4e44bb1af8)

## Build from source

Initialize the exact `godot-cpp` revision recorded by this repository:

```sh
git submodule update --init --recursive
```

The normal native build remains feature-complete:

```sh
scons -C gdextension \
  platform=macos \
  arch=universal \
  target=template_debug \
  precision=single \
  mterrain_profile=full
```

Select the appropriate native `platform` and `arch` for another host. A
standalone checkout writes to `build/mterrain/`; an existing
`res://addons/m_terrain` source layout retains its historical
`res://mterrain` output. Set `mterrain_output_dir` to an explicit destination
when packaging another layout.

The experimental browser artifacts use the fully pinned Godot, `godot-cpp`,
Emscripten/emsdk, Binaryen, SCons, and Brotli tuple in
`tools/web_toolchain.json`. Release CI resolves the matching Linux host tools
from `tools/ci_toolchain.json`; see the
[release process](docs/WEB_RELEASE_PROCESS.md) for a clean-clone reproduction.
On another host, install/activate the exact tools, then provide their
executables without copying them into the repository:

```sh
export GODOT_BIN=/path/to/Godot_4.7
export SCONS_BIN=/path/to/scons-4.8.1
export EMSDK_ENV=/path/to/emsdk/emsdk_env.sh
export BROTLI_BIN=/path/to/brotli-1.2.0
./scripts/build_web.sh all web_core
# Optional data-first foliage/navigation/path/HLOD companion profile:
./scripts/build_web.sh all web_extended
```

Core debug/release wasm32 no-thread side modules are written under
`build/mterrain/`; extended modules are isolated under
`build/mterrain/web_extended/`. Machine-readable v2 receipts under
`build/receipts/` include capability/profile data, hashes, raw/Brotli sizes, the
exact required WebAssembly features, and the extended companion hash when
selected. The build fails if a no-thread artifact requests threads or shared
memory. These directories are ignored build output. A project must use a Godot
4.7 Web export template built with GDExtension support, dynamic linking, and
`threads=no`. `scripts/build_web_export_template.sh` builds that template from
the pinned Godot source and emits a member-level receipt; browser and hardware
evidence commands are documented in the release process.

CI packages the two profiles separately. Each tagged prerelease contains both
bundles, their machine-readable release index, `SHA256SUMS`, and GitHub's
immutable release attestation. Start with `web_core`; choose `web_extended` only
when its optional projections have a named consumer. These bundles are Web
runtime inputs and do not replace the native editor package.

Builds keep target-specific `godot-cpp` generated bindings and libraries under
`build/godot-cpp/`, so native 64-bit and wasm32 invocations do not overwrite one
another. A repeated identical invocation is incremental.

Run the repository checks with:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
```

The native and browser smoke helpers under `scripts/` require locally installed
Godot templates and browser tooling. `runtime/web_extended_runtime.gd` is
packaged only for `web_extended`; its accepted resources are `res://` assets
subject to an explicit allowlist, or in-memory resources only when the project
deliberately enables that policy. It does not bake navigation, deform curves,
generate runtime meshes, or create foliage/path collision. Mesh and navigation
vertex/index ownership, cancellation, replacement, and HLOD focus changes are
explicitly bounded. See the roadmap for the exact acceptance ladder.

For the bounded seam/collision smoke on an Intel macOS host, first build the
matching native `web_core` library, then stage/export and run browsers
sequentially:

```sh
"$SCONS_BIN" -C gdextension \
  platform=macos arch=x86_64 target=template_debug precision=single threads=no \
  api_version=4.7 mterrain_profile=web_core \
  build_profile="$PWD/gdextension/web_core_build_profile.json"

GODOT_BIN="$GODOT_BIN" ./scripts/run_native_core_smoke.sh \
  build/mterrain/libMTerrain.macos.template_debug.x86_64.nothreads.dylib \
  web_core

python3 scripts/export_web_smoke.py \
  --profile web_core \
  --godot "$GODOT_BIN" \
  --template-debug /path/to/godot.web.template_debug.wasm32.nothreads.dlink.zip \
  --native-library \
    build/mterrain/libMTerrain.macos.template_debug.x86_64.nothreads.dylib

python3 scripts/run_web_smoke.py --browser chromium
python3 scripts/run_web_smoke.py --browser firefox
python3 scripts/run_web_smoke.py --browser webkit
```

Select `--profile web_extended`, the corresponding native library under
`build/mterrain/web_extended/`, `web_extended` as the native-smoke profile
argument, and a separate output directory to exercise all four optional
projections. The terrain bridge exposes its exact bounds through
`get_runtime_capabilities()` and live queue/residency/collision metrics through
`get_runtime_state()`, including visual LOD and phase timings; callers should use
`queue_height_tile()` plus
`step_runtime_work()` for frame-budgeted streaming and reserve
`apply_height_tile()` for bounded compatibility calls.

Use `arch=arm64` and the corresponding artifact name on Apple Silicon. Browser
checks require Playwright and its selected engines. Each report retains both a
page screenshot and a pixel-exact PNG reconstructed from the WebGL framebuffer,
which avoids compositor screenshot limitations in some automated WebKit runs.
Local automation and hosted virtual-display checks are not substitutes for the
physical-device and representative-performance gates in the roadmap.
