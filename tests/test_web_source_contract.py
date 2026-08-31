from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WebSourceContractTests(unittest.TestCase):
    def test_machine_readable_runtime_contract_matches_implementations(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_web_runtime_contract.py")],
            cwd=ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("MTERRAIN_WEB_RUNTIME_CONTRACT_OK", completed.stdout)
        contract = json.loads(
            (ROOT / "runtime" / "web_runtime_contract.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(contract["schema"], "mterrain-web-runtime-contract-v1")
        self.assertEqual(contract["contract_version"], 1)
        self.assertEqual(set(contract["profiles"]), {"web_core", "web_extended"})
        self.assertEqual(
            contract["profiles"]["web_extended"]["inherits"], "web_core"
        )

    def test_web_governance_docs_remain_standalone(self) -> None:
        for relative in (
            "AGENTS.md",
            "docs/WEB_RUNTIME_ROADMAP.md",
            "docs/WEB_RUNTIME_API.md",
            "docs/WEB_RELEASE_PROCESS.md",
            "docs/WEB_SUPPORT_MATRIX.md",
            "docs/WEB_RUNTIME_RC_NOTES.md",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIsNone(
                re.search(r"\b(?:rai|openverse|godot-light)\b", source, re.IGNORECASE),
                relative,
            )

    def test_toolchain_is_single_threaded_wasm32_godot_47(self) -> None:
        toolchains = {
            "web_core": json.loads(
                (ROOT / "tools" / "web_toolchain.json").read_text(
                    encoding="utf-8"
                )
            ),
            "web_extended": json.loads(
                (ROOT / "tools" / "web_extended_toolchain.json").read_text(
                    encoding="utf-8"
                )
            ),
        }
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
        for expected_profile, toolchain in toolchains.items():
            self.assertEqual(toolchain["schema"], "mterrain-web-toolchain-v1")
            self.assertEqual(
                toolchain["godot"]["version"],
                "4.7.stable.official.5b4e0cb0f",
            )
            self.assertEqual(toolchain["platform"], "web")
            self.assertEqual(toolchain["architecture"], "wasm32")
            self.assertEqual(toolchain["precision"], "single")
            self.assertFalse(toolchain["threads"])
            self.assertEqual(toolchain["profile"], expected_profile)
            self.assertEqual(toolchain["brotli_version"], "1.2.0")
            self.assertEqual(toolchain["brotli_quality"], 11)
            self.assertEqual(
                toolchain["binaryen_version"],
                "wasm-opt version 124",
            )
            self.assertEqual(toolchain["binaryen_commit"], "6d5fed324")
            self.assertEqual(
                toolchain["binding_profile"],
                "gdextension/web_core_build_profile.json",
            )
            self.assertEqual(actual_godot_cpp, toolchain["godot_cpp_commit"])
            self.assertEqual(toolchain["source_path_mapping"], "/mterrain")
            self.assertEqual(
                toolchain["receipt_timestamp"], "source_commit_epoch"
            )
        self.assertEqual(
            toolchains["web_extended"]["runtime_companion"],
            "runtime/web_extended_runtime.gd",
        )
        self.assertEqual(
            toolchains["web_extended"]["native_binding_profile_shared_with"],
            "web_core",
        )

        ci_toolchain = json.loads(
            (ROOT / "tools" / "ci_toolchain.json").read_text(encoding="utf-8")
        )
        self.assertEqual(ci_toolchain["schema"], "mterrain-ci-toolchain-v1")
        self.assertEqual(
            ci_toolchain["host"],
            {"os": "linux", "architecture": "x86_64"},
        )
        self.assertEqual(
            ci_toolchain["godot"]["version"],
            toolchains["web_core"]["godot"]["version"],
        )
        self.assertEqual(
            ci_toolchain["scons"]["version"],
            toolchains["web_core"]["scons_version"],
        )
        self.assertEqual(
            ci_toolchain["emsdk"]["version"],
            toolchains["web_core"]["emscripten_version"],
        )
        self.assertEqual(
            ci_toolchain["emsdk"]["commit"],
            toolchains["web_core"]["emsdk_commit"],
        )
        self.assertEqual(
            ci_toolchain["brotli"]["version"],
            toolchains["web_core"]["brotli_version"],
        )
        for category, field in (
            ("godot", "asset_sha256"),
            ("scons", "wheel_sha256"),
        ):
            self.assertRegex(ci_toolchain[category][field], r"\A[0-9a-f]{64}\Z")
        self.assertEqual(
            ci_toolchain["godot_source"]["commit"],
            toolchains["web_core"]["godot"]["commit"],
        )
        template = ci_toolchain["godot_source"]["template"]
        self.assertEqual(template["architecture"], "wasm32")
        self.assertFalse(template["threads"])
        self.assertTrue(template["dynamic_linking"])
        self.assertEqual(
            template["artifact"],
            "godot.web.template_debug.wasm32.nothreads.dlink.zip",
        )
        self.assertEqual(ci_toolchain["playwright"]["version"], "1.62.0")
        self.assertEqual(
            set(ci_toolchain["playwright"]["browsers"]),
            {"chromium", "firefox", "webkit"},
        )
        installations = ci_toolchain["playwright"]["linux_x86_64_installations"]
        self.assertEqual(set(installations), {"chromium", "firefox", "webkit"})
        for installation in installations.values():
            self.assertRegex(installation["tree_sha256"], r"\A[0-9a-f]{64}\Z")
            self.assertGreater(installation["regular_files"], 0)
            self.assertGreater(installation["total_file_bytes"], 0)
        for wheel in ci_toolchain["playwright"]["wheels"]:
            self.assertRegex(wheel["sha256"], r"\A[0-9a-f]{64}\Z")
        browser_receipt_writer = (
            ROOT / "scripts" / "write_browser_toolchain_receipt.py"
        ).read_text(encoding="utf-8")
        self.assertIn("installation_tree", browser_receipt_writer)
        self.assertIn("mterrain-browser-toolchain-receipt-v2", browser_receipt_writer)

    def test_web_core_profile_fails_closed(self) -> None:
        sconstruct = (ROOT / "gdextension" / "SConstruct").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'mterrain_profile in ("web_core", "web_extended") and env["threads"]',
            sconstruct,
        )
        self.assertIn('env["platform"] == "web"', sconstruct)
        self.assertIn(
            'web_source_mapping = web_source_root + "=/mterrain"', sconstruct
        )
        self.assertIn('"-ffile-prefix-map=" + web_source_mapping', sconstruct)
        self.assertIn('"-fdebug-prefix-map=" + web_source_mapping', sconstruct)
        self.assertIn('"-fmacro-prefix-map=" + web_source_mapping', sconstruct)
        self.assertIn('("moctree.cpp", "mtool.cpp")', sconstruct)
        for source_group in ("grass", "navmesh", "octmesh", "path", "hlod"):
            self.assertIn(f'Glob("src/{source_group}/*.cpp")', sconstruct)
        self.assertIn('"MTERRAIN_CORE_ONLY"', sconstruct)
        self.assertIn('"MTERRAIN_BOUNDED_RUNTIME"', sconstruct)
        self.assertIn('"MTERRAIN_SINGLE_THREADED"', sconstruct)
        self.assertIn('"MTERRAIN_PROFILE_WEB_EXTENDED"', sconstruct)
        self.assertIn('"MTERRAIN_PROFILE_WEB_CORE"', sconstruct)

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

    def test_native_regression_binding_profile_covers_full_source(self) -> None:
        profile_path = (
            ROOT / "gdextension" / "native_full_build_profile.json"
        )
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        enabled = set(profile["enabled_classes"])
        for required in (
            "EditorInterface",
            "EditorScript",
            "NavigationServer3D",
            "PhysicsServer3D",
            "RenderingServer",
            "WorkerThreadPool",
        ):
            self.assertIn(required, enabled)
        self.assertNotIn("EditorPlugin", enabled)
        self.assertNotIn("RenderingDevice", enabled)

        native_script = (
            ROOT / "scripts" / "run_native_regression_builds.sh"
        ).read_text(encoding="utf-8")
        profile_argument = (
            'build_profile="$ROOT_DIR/gdextension/'
            'native_full_build_profile.json"'
        )
        self.assertEqual(native_script.count(profile_argument), 2)
        self.assertIn("build_profile full template_debug", native_script)
        self.assertIn("build_profile full template_release", native_script)

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
        runtime_api = (
            ROOT / "gdextension" / "src" / "mterrain_runtime_api.cpp"
        ).read_text(encoding="utf-8")
        scheduler = (
            ROOT / "gdextension" / "src" / "mruntime_scheduler.cpp"
        ).read_text(encoding="utf-8")
        combined = implementation + runtime_api
        for method in (
            "get_runtime_bridge_api_version",
            "get_runtime_capabilities",
            "apply_height_tile",
            "queue_height_tile",
            "step_runtime_work",
            "cancel_runtime_work",
            "release_runtime_tile",
            "request_runtime_collision_focus",
            "configure_runtime_material",
        ):
            self.assertIn(method, header)
            self.assertIn(method, combined)
        self.assertIn("return 2;", implementation)
        self.assertNotIn("#if 0", implementation)
        self.assertIn("MAX_TILE_SIDE = 67", scheduler)
        self.assertIn("MAX_TILE_SAMPLES = 4489", scheduler)
        self.assertIn("std::isfinite", scheduler)
        self.assertIn("WORK_GENERATE_NORMALS", scheduler)
        self.assertIn("WORK_ROLLBACK_HEIGHTS", scheduler)
        self.assertIn("WORK_ROLLBACK_NORMALS", scheduler)
        self.assertIn("WORK_ROLLBACK_APPLY", scheduler)
        self.assertIn("remaining_samples >= normal_width", scheduler)
        self.assertIn("apply_region_cursor", scheduler)
        self.assertIn("rollback_apply_region_cursor", scheduler)
        self.assertIn("MAX_COMPLETED_RESULTS = 256", scheduler)
        self.assertIn('fail("coalesced"', scheduler)
        self.assertIn('collision["regions"]', scheduler)
        self.assertIn('runtime_region_collision_generation', scheduler)
        self.assertIn("collision_region_limit_exceeded", scheduler)
        self.assertIn("collision_focus_explicit", scheduler)
        self.assertIn("active_collision_regions", scheduler)
        self.assertIn("collision_memory_budget_exceeded", scheduler)
        self.assertIn("schedule_resident_release", scheduler)
        self.assertIn("longest_step_usec", scheduler)
        self.assertIn(
            'ERR_FAIL_COND_MSG(!input, "This build profile requires runtime_memory_only")',
            implementation,
        )
        grid = (ROOT / "gdextension" / "src" / "mgrid.h").read_text(
            encoding="utf-8"
        )
        grid_implementation = (
            ROOT / "gdextension" / "src" / "mgrid.cpp"
        ).read_text(encoding="utf-8")
        region = (ROOT / "gdextension" / "src" / "mregion.cpp").read_text(
            encoding="utf-8"
        )
        image = (ROOT / "gdextension" / "src" / "mimage.cpp").read_text(
            encoding="utf-8"
        )
        self.assertIn("bool runtime_memory_only = false", grid)
        self.assertIn("unload(mres,!grid->runtime_memory_only)", region)
        self.assertIn("runtime_mark_region_normals_dirty", grid)
        self.assertNotIn("runtime_loaded_region_count", grid)
        self.assertIn("if(save_before_unload)", image)
        for capability in (
            "heightfield_terrain",
            "visual_lod",
            "heightfield_collision",
            "compatibility_materials",
            "bounded_update_scheduler",
            "bounded_collision",
            "phase_timing_metrics",
            "scheduler_owned_visual_residency",
        ):
            self.assertIn(f'capabilities["{capability}"]', implementation)
        for topology_limit, value in (
            ("WEB_MAX_TERRAIN_QUADS_PER_AXIS", 256),
            ("WEB_MAX_TERRAIN_TOPOLOGY_POINTS", 65536),
            ("WEB_MAX_TERRAIN_REGIONS", 1024),
            ("WEB_MAX_VISUAL_RANGE_QUADS", 128),
        ):
            self.assertIn(f"{topology_limit} = {value}", implementation)
        self.assertIn("RenderingServer::get_singleton()->free_rid(point.instance)", grid_implementation)
        self.assertIn("#ifndef MTERRAIN_BOUNDED_RUNTIME", implementation)
        self.assertIn("#ifndef MTERRAIN_BOUNDED_RUNTIME", grid_implementation)
        self.assertIn('capabilities["api_stability"] = "experimental"', implementation)
        for phase in (
            "region_load",
            "preflight",
            "write_heights",
            "generate_normals",
            "texture_apply",
            "collision",
            "eviction",
            "rollback_heights",
            "rollback_normals",
            "rollback_apply",
        ):
            self.assertIn(f'"{phase}"', scheduler)
        self.assertIn('"shared_sample_mismatch"', scheduler)
        self.assertIn('"mterrain-runtime-phase-timings/v1"', scheduler)
        self.assertIn("runtime_lod_snapshot", grid)
        self.assertIn('"mterrain-runtime-visual-lod/v1"', grid_implementation)
        tile_apply = scheduler[
            scheduler.index("Dictionary MRuntimeScheduler::step") :
        ]
        forward_write = tile_apply.index(
            "if(work.phase == WORK_WRITE_HEIGHTS"
        )
        self.assertLess(
            tile_apply.index("grid->can_set_height_by_pixel"),
            forward_write,
        )
        self.assertLess(
            tile_apply.index("grid->can_update_normals"),
            forward_write,
        )
        self.assertIn('fail("normal_halo_not_resident"', tile_apply)
        self.assertLess(
            tile_apply.index("grid->update_normals"),
            tile_apply.index("grid->runtime_upload_region_ids"),
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
        self.assertIn('binding_profile_key = (', sconstruct)
        self.assertIn('"web_core"', sconstruct)
        self.assertIn("variant_dir=str(binding_variant_dir)", sconstruct)
        self.assertIn("duplicate=1", sconstruct)
        self.assertIn("env = binding_env.Clone()", sconstruct)
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
        self.assertIn('"bounded_update_scheduler": True', receipt)
        self.assertIn('"bounded_collision": True', receipt)
        self.assertIn('extended = args.profile == "web_extended"', receipt)
        self.assertIn('receipt["runtime_companion"]', receipt)
        self.assertIn('"binaryen": args.wasm_opt_version', receipt)
        self.assertIn('"wasm_features": wasm_features', receipt)
        self.assertIn('os.environ.get("SOURCE_DATE_EPOCH")', receipt)
        self.assertIn('"source_date_epoch": source_date_epoch', receipt)
        self.assertIn('local wasm_features', build_script)
        self.assertIn('--enable-threads', build_script)
        self.assertIn('--enable-shared-everything', build_script)
        self.assertIn('WEB_PROFILE="${2:-${MTERRAIN_WEB_PROFILE:-web_core}}"', build_script)
        self.assertIn('web_extended)', build_script)
        self.assertIn('shutil.rmtree(stage / ".godot", ignore_errors=True)', exporter)
        self.assertIn('custom_features="mterrain_{profile}"', exporter)
        self.assertIn('ROOT / "runtime" / "web_extended_runtime.gd"', exporter)
        self.assertIn('shutil.rmtree(stage / "fixtures"', exporter)

    def test_distribution_workflow_builds_both_profiles_before_release(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "web-runtime-distribution.yml"
        ).read_text(encoding="utf-8")
        for expected in (
            "submodules: recursive",
            "node --check tests/web_performance/evidence_bridge.js",
            "./scripts/build_web.sh all web_core",
            "./scripts/build_web.sh all web_extended",
            "./scripts/run_native_regression_builds.sh",
            "--verify-dir build/distribution",
            "needs:",
            "web-artifacts",
            "native-regressions",
            "hosted-browser-smoke",
            "./scripts/build_web_export_template.sh",
            "for browser in chromium firefox",
            '--browser "$browser"',
            "xvfb-run --auto-servernum",
            "--headed",
            "Retain pinned Playwright WebKit diagnostic",
            "webkit-diagnostic",
            "scripts/record_web_hosted_correctness.py",
            "REQUESTED_DISTRIBUTION_VERSION",
            "A final-version stable candidate must be built from master.",
            "Stable tags require candidate-bound physical",
            "gh release create",
            "--draft",
            "gh release edit",
            "gh release verify-asset",
        ):
            self.assertIn(expected, workflow)
        self.assertIn("permissions:\n      contents: write", workflow)
        self.assertNotRegex(workflow, r"uses: [^\n]+@(?![0-9a-f]{40})")

        packager = (
            ROOT / "scripts" / "package_web_release.py"
        ).read_text(encoding="utf-8")
        self.assertIn('RUNTIME_CONTRACT_RELATIVE = "runtime/web_runtime_contract.json"', packager)
        self.assertIn('"mterrain-web-runtime-contract-v1"', packager)
        self.assertIn('"web-runtime-v0.1.0-rc.1"', packager)
        self.assertIn("runtime_contract_output", packager)
        self.assertIn("PERFORMANCE_BUDGETS_RELATIVE", packager)
        self.assertIn("PERFORMANCE_CALIBRATION_RELATIVE", packager)
        self.assertIn("RELEASE_GATE_RELATIVE", packager)
        self.assertIn("PERFORMANCE_FIXTURE_FILES", packager)
        self.assertIn("Receipt source mismatch", packager)
        self.assertIn("Receipt Brotli record mismatch", packager)

    def test_stable_release_gate_stays_fail_closed_without_physical_evidence(self) -> None:
        budgets = json.loads(
            (ROOT / "tools" / "web_performance_budgets.json").read_text(
                encoding="utf-8"
            )
        )
        gate = json.loads(
            (ROOT / "tools" / "web_release_gate.json").read_text(encoding="utf-8")
        )
        calibration = json.loads(
            (ROOT / "tools" / "web_performance_calibration.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(budgets["schema"], "mterrain-web-performance-budgets-v1")
        self.assertNotIn("calibration", budgets)
        self.assertEqual(
            calibration["schema"], "mterrain-web-performance-calibration-v1"
        )
        self.assertFalse(calibration["release_gate_eligible"])
        self.assertEqual(calibration["approved_evidence_sha256"], [])
        self.assertEqual(
            calibration["status"],
            "post_build_candidate_bound_approval_required",
        )
        self.assertEqual(
            set(budgets["fixture"]["runtime_profiles"]),
            {"web_core", "web_extended"},
        )
        for limits in budgets["profiles"].values():
            self.assertGreater(limits["maximum_compressed_runtime_export_bytes"], 0)
        self.assertEqual(gate["schema"], "mterrain-web-release-gate-v1")
        self.assertEqual(
            set(gate["hosted_correctness"]["browsers"]),
            {"playwright_chromium", "playwright_firefox"},
        )
        lanes = gate["stable_profiles"]["web_core"]["performance_lanes"]
        self.assertEqual(
            set(lanes),
            {
                "headed_chrome_desktop",
                "headed_firefox_desktop",
                "safari_macos",
                "android_chrome",
                "ios_safari",
            },
        )
        self.assertEqual(lanes["safari_macos"]["browser_products"], ["apple_safari"])
        self.assertNotIn(
            "playwright_webkit_not_safari",
            lanes["safari_macos"]["browser_products"],
        )
        with tempfile.TemporaryDirectory() as temporary:
            command = [
                sys.executable,
                str(ROOT / "scripts" / "verify_web_release_gate.py"),
                "--evidence-dir",
                temporary,
            ]
            audit = subprocess.run(
                command,
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(audit.returncode, 0, audit.stdout)
            self.assertIn("MTERRAIN_WEB_RELEASE_GATE_OPEN", audit.stdout)
            stable = subprocess.run(
                [*command, "--require-stable"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertNotEqual(stable.returncode, 0, stable.stdout)
            self.assertIn("stable-release gate remains open", stable.stdout)

            approval_path = Path(temporary) / "approved-calibration.json"
            approval_path.write_text(
                json.dumps(
                    {
                        "schema": "mterrain-web-performance-calibration-v1",
                        "status": "reviewed_candidate_bound_evidence",
                        "release_gate_eligible": True,
                        "threshold_contract_sha256": calibration[
                            "threshold_contract_sha256"
                        ],
                        "candidate_release": {
                            "version": "web-runtime-vNEXT",
                            "release_index_sha256": "a" * 64,
                        },
                        "approved_evidence": [
                            {
                                "name": "evidence.json",
                                "profile": "web_core",
                                "lane": "headed_chrome_desktop",
                                "sha256": "b" * 64,
                            }
                        ],
                        "approved_evidence_sha256": ["b" * 64],
                        "review": {
                            "operator": "release reviewer",
                            "approved_at": "2026-08-30T12:00:00+00:00",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            unbound = subprocess.run(
                [*command, "--calibration", str(approval_path)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(unbound.returncode, 0, unbound.stdout)
            self.assertIn(
                "performance calibration is not bound to a verified candidate",
                unbound.stdout,
            )

        approver = (
            ROOT / "scripts" / "approve_web_performance_calibration.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"release_index_sha256": next(iter(candidate_indices))', approver)
        self.assertIn("valid_performance_evidence", approver)
        packager = (ROOT / "scripts" / "package_web_release.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("candidate-bound approval is post-build evidence", packager)
        promotion = (
            ROOT / "scripts" / "prepare_web_stable_promotion.py"
        ).read_text(encoding="utf-8")
        self.assertIn('for profile in ("web_core", "web_extended")', promotion)
        self.assertIn('"--require-stable"', promotion)
        self.assertIn("STABLE_PROMOTION_SHA256SUMS", promotion)
        self.assertIn("MTERRAIN_WEB_STABLE_PROMOTION_VERIFY_OK", promotion)
        self.assertIn('"--verify-dir requires the verified --prior-dir"', promotion)

    def test_performance_and_whole_bundle_rollback_harnesses_are_bounded(self) -> None:
        performance = (ROOT / "tests" / "web_performance" / "main.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn("ROUTE_REPETITIONS := 4", performance)
        self.assertIn("ROUTE_REGION_SIDE := 8", performance)
        self.assertIn("SAMPLE_BUDGET := 512", performance)
        self.assertIn('"sample_ops_per_step": SAMPLE_BUDGET', performance)
        self.assertIn('"region_ops_per_step": REGION_BUDGET', performance)
        self.assertIn("MTERRAIN_WEB_PERFORMANCE_OK", performance)
        self.assertIn("scheduler_metrics", performance)
        self.assertIn("_awaiting_collision", performance)
        self.assertIn("_request_current_collision", performance)
        self.assertIn('"runtime_profile": _runtime_profile', performance)
        exporter = (
            ROOT / "scripts" / "export_web_smoke.py"
        ).read_text(encoding="utf-8")
        self.assertIn("fixture_source_context", exporter)
        self.assertIn("runtime_export_payload", exporter)
        self.assertIn("gzip-9-mtime-0-per-file", exporter)
        bridge = (
            ROOT / "tests" / "web_performance" / "evidence_bridge.js"
        ).read_text(encoding="utf-8")
        self.assertIn("mterrain-browser-capture-v1", bridge)
        self.assertIn("mterrain_performance_context.json", bridge)
        self.assertIn("Download MTerrain evidence", bridge)
        self.assertIn("response_status", bridge)
        self.assertIn("response.ok", bridge)

        rollback = (ROOT / "tests" / "web_rollback" / "main.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn("MTERRAIN_WEB_ROLLBACK_OK", rollback)
        self.assertIn("eviction_recovery=1", rollback)
        self.assertIn("web_extended_runtime.gd", rollback)
        preparer = (
            ROOT / "scripts" / "prepare_web_rollback_gate.py"
        ).read_text(encoding="utf-8")
        self.assertIn("safe_archive_members", preparer)
        self.assertIn('["candidate", "prior"]', preparer)
        recorder = (
            ROOT / "scripts" / "record_web_rollback_evidence.py"
        ).read_text(encoding="utf-8")
        self.assertIn("candidate_time >= prior_time", recorder)
        self.assertIn("file-level substitution", recorder)
        self.assertIn('"origin": "attested_physical_browser_rollback"', recorder)
        self.assertIn('choices=("web_core", "web_extended")', recorder)

        stable_gate = (
            ROOT / "scripts" / "verify_web_release_gate.py"
        ).read_text(encoding="utf-8")
        self.assertIn("mterrain-web-hosted-correctness-evidence-v1", stable_gate)
        self.assertIn('parser.add_argument("--candidate-dir"', stable_gate)
        self.assertIn('parser.add_argument("--prior-dir"', stable_gate)
        self.assertIn("candidate_contract[\"bundle_sha256\"]", stable_gate)
        self.assertIn('prior_contract["bundle_sha256"]', stable_gate)
        self.assertIn('candidate["performance_fixture_sources"]', stable_gate)
        self.assertIn("timestamp_before", stable_gate)
        self.assertIn('session.get("manifest_sha256")', stable_gate)
        self.assertIn("software_renderer", stable_gate)
        evidence_common = (
            ROOT / "scripts" / "web_evidence_common.py"
        ).read_text(encoding="utf-8")
        self.assertIn("microsoft basic render", evidence_common)
        self.assertIn("lavapipe", evidence_common)
        self.assertIn("compressed_runtime_export_bytes", evidence_common)
        self.assertIn("runtime_export_payload_valid", evidence_common)
        self.assertIn("SCHEDULER_PHASES", evidence_common)
        self.assertIn("scheduler_metrics_valid", evidence_common)

    def test_lod_edge_meshes_cover_every_boolean_combination(self) -> None:
        configuration = (ROOT / "gdextension" / "src" / "mconfig.h").read_text(
            encoding="utf-8"
        )
        chunks = (ROOT / "gdextension" / "src" / "mchunks.cpp").read_text(
            encoding="utf-8"
        )
        grid = (ROOT / "gdextension" / "src" / "mgrid.cpp").read_text(
            encoding="utf-8"
        )
        self.assertIn("#define M_MAX_EDGE 16", configuration)
        for name in ("M_LR", "M_TB", "M_LRT", "M_LRB", "M_LTB", "M_RTB"):
            self.assertIn(name, configuration)
            self.assertIn(f"edge == {name}", chunks)
            self.assertIn(f"return {name};", grid)
        self.assertNotIn("Error Can not find correct Edge", grid)

    def test_release_archives_are_normalized_and_deterministic(self) -> None:
        package_path = ROOT / "scripts" / "package_web_release.py"
        specification = importlib.util.spec_from_file_location(
            "mterrain_package_web_release", package_path
        )
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        files = {
            "candidate/LICENSE": b"license\n",
            "candidate/mterrain/test.wasm": b"wasm\x00fixture",
        }
        first = module.archive_bytes(files, 1_700_000_000)
        second = module.archive_bytes(files, 1_700_000_000)
        self.assertEqual(first, second)
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "candidate.tar.gz"
            archive.write_bytes(first)
            self.assertEqual(
                module.safe_archive_members(archive, 1_700_000_000), files
            )

    def test_browser_receipt_tree_digest_covers_delegated_files(self) -> None:
        receipt_path = ROOT / "scripts" / "write_browser_toolchain_receipt.py"
        specification = importlib.util.spec_from_file_location(
            "mterrain_browser_receipt", receipt_path
        )
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            installation = Path(temporary) / "browser-1"
            delegated = installation / "lib" / "delegated.so"
            delegated.parent.mkdir(parents=True)
            delegated.write_bytes(b"first browser payload")
            first = module.installation_tree(installation)
            delegated.write_bytes(b"changed browser payload")
            second = module.installation_tree(installation)
            self.assertNotEqual(first["tree_sha256"], second["tree_sha256"])

    def test_runtime_export_payload_contract_is_complete_and_tamper_evident(self) -> None:
        common_path = ROOT / "scripts" / "web_evidence_common.py"
        specification = importlib.util.spec_from_file_location(
            "mterrain_web_evidence_common", common_path
        )
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        files = [
            {
                "name": name,
                "sha256": "a" * 64,
                "raw_bytes": 100,
                "gzip_bytes": 50,
            }
            for name in sorted(module.RUNTIME_EXPORT_REQUIRED_FILES)
        ]
        payload = {
            "schema": "mterrain-web-runtime-export-payload-v1",
            "compression": "gzip-9-mtime-0-per-file",
            "instrumentation_excluded": True,
            "file_count": len(files),
            "raw_bytes": len(files) * 100,
            "gzip_bytes": len(files) * 50,
            "files": files,
        }
        self.assertTrue(module.runtime_export_payload_valid(payload))
        payload["gzip_bytes"] += 1
        self.assertFalse(module.runtime_export_payload_valid(payload))

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
        native_runner = (
            ROOT / "scripts" / "run_native_core_smoke.sh"
        ).read_text(encoding="utf-8")
        for source in (native_smoke, web_smoke, browser_runner):
            self.assertIn("initialized_tile_samples=4489", source)
            self.assertIn("rejected_non_finite=1", source)
            self.assertIn("scheduler_visual=1", source)
        self.assertIn('frame_data_url: capture.toDataURL("image/png")', browser_runner)
        self.assertIn('framebuffer_capture.write_bytes', browser_runner)
        self.assertIn('"harness_error_type": type(error).__name__', browser_runner)
        for source in (native_smoke, web_smoke):
            self.assertIn('apply_height_tile"', source)
            self.assertIn("Vector2i(69, 69)", source)
            self.assertIn('set_terrain_size", Vector2i(8, 8)', source)
            self.assertIn('set_region_size", 4', source)
            self.assertIn("invalid_heights[0] = NAN", source)
            self.assertIn("seam-left", source)
            self.assertIn("PhysicsRayQueryParameters3D.create", source)
            self.assertIn("Texture2DArray.new()", source)
        for source in (native_smoke, web_smoke):
            self.assertIn("shared_sample_mismatch", source)
            self.assertIn("mterrain-runtime-visual-lod/v1", source)
            self.assertIn("phase_timings", source)
        self.assertIn("teleport-a", native_smoke)
        self.assertIn("max_resident_tiles\": 2", native_smoke)
        self.assertIn('EXPECTED_PROFILE="${2:-${MTERRAIN_EXPECTED_PROFILE:-web_core}}"', native_runner)
        self.assertIn('MTERRAIN_EXPECTED_PROFILE="$EXPECTED_PROFILE"', native_runner)

    def test_full_profile_smoke_requires_native_feature_registration(self) -> None:
        smoke = (
            ROOT / "tests" / "full_profile_smoke" / "smoke.gd"
        ).read_text(encoding="utf-8")
        for class_name in (
            "MOctree",
            "MGrass",
            "MNavigationRegion3D",
            "MPath",
            "MHlod",
        ):
            self.assertIn(f'&"{class_name}"', smoke)
        self.assertIn("MTERRAIN_FULL_PROFILE_SMOKE_OK", smoke)

    def test_compatibility_material_is_bounded_and_texture_optional(self) -> None:
        shader = (ROOT / "start_opengl.gdshader").read_text(encoding="utf-8")
        forward_shader = (ROOT / "start.gdshader").read_text(encoding="utf-8")
        runtime_api = (
            ROOT / "gdextension" / "src" / "mterrain_runtime_api.cpp"
        ).read_text(encoding="utf-8")
        for shader_source in (shader, forward_shader):
            self.assertIn("mterrain_surface_textures_enabled", shader_source)
            self.assertIn("sampler2DArray runtime_surface_layers", shader_source)
            self.assertIn("semantic_color", shader_source)
            self.assertIn("ALBEDO = surface_color", shader_source)
            self.assertIn("if(weight_total > 0.0001)", shader_source)
        self.assertIn("surface_layer_count > 4", runtime_api)
        self.assertIn("surface_layers->get_layers() > 16", runtime_api)
        self.assertIn("missing_texture_readable", runtime_api)
        self.assertIn("runtime_material_shader_contract", runtime_api)
        material_source = (
            ROOT / "gdextension" / "src" / "mterrain_material.cpp"
        ).read_text(encoding="utf-8")
        self.assertIn("uniforms[-1] = defaults", material_source)

    def test_extended_runtime_keeps_capabilities_data_first_and_bounded(self) -> None:
        runtime = (
            ROOT / "runtime" / "web_extended_runtime.gd"
        ).read_text(encoding="utf-8")
        smoke = (
            ROOT / "tests" / "extended_runtime_smoke" / "smoke.gd"
        ).read_text(encoding="utf-8")
        for method in (
            "queue_foliage",
            "queue_navigation",
            "queue_path",
            "queue_mesh_hlod",
            "step_runtime_work",
            "release_projection",
        ):
            self.assertIn(f"func {method}", runtime)
        self.assertIn('"runtime_navigation_baking": false', runtime)
        self.assertIn('"runtime_curve_deformation": false', runtime)
        self.assertIn('"allow_in_memory_resources": false', runtime)
        self.assertIn("MAX_FOLIAGE_LIMIT := 8192", runtime)
        self.assertIn("MAX_MESH_INDICES := 262144", runtime)
        self.assertIn("MAX_NAVIGATION_INDICES := 65536", runtime)
        self.assertIn("MAX_HLOD_LEVELS := 4", runtime)
        self.assertIn("MAX_ALLOWED_RESOURCE_PATHS := 256", runtime)
        self.assertIn("MAX_RESULT_RECEIPTS := 256", runtime)
        self.assertIn("hlod_total_vertex_limit", runtime)
        self.assertIn("hlod_total_index_limit", runtime)
        self.assertIn("navigation_index_out_of_bounds", runtime)
        self.assertIn("hlod_hysteresis_m", runtime)
        self.assertIn("installed_projection_limit", runtime)
        self.assertIn("resource_policy_in_use", runtime)
        self.assertIn("work_key_conflict", runtime)
        self.assertIn('path.begins_with("res://")', runtime)
        self.assertIn("if allowlist.is_empty() or path not in allowlist", runtime)
        self.assertNotIn("Thread.new", runtime)
        self.assertNotIn("bake_from_source_geometry_data", runtime)
        self.assertIn("NavigationServer3D.map_get_path", smoke)
        self.assertIn("MTERRAIN_WEB_EXTENDED_SMOKE_OK", smoke)

    def test_extended_export_fixtures_include_their_source_resources(self) -> None:
        ignore_rules = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!tests/web_smoke/fixtures/*.obj", ignore_rules)
        for fixture in (
            "grass_cluster.obj",
            "road_strip.obj",
            "rock_near.obj",
            "rock_far.obj",
        ):
            source = ROOT / "tests" / "web_smoke" / "fixtures" / fixture
            import_metadata = source.with_suffix(source.suffix + ".import")
            self.assertTrue(source.is_file(), fixture)
            self.assertTrue(import_metadata.is_file(), import_metadata.name)


if __name__ == "__main__":
    unittest.main()
