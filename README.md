# Godot M Terrain
MTerrain is an optimized terrain system/editor for Godot Engine.

Web runtime work is governed by the standalone
[Web Runtime Roadmap](docs/WEB_RUNTIME_ROADMAP.md). The primary browser target is
Godot 4.7, wasm32, the Compatibility renderer, WebGL2, and a single-threaded
GDExtension build. The experimental `web_core` slice compiles and initializes a
four-region memory-only terrain, atomically applies a bounded height tile across
both shared region borders, and renders it in local Chromium, Firefox, and WebKit
automation. Bounded streaming, collision traversal, eviction, performance, CI
artifacts, and physical-device gates remain before a Web runtime release claim.

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
`tools/web_toolchain.json`. Install/activate those exact tools, then provide
their executables without copying them into the repository:

```sh
export GODOT_BIN=/path/to/Godot_4.7
export SCONS_BIN=/path/to/scons-4.8.1
export EMSDK_ENV=/path/to/emsdk/emsdk_env.sh
export BROTLI_BIN=/path/to/brotli-1.2.0
./scripts/build_web.sh all
```

The command produces debug and release wasm32 no-thread side modules under
`build/mterrain/` and machine-readable receipts under `build/receipts/`. The
receipts include hashes, raw/Brotli sizes, and the exact required WebAssembly
features; the build fails if a no-thread artifact requests threads or shared
memory. Both directories are ignored build output. A project must use a Godot
4.7 Web export template built with GDExtension support, dynamic linking, and
`threads=no`.

Builds keep target-specific `godot-cpp` generated bindings and libraries under
`build/godot-cpp/`, so native 64-bit and wasm32 invocations do not overwrite one
another. A repeated identical invocation is incremental.

Run the repository checks with:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
```

The native and browser smoke helpers under `scripts/` require locally installed
Godot templates and browser tooling; see the roadmap for the exact acceptance
ladder and the capabilities that are intentionally still closed.

For the current initialized-tile smoke on an Intel macOS host, first build the
matching native `web_core` library, then stage/export and run browsers
sequentially:

```sh
"$SCONS_BIN" -C gdextension \
  platform=macos arch=x86_64 target=template_debug precision=single threads=no \
  api_version=4.7 mterrain_profile=web_core \
  build_profile="$PWD/gdextension/web_core_build_profile.json"

GODOT_BIN="$GODOT_BIN" ./scripts/run_native_core_smoke.sh \
  build/mterrain/libMTerrain.macos.template_debug.x86_64.nothreads.dylib

python3 scripts/export_web_smoke.py \
  --godot "$GODOT_BIN" \
  --template-debug /path/to/godot.web.template_debug.wasm32.nothreads.dlink.zip \
  --native-library \
    build/mterrain/libMTerrain.macos.template_debug.x86_64.nothreads.dylib

python3 scripts/run_web_smoke.py --browser chromium
python3 scripts/run_web_smoke.py --browser firefox
python3 scripts/run_web_smoke.py --browser webkit
```

Use `arch=arm64` and the corresponding artifact name on Apple Silicon. Browser
checks require Playwright and its selected engines. Each report retains both a
page screenshot and a pixel-exact PNG reconstructed from the WebGL framebuffer,
which avoids headless WebKit screenshot limitations. These local headless checks
are not substitutes for the headed and physical-device gates in the roadmap.
