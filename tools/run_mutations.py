#!/usr/bin/env python3
"""AUD-039 mutation testing: one mutant at a time on a separate build dir.

Each mutant is a minimal source patch applied to an isolated source copy,
built into a separate directory, and probed by the detector audit case run
against the mutant binaries. A mutant counts as KILLED only when the detector
reports a semantic FAIL on the mutant and PASS on the baseline control.
Compile errors/timeouts are recorded, never counted as semantic kills.
Sources are restored (hash-verified) after every mutant.
"""
from __future__ import annotations
import importlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tests" / "acceptance"))  # audit_cases/lib
import audit_cases  # noqa: E402
from audit_lib import make_result, run  # noqa: E402

ENGINE_ROOT = HERE.parent

MUTANTS = [
    {"id": "MUT-01", "title": "Bypass the entire creative look",
     "patches": [("engine/src/look.cpp",
                  "    if (amount <= 0.0) return; // amount=0 bypasses the look entirely",
                  "    if (amount <= 0.0) return; // amount=0 bypasses the look entirely\n    return; // MUT-01")],
     "detector": "AUD-005"},
    {"id": "MUT-02", "title": "Swap red/blue LUT input channels",
     "patches": [('engine/src/look.cpp', '            const float r0 = clamp01f(px[i]);\n            const float g0 = clamp01f(px[i + 1]);\n            const float b0 = clamp01f(px[i + 2]);', '            const float r0 = clamp01f(px[i + 2]); // MUT-02\n            const float g0 = clamp01f(px[i + 1]);\n            const float b0 = clamp01f(px[i]); // MUT-02')],
     "detector": "AUD-006"},
    {"id": "MUT-03", "title": "Replace trilinear with nearest-corner",
     "patches": [('engine/src/look.cpp', '            uint32_t r_lo = uint32_t(fr);\n            uint32_t g_lo = uint32_t(fg);\n            uint32_t b_lo = uint32_t(fb);', '            uint32_t r_lo = uint32_t(fr + 0.5f); if (r_lo >= n) r_lo = n - 1; // MUT-03\n            uint32_t g_lo = uint32_t(fg + 0.5f); if (g_lo >= n) g_lo = n - 1;\n            uint32_t b_lo = uint32_t(fb + 0.5f); if (b_lo >= n) b_lo = n - 1;\n            // MUT-03 zero interpolation weights below'), ('engine/src/look.cpp', '            const float tr = fr - float(r_lo);\n            const float tg = fg - float(g_lo);\n            const float tb = fb - float(b_lo);', '            const float tr = 0.0f; // MUT-03\n            const float tg = 0.0f; // MUT-03\n            const float tb = 0.0f; // MUT-03')],
     "detector": "AUD-008"},
    {"id": "MUT-04", "title": "Replace trilinear with valid tetrahedral",
     "patches": [('engine/src/look.cpp', '            for (int c = 0; c < 3; c++) {\n                const float c000 = at(r_lo, g_lo, b_lo, c);\n                const float c100 = at(r_hi, g_lo, b_lo, c);\n                const float c010 = at(r_lo, g_hi, b_lo, c);\n                const float c110 = at(r_hi, g_hi, b_lo, c);\n                const float c001 = at(r_lo, g_lo, b_hi, c);\n                const float c101 = at(r_hi, g_lo, b_hi, c);\n                const float c011 = at(r_lo, g_hi, b_hi, c);\n                const float c111 = at(r_hi, g_hi, b_hi, c);\n                const float c00 = c000 + (c100 - c000) * tr;\n                const float c10 = c010 + (c110 - c010) * tr;\n                const float c01 = c001 + (c101 - c001) * tr;\n                const float c11 = c011 + (c111 - c011) * tr;\n                const float c0 = c00 + (c10 - c00) * tg;\n                const float c1 = c01 + (c11 - c01) * tg;\n                const float looked = c0 + (c1 - c0) * tb;\n                // Amount blend in the encoded look domain (docs/03 section 3.5).\n                px[i + c] = float(ia * px[i + c] + a * looked);\n            }', '            // MUT-04: valid tetrahedral interpolation (6-tet scheme)\n            auto corner = [&](uint32_t r, uint32_t g, uint32_t b,\n                              float out[3]) {\n                out[0] = at(r, g, b, 0); out[1] = at(r, g, b, 1);\n                out[2] = at(r, g, b, 2);\n            };\n            float c000[3], c100[3], c010[3], c001[3], c110[3], c011[3], c101[3], c111[3];\n            corner(r_lo, g_lo, b_lo, c000); corner(r_hi, g_lo, b_lo, c100);\n            corner(r_lo, g_hi, b_lo, c010); corner(r_lo, g_lo, b_hi, c001);\n            corner(r_hi, g_hi, b_lo, c110); corner(r_lo, g_hi, b_hi, c011);\n            corner(r_hi, g_lo, b_hi, c101); corner(r_hi, g_hi, b_hi, c111);\n            const float *v0 = c000, *v1, *v2, *v3 = c111;\n            float w0, w1, w2, w3;\n            if (tr > tg) {\n                if (tg > tb)      { v1 = c100; v2 = c110; w0 = 1-tr; w1 = tr-tg; w2 = tg-tb; w3 = tb; }\n                else if (tr > tb) { v1 = c100; v2 = c101; w0 = 1-tr; w1 = tr-tb; w2 = tb-tg; w3 = tg; }\n                else              { v1 = c001; v2 = c101; w0 = 1-tb; w1 = tb-tr; w2 = tr-tg; w3 = tg; }\n            } else {\n                if (tg > tb) {\n                    if (tr > tb)  { v1 = c010; v2 = c110; w0 = 1-tg; w1 = tg-tr; w2 = tr-tb; w3 = tb; }\n                    else          { v1 = c010; v2 = c011; w0 = 1-tg; w1 = tg-tb; w2 = tb-tr; w3 = tr; }\n                } else            { v1 = c001; v2 = c011; w0 = 1-tb; w1 = tb-tg; w2 = tg-tr; w3 = tr; }\n            }\n            for (int c = 0; c < 3; c++) {\n                const float looked = w0 * v0[c] + w1 * v1[c] + w2 * v2[c] + w3 * v3[c];\n                px[i + c] = float(ia * px[i + c] + a * looked);\n            }')],
     "detector": "AUD-007"},
    {"id": "MUT-05", "title": "Amount squared instead of linear blend",
     "patches": [("engine/src/look.cpp",
                  "    const double a = std::min(amount, 1.0);",
                  "    const double a = std::min(amount * amount, 1.0); // MUT-05")],
     "detector": "AUD-006"},
    {"id": "MUT-06", "title": "Apply the look in linear domain (before encode)",
     "patches": [('engine/src/render.cpp', '        const double t_en = now_ms();', '        if (request.look) cube3d_apply(*request.look, dev.buffer, request.look_amount, cancel); // MUT-06 linear look\n        const double t_en = now_ms();'), ('engine/src/render.cpp', '        // 5) Look + amount blend in the encoded domain. amount=0 bypasses.\n        if (request.look) cube3d_apply(*request.look, dev.buffer, request.look_amount, cancel);', '        // MUT-06 encoded-domain look removed')],
     "detector": "AUD-009"},
    {"id": "MUT-07", "title": "Skip the sRGB decode after look (double encode at output)",
     "patches": [('engine/src/render.cpp', '        // 6) Decode sRGB back to linear for geometry.\n        for_each_chunk(dev.buffer.data.size(), cancel, "decode.chunk", [&](size_t begin, size_t end) {\n            for (size_t i = begin; i < end; ++i) {\n                dev.buffer.data[i] = srgb_decode_f(dev.buffer.data[i]);\n            }\n        });\n        dev.buffer.domain = Domain::LinearBounded;', '        // MUT-07: decode removed; final encode encodes twice')],
     "detector": "AUD-009"},
    {"id": "MUT-08", "title": "Ignore exposure EV",
     "patches": [("engine/src/render.cpp",
                  "    if (request.exposure_ev != 0.0) {",
                  "    if (false) { // MUT-08")],
     "detector": "AUD-015"},
    {"id": "MUT-09", "title": "Ignore custom WB multipliers",
     "patches": [("engine/src/raw_adapter.cpp",
                  "        raw.imgdata.params.user_mul[0] = float(config.wb_multipliers[0]);\n"
                  "        raw.imgdata.params.user_mul[1] = float(config.wb_multipliers[1]);\n"
                  "        raw.imgdata.params.user_mul[2] = float(config.wb_multipliers[2]);\n"
                  "        raw.imgdata.params.user_mul[3] = float(config.wb_multipliers[3]);",
                  "        raw.imgdata.params.user_mul[0] = 1.0f; // MUT-09\n"
                  "        raw.imgdata.params.user_mul[1] = 1.0f;\n"
                  "        raw.imgdata.params.user_mul[2] = 1.0f;\n"
                  "        raw.imgdata.params.user_mul[3] = 1.0f;")],
     "detector": "AUD-013"},
    {"id": "MUT-10", "title": "Return stale pixels after recipe changes",
     "patches": [('engine/src/c_api.cpp', '        *out_image = reinterpret_cast<pe_image *>(image.release());', '        static const Image stale = *image; // MUT-10\n        image->rgba = stale.rgba;\n        *out_image = reinterpret_cast<pe_image *>(image.release());')],
     "detector": "AUD-022"},
    {"id": "MUT-11", "title": "Drop the ICC profile from exported JPEG",
     "patches": [("engine/src/jpeg_encoder.cpp",
                  "    if (!icc_marker.empty()) {",
                  "    if (false) { // MUT-11")],
     "detector": "AUD-023"},
    {"id": "MUT-12", "title": "Allow overwrite of an existing output",
     "patches": [("cli/main.cpp",
                  "    if (path_exists(a.out)) {\n"
                  "        std::fprintf(stderr, \"error: output path already exists: %s\\n\", a.out.c_str());\n"
                  "        return 1;\n"
                  "    }\n"
                  "    if (!open_engine_and_source(a, &engine, &source)) return 1;",
                  "    if (!open_engine_and_source(a, &engine, &source)) return 1; // MUT-12 early check removed"),
                 ("cli/main.cpp",
                  "utf8_rename_no_replace(staging, a.out)",
                  "(utf8_remove(a.out), utf8_rename(staging, a.out)) /* MUT-12 */")],
     "detector": "AUD-027"},
    {"id": "MUT-13", "title": "Swap 90 CW and 270 CW rotations",
     "patches": [("engine/src/geometry.cpp",
                  "        // rotate 90 degrees clockwise: new(x', y') = old(y', h-1-x')\n"
                  "        remap(buffer, nw, nh, [&](uint32_t x, uint32_t y, float *dst) {\n"
                  "            const size_t si = (size_t(h - 1 - x) * w + y) * 3;",
                  "        // MUT-13 swapped\n"
                  "        remap(buffer, nw, nh, [&](uint32_t x, uint32_t y, float *dst) {\n"
                  "            const size_t si = (size_t(x) * w + (w - 1 - y)) * 3;"),
                 ("engine/src/geometry.cpp",
                  "        // rotate 270 degrees clockwise (90 CCW): new(x', y') = old(w-1-y', x')\n"
                  "        remap(buffer, nw, nh, [&](uint32_t x, uint32_t y, float *dst) {\n"
                  "            const size_t si = (size_t(x) * w + (w - 1 - y)) * 3;",
                  "        // MUT-13 swapped\n"
                  "        remap(buffer, nw, nh, [&](uint32_t x, uint32_t y, float *dst) {\n"
                  "            const size_t si = (size_t(h - 1 - x) * w + y) * 3;")],
     "detector": "AUD-019"},
    {"id": "MUT-14", "title": "Ignore the cancellation token",
     "patches": [('engine/src/cancel_flag.h', '    bool is_cancelled() const { return flag_.load(std::memory_order_relaxed); }', '    bool is_cancelled() const { return false; } // MUT-14 ignore requests')],
     "detector": "AUD-031"},
]

