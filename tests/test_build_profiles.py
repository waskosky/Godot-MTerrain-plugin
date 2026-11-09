"""Source/capability parity and loadable manifest ownership across builders."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "gdextension"
SPEC = importlib.util.spec_from_file_location("mterrain_profiles", EXTENSION / "mterrain_build_profile.py")
PROFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILE)


class BuildProfileTests(unittest.TestCase):
    def test_native_full_keeps_every_source_and_editor_only_in_debug(self):
        all_sources = {str(p.relative_to(EXTENSION)) for p in (EXTENSION / "src").rglob("*.cpp")}
        debug = PROFILE.select_sources(EXTENSION, "full", "template_debug")
        self.assertEqual(set(debug["sources"]), all_sources | {"register_types.cpp"})
        self.assertEqual(debug["sources"].count("src/register.cpp"), 1)
        self.assertIn("MTERRAIN_EDITOR_ENABLED", debug["definitions"])
        self.assertNotIn("MTERRAIN_EDITOR_ENABLED", PROFILE.select_sources(EXTENSION, "runtime", "template_debug")["definitions"])
        for name in ("full", "runtime"):
            release = PROFILE.select_sources(EXTENSION, name, "template_release")
            self.assertFalse(any("/editor/" in p for p in release["sources"]))
            self.assertNotIn("MTERRAIN_EDITOR_ENABLED", release["definitions"])
            for group in PROFILE.NATIVE_GROUPS:
                self.assertTrue(any(p.startswith("src/" + group + "/") for p in release["sources"]))

    def test_bounded_profiles_keep_the_same_runtime_closure(self):
        core = PROFILE.select_sources(EXTENSION, "web_core", "template_debug")
        extended = PROFILE.select_sources(EXTENSION, "web_extended", "template_debug")
        self.assertEqual(core["sources"], extended["sources"])
        for source in core["sources"]:
            self.assertTrue((EXTENSION / source).is_file())
            self.assertFalse(any("/" + group + "/" in source for group in (*PROFILE.NATIVE_GROUPS, "editor")))
        self.assertNotIn("src/moctree.cpp", core["sources"])
        self.assertNotIn("src/mtool.cpp", core["sources"])
        self.assertIn("register_types.cpp", core["sources"])
        for selected in (core, extended):
            self.assertTrue({"MTERRAIN_CORE_ONLY", "MTERRAIN_MEMORY_ONLY_DEFAULT", "MTERRAIN_BOUNDED_RUNTIME", "MTERRAIN_SINGLE_THREADED"} <= set(selected["definitions"]))
            self.assertIn("MTERRAIN_PROFILE_" + selected["profile"].upper(), selected["definitions"])

    def test_unknown_profiles_and_targets_fail_before_selection(self):
        for profile, target in (("typo", "template_debug"), ("full", "typo")):
            with self.assertRaises(ValueError):
                PROFILE.select_sources(EXTENSION, profile, target)

    def test_manifest_names_the_actual_native_and_web_libraries(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "MTerrain.gdextension"
            for platform, arch, target, threads, library, key in (
                ("macos", "x86_64", "template_debug", True, "libMTerrain.macos.template_debug.x86_64.dylib", "macos.debug.x86_64"),
                ("macos", "arm64", "template_release", True, "libMTerrain.macos.template_release.arm64.dylib", "macos.release.arm64"),
                ("web", "wasm32", "template_debug", False, "libMTerrain.web.template_debug.wasm32.nothreads.wasm", "web.debug.wasm32.nothreads"),
            ):
                PROFILE.write_manifest(EXTENSION / "MTerrain.txt", output, platform, target, arch, library, threads=threads)
                text = output.read_text()
                self.assertEqual(text.count(key + " ="), 1)
                self.assertIn(key + ' = "res://mterrain/' + library + '"', text)
                self.assertIn('[icons]', text)
            debug_library = "libMTerrain.macos.template_debug.x86_64.dylib"
            release_library = "libMTerrain.macos.template_release.x86_64.dylib"
            (Path(folder) / debug_library).touch()
            PROFILE.write_manifest(EXTENSION / "MTerrain.txt", output, "macos", "template_debug", "x86_64", debug_library)
            PROFILE.write_manifest(EXTENSION / "MTerrain.txt", output, "macos", "template_release", "x86_64", release_library)
            self.assertIn('macos.debug.x86_64 = "res://mterrain/' + debug_library + '"', output.read_text())
            self.assertIn('macos.release.x86_64 = "res://mterrain/' + release_library + '"', output.read_text())
            before = output.read_bytes()
            with self.assertRaises(ValueError):
                PROFILE.write_manifest(EXTENSION / "MTerrain.txt", output, "macos", "template_debug", "x86_64", "../wrong.dylib")
            self.assertEqual(output.read_bytes(), before)

    @unittest.skipUnless(shutil.which("cmake"), "CMake configure coverage needs CMake")
    def test_cmake_rejects_unqualified_web_profiles(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(["cmake", "-S", str(EXTENSION), "-B", folder,
                                     "-DMTERRAIN_PROFILE=web_core"], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("use scripts/build_web.sh", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
