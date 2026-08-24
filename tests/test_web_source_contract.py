from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WebSourceContractTests(unittest.TestCase):
    def test_web_governance_docs_remain_standalone(self) -> None:
        for relative in ("AGENTS.md", "docs/WEB_RUNTIME_ROADMAP.md"):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIsNone(
                re.search(r"\b(?:rai|openverse|godot-light)\b", source, re.IGNORECASE),
                relative,
            )

    def test_toolchain_is_single_threaded_wasm32_godot_47(self) -> None:
        toolchain = json.loads(
            (ROOT / "tools" / "web_toolchain.json").read_text(encoding="utf-8")
        )
        self.assertEqual(toolchain["schema"], "mterrain-web-toolchain-v1")
        self.assertEqual(toolchain["godot"]["version"], "4.7.stable.official.5b4e0cb0f")
        self.assertEqual(toolchain["platform"], "web")
        self.assertEqual(toolchain["architecture"], "wasm32")
        self.assertEqual(toolchain["precision"], "single")
        self.assertFalse(toolchain["threads"])
        self.assertEqual(toolchain["profile"], "web_core")
        self.assertEqual(toolchain["brotli_version"], "1.2.0")
        self.assertEqual(toolchain["brotli_quality"], 11)
        self.assertEqual(
            toolchain["binaryen_version"],
            "wasm-opt version 124 (version_123-495-g6d5fed324)",
        )
        self.assertEqual(
            toolchain["binding_profile"],
            "gdextension/web_core_build_profile.json",
        )
        actual_godot_cpp = subprocess.check_output(
            [
                "git",
                "-C",
                str(ROOT / "gdextension" / "godot-cpp"),
                "rev-parse",
                "HEAD",
            ],
            text=True,
        ).strip()
        self.assertEqual(actual_godot_cpp, toolchain["godot_cpp_commit"])

    def test_web_core_profile_fails_closed(self) -> None:
        sconstruct = (ROOT / "gdextension" / "SConstruct").read_text(
            encoding="utf-8"
        )
        self.assertIn('mterrain_profile == "web_core" and env["threads"]', sconstruct)
        self.assertIn('env["platform"] == "web"', sconstruct)
        self.assertIn('("moctree.cpp", "mtool.cpp")', sconstruct)
        for source_group in ("grass", "navmesh", "octmesh", "path", "hlod"):
            self.assertIn(f'Glob("src/{source_group}/*.cpp")', sconstruct)
        self.assertIn('"MTERRAIN_CORE_ONLY"', sconstruct)
        self.assertIn('"MTERRAIN_SINGLE_THREADED"', sconstruct)

    def test_web_binding_profile_omits_editor_and_rendering_device_classes(self) -> None:
        profile = json.loads(
            (
                ROOT / "gdextension" / "web_core_build_profile.json"
            ).read_text(encoding="utf-8")
        )
        enabled = set(profile["enabled_classes"])
        self.assertNotIn("EditorPlugin", enabled)
        self.assertNotIn("RenderingDevice", enabled)
        self.assertIn("RenderingServer", enabled)
        # godot-cpp's low-level helper resolves Engine.get_main_loop() to a
        # SceneTree even though MTerrain does not call either class directly.
        self.assertIn("MainLoop", enabled)
        self.assertIn("SceneTree", enabled)

        grid = (ROOT / "gdextension" / "src" / "mgrid.cpp").read_text(
            encoding="utf-8"
        )
        self.assertIn('get_current_rendering_method() == "gl_compatibility"', grid)
        self.assertNotIn("get_rendering_device()", grid)

    def test_manifest_selects_nothread_wasm_side_modules(self) -> None:
        manifest = (ROOT / "gdextension" / "MTerrain.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("compatibility_minimum = 4.7", manifest)
        self.assertIn("web.debug.wasm32", manifest)
        self.assertIn("web.release.wasm32", manifest)
        self.assertEqual(manifest.count(".wasm32.nothreads.wasm"), 2)
        self.assertNotIn("web.debug.threads", manifest)
        self.assertNotIn("web.release.threads", manifest)
        double_manifest = (
            ROOT / "gdextension" / "MTerrain_double.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("compatibility_minimum = 4.7", double_manifest)
        self.assertNotIn("web.", double_manifest)

    def test_runtime_height_tile_contract_is_versioned_and_bounded(self) -> None:
        header = (ROOT / "gdextension" / "src" / "mterrain.h").read_text(
            encoding="utf-8"
        )
        implementation = (
            ROOT / "gdextension" / "src" / "mterrain.cpp"
        ).read_text(encoding="utf-8")
        for method in (
            "get_runtime_bridge_api_version",
            "get_runtime_capabilities",
            "apply_height_tile",
        ):
            self.assertIn(method, header)
            self.assertIn(method, implementation)
        self.assertIn("width > 67 || height > 67", implementation)
        self.assertIn("sample_count > 4489", implementation)
        self.assertIn("std::isfinite", implementation)
        self.assertIn(
            'ERR_FAIL_COND_MSG(!input, "This build profile requires runtime_memory_only")',
            implementation,
        )
        grid = (ROOT / "gdextension" / "src" / "mgrid.h").read_text(
            encoding="utf-8"
        )
        region = (ROOT / "gdextension" / "src" / "mregion.cpp").read_text(
            encoding="utf-8"
        )
        image = (ROOT / "gdextension" / "src" / "mimage.cpp").read_text(
            encoding="utf-8"
        )
        self.assertIn("bool runtime_memory_only = false", grid)
        self.assertIn("unload(mres,!grid->runtime_memory_only)", region)
        self.assertIn("if(save_before_unload)", image)
        for capability in (
            "heightfield_terrain",
            "visual_lod",
            "heightfield_collision",
            "compatibility_materials",
            "bounded_update_scheduler",
            "bounded_collision",
        ):
            self.assertIn(f'capabilities["{capability}"]', implementation)
        self.assertIn('capabilities["api_stability"] = "experimental"', implementation)
        tile_apply = implementation[implementation.index("Dictionary MTerrain::apply_height_tile") :]
        self.assertLess(
            tile_apply.index("grid->can_set_height_by_pixel"),
            tile_apply.index("grid->set_height_by_pixel(\n"),
        )
        self.assertLess(
            tile_apply.index("grid->can_update_normals"),
            tile_apply.index("grid->set_height_by_pixel(\n"),
        )
        self.assertIn('fail("normal_halo_not_resident"', tile_apply)
        self.assertLess(
            tile_apply.index("grid->update_normals"),
            tile_apply.index("grid->update_all_dirty_image_texture(update_collision)"),
        )

    def test_web_core_registration_excludes_extended_classes(self) -> None:
        registration = (
            ROOT / "gdextension" / "src" / "register_types.cpp"
        ).read_text(encoding="utf-8")
        include_guard = registration.index("#ifndef MTERRAIN_CORE_ONLY")
        first_extended_include = registration.index('#include "grass/mgrass.h"')
        self.assertLess(include_guard, first_extended_include)
        self.assertIn("ClassDB::register_class<MTerrain>();", registration)
        self.assertIn("ClassDB::register_class<MTerrainMaterial>();", registration)

    def test_plugin_objects_wait_for_target_specific_bindings(self) -> None:
        sconstruct = (ROOT / "gdextension" / "SConstruct").read_text(
            encoding="utf-8"
        )
        self.assertIn('"build", "godot-cpp", requested_binding_tuple', sconstruct)
        self.assertIn("variant_dir=str(binding_variant_dir)", sconstruct)
        self.assertIn("duplicate=1", sconstruct)
        self.assertNotIn('ARGUMENTS["generate_bindings"]', sconstruct)
        self.assertIn('env.Requires(objects, env["LIBS"])', sconstruct)
        self.assertIn('plugin_root.name == "m_terrain"', sconstruct)
        self.assertIn('plugin_root.parent.name == "addons"', sconstruct)

    def test_web_scripts_fail_closed_on_source_and_output_scope(self) -> None:
        build_script = (ROOT / "scripts" / "build_web.sh").read_text(
            encoding="utf-8"
        )
        exporter = (ROOT / "scripts" / "export_web_smoke.py").read_text(
            encoding="utf-8"
        )
        receipt = (
            ROOT / "scripts" / "write_web_build_receipt.py"
        ).read_text(encoding="utf-8")
        self.assertIn("status --porcelain --untracked-files=normal", build_script)
        self.assertIn("output == build_root or build_root not in output.parents", exporter)
        self.assertIn('"--untracked-files=normal"', receipt)
        self.assertIn('"mterrain_tree": git("rev-parse", "HEAD^{tree}")', receipt)
        self.assertIn('"height_tile_apply": True', receipt)
        self.assertIn('"bounded_update_scheduler": False', receipt)
        self.assertIn('"binaryen": args.wasm_opt_version', receipt)
        self.assertIn('"wasm_features": wasm_features', receipt)
        self.assertIn('local wasm_features', build_script)
        self.assertIn('--enable-threads', build_script)
        self.assertIn('--enable-shared-everything', build_script)
        self.assertIn('shutil.rmtree(stage / ".godot", ignore_errors=True)', exporter)

    def test_runtime_smokes_require_an_initialized_height_tile(self) -> None:
        native_smoke = (ROOT / "tests" / "runtime_smoke" / "smoke.gd").read_text(
            encoding="utf-8"
        )
        web_smoke = (ROOT / "tests" / "web_smoke" / "main.gd").read_text(
            encoding="utf-8"
        )
        browser_runner = (ROOT / "scripts" / "run_web_smoke.py").read_text(
            encoding="utf-8"
        )
        for source in (native_smoke, web_smoke, browser_runner):
            self.assertIn("initialized_tile_samples=4489", source)
            self.assertIn("rejected_non_finite=1", source)
        self.assertIn('frame_data_url: capture.toDataURL("image/png")', browser_runner)
        self.assertIn('framebuffer_capture.write_bytes', browser_runner)
        for source in (native_smoke, web_smoke):
            self.assertIn('apply_height_tile"', source)
            self.assertIn("Vector2i(69, 69)", source)
            self.assertIn('set_terrain_size", Vector2i(8, 8)', source)
            self.assertIn('set_region_size", 4', source)
            self.assertIn("invalid_heights[0] = NAN", source)


if __name__ == "__main__":
    unittest.main()