HARNESS_MUTANT_15 = {
    "id": "MUT-15", "title": "Comparator skips non-finite samples (harness mutant)",
    "detector": "AUD-002",
}


def run_mutations(ctx, artifacts: Path, results: list, baseline_results=()):
    import hashlib
    import difflib
    artifacts = artifacts.resolve()
    environment_path = artifacts / "environment.json"
    environment = json.loads(environment_path.read_text(encoding="utf-8"))
    # This module is imported only when AUD-039 starts. Retain both the initial
    # snapshot hash and the exact module revision actually executed.
    relative_module = str(Path(__file__).relative_to(ctx.root))
    environment.setdefault("executionSourceUpdates", {})[relative_module] = {
        "initialSha256": environment.get("sourceHashes", {}).get(relative_module),
        "executedSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "reason": "mutation detector scope finalized before AUD-039 module was imported; production sources/thresholds unchanged"}
    environment_path.write_text(json.dumps(environment, indent=2), encoding="utf-8")
    isolated = artifacts / "mutations" / "source"
    isolated.mkdir(parents=True)
    for folder in ("engine", "cli", "tests", "contracts", "cmake", "third_party"):
        shutil.copytree(ctx.root / folder, isolated / folder,
                        ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(ctx.root / "CMakeLists.txt", isolated / "CMakeLists.txt")
    mut_build = artifacts / "mutations" / "build"
    configure = run(["cmake", "-G", "Ninja", "-B", mut_build, "-S", isolated,
                     "-DCMAKE_BUILD_TYPE=Release", "-DPHOTO_ENGINE_AUDIT_FAULTS=ON", "-DDOCS_PACKAGE_DIR=" +
                     str(ctx.root.parent / "raw_photo_app_rnd_v0.1")], cwd=ctx.root)
    (artifacts / "mutations" / "configure.log").write_text(
        configure["stdout"] + configure["stderr"], encoding="utf-8")
    if configure["exit"] != 0:
        return results + [make_result("AUD-039", "configure", "isolated mutant build",
                          "NOT_RUN", reason="configuration failed; see mutations/configure.log")]
    controls = {}
    for row in baseline_results:
        controls.setdefault(row["caseId"], []).append(row)
    for mutant in MUTANTS:
        mid, detector = mutant["id"], mutant["detector"]
        mdir = artifacts / "mutations" / mid
        mdir.mkdir(parents=True)
        print(f"[MUTATION  ] {mid}: control {detector}", flush=True)
        if detector not in controls:
            cdir = artifacts / "mutations" / "controls" / detector
            cdir.mkdir(parents=True)
            cctx = audit_cases.AuditContext(ctx.root, cdir, ctx.policy,
                                           ctx.fixtures, ctx.looks, ctx.oracle_path)
            cctx.cli, cctx.harness, cctx.ref_adapter = ctx.cli, ctx.harness, ctx.ref_adapter
            try:
                controls[detector] = audit_cases.CASES[detector](cctx)
            except Exception as exc:
                controls[detector] = [make_result(detector, "runner", "control",
                                                  "FAIL", reason=str(exc))]
            (cdir / "results.json").write_text(json.dumps(controls[detector], indent=2),
                                               encoding="utf-8")
        control = controls[detector]
        if not control or any(r["status"] != "PASS" for r in control):
            results.append(make_result("AUD-039", f"{mid}/control", mutant["title"],
                            "NOT_RUN", reason="baseline detector does not fully PASS"))
            continue
        backups, diffs = {}, []
        try:
            for rel, old, new in mutant["patches"]:
                path = isolated / rel
                backups.setdefault(rel, path.read_bytes())
                original = path.read_text(encoding="utf-8")
                if original.count(old) != 1:
                    raise ValueError(f"patch anchor not unique in {rel}")
                changed = original.replace(old, new, 1)
                diffs.extend(difflib.unified_diff(original.splitlines(True),
                             changed.splitlines(True), fromfile=rel, tofile=rel))
                path.write_text(changed, encoding="utf-8", newline="\n")
            (mdir / "mutation.patch").write_text("".join(diffs), encoding="utf-8")
            build = run(["cmake", "--build", mut_build, "--parallel", "4"],
                        cwd=ctx.root, timeout=900)
            (mdir / "build.log").write_text(build["stdout"] + build["stderr"], encoding="utf-8")
            if build["exit"] != 0:
                results.append(make_result("AUD-039", f"{mid}/build", mutant["title"],
                                "NOT_RUN", reason="compile error is not a semantic kill"))
                continue
            (mdir / "manifest.json").write_text(json.dumps({
                "mutantId": mid, "detector": detector,
                "sourceBefore": {rel: hashlib.sha256(data).hexdigest()
                                 for rel, data in backups.items()},
                "sourceAfter": {rel: hashlib.sha256((isolated / rel).read_bytes()).hexdigest()
                                for rel in backups},
                "binaries": {name: hashlib.sha256((mut_build / name).read_bytes()).hexdigest()
                             for name in ("photo-cli.exe", "photoengine_audit_harness.exe")},
                "control": "all detector variants PASS on baseline",
                "patchSha256": hashlib.sha256((mdir / "mutation.patch").read_bytes()).hexdigest()
            }, indent=2), encoding="utf-8")
            mctx = audit_cases.AuditContext(ctx.root, mdir, ctx.policy, ctx.fixtures,
                                           ctx.looks, ctx.oracle_path)
            mctx.cli = mut_build / "photo-cli.exe"
            mctx.harness = mut_build / "photoengine_audit_harness.exe"
            mctx.ref_adapter = mut_build / "ref_adapter.exe"
            try:
                # One full-frame discriminating probe is enough for each LUT
                # mutant; the matching variant already passed in the full
                # baseline family. Reuse exactly the same oracle/comparator.
                lut_probes = {"MUT-01": ("constant", 1.0),
                              "MUT-02": ("affine", 1.0),
                              "MUT-03": ("squaregrid", 1.0),
                              "MUT-04": ("multiaffine", 1.0),
                              "MUT-05": ("affine", 0.5)}
                if mid in lut_probes:
                    kind, amount = lut_probes[mid]
                    rows = audit_cases._look_family_case(mctx, detector, [kind],
                        amounts=[amount], fixtures=["d7000-compressed-12bit"])
                else:
                    rows = audit_cases.CASES[detector](mctx)
            except Exception as exc:
                results.append(make_result("AUD-039", f"{mid}/detector-error",
                                mutant["title"], "NOT_RUN",
                                reason=f"detector exception is not a semantic kill: {exc}"))
                continue
            # A failing numeric assertion or an explicit harness semantic result
            # is evidence. Process crashes/nonzero render errors are not kills.
            semantic = [r for r in rows if r["status"] == "FAIL" and
                        (r.get("metric") is not None or
                         (r.get("actual") and r.get("exitCode") in (0, 1) and
                          str(r["actual"]).startswith("{")))]
            status = "KILLED" if semantic else ("SURVIVED" if all(
                     r["status"] == "PASS" for r in rows) else "UNRUN")
            (mdir / "detector_results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
            results.append(make_result("AUD-039", f"{mid}/{status}", mutant["title"],
                           "PASS" if status == "KILLED" else
                           "FAIL" if status == "SURVIVED" else "NOT_RUN",
                           metric={"mutantStatus": status, "detector": detector,
                                   "control": "PASS", "semanticFailures": [
                                   r["variant"] for r in semantic]},
                           artifacts=[str(mdir / "detector_results.json"),
                                      str(mdir / "mutation.patch")]))
            print(f"[MUTATION  ] {mid}: {status}", flush=True)
        except Exception as exc:
            results.append(make_result("AUD-039", f"{mid}/runner", mutant["title"],
                            "NOT_RUN", reason=f"not a semantic kill: {exc}"))
        finally:
            for rel, data in backups.items():
                (isolated / rel).write_bytes(data)
                if (isolated / rel).read_bytes() != data:
                    raise RuntimeError(f"source restoration failed: {rel}")
            (mdir / "result.json").write_text(json.dumps(results[-1], indent=2), encoding="utf-8")
    suite = run([ctx.cli.parent / "photoengine_tests.exe"], cwd=ctx.root)
    (artifacts / "mutations" / "baseline_suite.log").write_text(
        suite["stdout"] + suite["stderr"], encoding="utf-8")
    same = all((isolated / rel).read_bytes() == (ctx.root / rel).read_bytes()
               for mutant in MUTANTS for rel, _, _ in mutant["patches"])
    results.append(make_result("AUD-039", "baseline-restored",
                   "isolated sources restored byte-for-byte; production baseline suite passes",
                   "PASS" if same and suite["exit"] == 0 else "FAIL",
                   metric={"sourcesRestored": same, "baselineSuiteExit": suite["exit"]}))
    # MUT-15: harness mutant - a comparator that skips NaN must be exposed
    d = artifacts / "mutations" / "MUT-15"
    d.mkdir(parents=True, exist_ok=True)
    real = (HERE.parent / "tests" / "acceptance" / "oracle" / "oracle.py")
    patched_text = real.read_text(encoding="utf-8").replace(
        "if not all(math.isfinite(v) for v in yv):\n"
        "                    raise ValueError(f'Non-finite actual sample at pixel {index}; never skip NaN/Inf.')",
        "if not all(math.isfinite(v) for v in yv):\n"
        "                    index += 1  # MUT-15: skip non-finite pixel\n"
        "                    continue")
    if "MUT-15" in patched_text:
        mutant_oracle = d / "oracle_nan_skip.py"
        mutant_oracle.write_text(patched_text, encoding="utf-8")
        import numpy as np
        rng = np.random.default_rng(5)
        base = (rng.random((16, 16, 3)) * 0.8 + 0.1).astype("<f4")
        bad = base.copy()
        bad[5, 5, 1] = np.float32("nan")
        base.tofile(d / "base.f32le")
        bad.tofile(d / "nan.f32le")
        real_exit = run(["python", str(real), "compare", "--base", str(d / "base.f32le"),
                         "--actual", str(d / "nan.f32le"), "--width", "16",
                         "--height", "16", "--kind", "identity", "--amount", "1",
                         "--domain", "encoded", "--dimension", "17",
                         "--report", str(d / "real.json")])["exit"]
        mut_exit = run(["python", str(mutant_oracle), "compare",
                        "--base", str(d / "base.f32le"),
                        "--actual", str(d / "nan.f32le"), "--width", "16",
                        "--height", "16", "--kind", "identity", "--amount", "1",
                        "--domain", "encoded", "--dimension", "17",
                        "--report", str(d / "mutant.json")])["exit"]
        results.append(make_result(
            "AUD-039", "MUT-15/comparator-nan-skip",
            "removing the non-finite check flips FAIL to PASS: detection depends on the real comparator",
            "PASS" if real_exit == 2 and mut_exit == 0 else "FAIL",
            metric={"realComparatorExit": real_exit,
                    "mutantComparatorExit": mut_exit}))
    else:
        results.append(make_result("AUD-039", "MUT-15/comparator-nan-skip",
                                   "harness mutant", "NOT_RUN",
                                   reason="anchor not found in oracle copy"))
    return results
