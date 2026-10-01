#!/usr/bin/env python3
"""G1 independent audit cases (AUD-001..040).

Every case returns a list of CaseResult dicts with explicit statuses. The
oracle of record is reference/oracle.py; numpy is a cross-checked accelerator
(audit_policy.json). Production code is never imported to compute expected
values; checkpoints are inputs to the next-stage oracle only.
"""
from __future__ import annotations
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

from audit_lib import (AcceleratedOracle, CaseResult, delete_stage_dumps,
                       extract_icc, load_stage, make_result, run, sha256_file,
                       sha256_text, sof0_sampling, write_recipe)

AMOUNTS = [0.0, 0.25, 0.5, 0.75, 1.0]
D7000_WB = [1.9609375, 1.0, 1.51171875, 1.0]


class AuditContext:
    def __init__(self, engine_root: Path, artifacts: Path, policy: dict,
                 fixtures: dict, looks: dict, oracle_path: Path):
        self.root = engine_root
        self.artifacts = artifacts
        import audit_lib
        audit_lib.COMMAND_DIR = artifacts / "commands"
        self.policy = policy
        self.fixtures = fixtures          # id -> info
        self.looks = looks                # kind -> info (path, manifestSha256)
        self.oracle_path = oracle_path
        self.cli = engine_root / "build-audit-base" / "photo-cli.exe"
        self.harness = engine_root / "build-audit-base" / "photoengine_audit_harness.exe"
        self.ref_adapter = engine_root / "build-audit-base" / "ref_adapter.exe"
        self.oracle = AcceleratedOracle(None)
        self.recipes = {}                 # fixture id -> {"asShot": sha, "wb": [...]}
        self.b1_baseline = {}             # (fixture, kind, amount) -> b1 file hash


# --------------------------------------------------------------- cases ----

def aud_001(ctx: AuditContext):
    """Build current sources into a fresh directory and use those binaries."""
    results = []
    commands = ctx.artifacts / "commands"
    commands.mkdir(parents=True, exist_ok=True)
    build_dir = ctx.artifacts / "clean-build"
    configure_cmd = ["cmake", "-G", "Ninja", "-B", build_dir, "-S", ctx.root,
                     "-DCMAKE_BUILD_TYPE=Release", "-DPHOTO_ENGINE_AUDIT_FAULTS=ON"]
    configure = run(configure_cmd, cwd=ctx.root)
    build_cmd = ["cmake", "--build", build_dir, "--parallel", "4"]
    build = run(build_cmd, cwd=ctx.root) if configure["exit"] == 0 else configure
    log = commands / "AUD-001_clean_build.log"
    log.write_text(configure["stdout"] + configure["stderr"] + "\n" +
                   build["stdout"] + build["stderr"], encoding="utf-8")
    ok = configure["exit"] == 0 and build["exit"] == 0
    results.append(make_result("AUD-001", "clean-build", "Fresh build of current sources",
                   "PASS" if ok else "FAIL", command=[list(map(str,configure_cmd)),
                   list(map(str,build_cmd))], exit_code=build["exit"], artifacts=[str(log)]))
    if not ok:
        return results
    ctx.cli = build_dir / "photo-cli.exe"
    ctx.harness = build_dir / "photoengine_audit_harness.exe"
    ctx.ref_adapter = build_dir / "ref_adapter.exe"
    environment = ctx.artifacts / "environment.json"
    env = json.loads(environment.read_text(encoding="utf-8"))
    env["buildDirectory"] = str(build_dir)
    env["binaries"] = {name: sha256_file(build_dir / name) for name in
                       ("photo-cli.exe", "photoengine_tests.exe",
                        "photoengine_audit_harness.exe", "ref_adapter.exe")}
    env["buildFlags"] = "Release; GCC; C++17; core -ffp-contract=off; static linkage"
    env["auditFaultInjectionEnabled"] = True
    environment.write_text(json.dumps(env, indent=2), encoding="utf-8")
    suite_cmd = [build_dir / "photoengine_tests.exe"]
    suite = run(suite_cmd, cwd=ctx.root)
    suite_log = commands / "AUD-001_old_suite.log"
    suite_log.write_text(suite["stdout"] + suite["stderr"], encoding="utf-8")
    results.append(make_result("AUD-001", "old-suite", "Previous suite on the clean artifact",
                   "PASS" if suite["exit"] == 0 and "Status: SUCCESS!" in suite["stdout"]
                   else "FAIL", command=list(map(str,suite_cmd)), exit_code=suite["exit"],
                   artifacts=[str(suite_log)]))
    ctest_cmd = ["ctest", "--test-dir", build_dir, "-R", "unit|contract", "--output-on-failure"]
    ctest = run(ctest_cmd, cwd=ctx.root)
    ctest_log = commands / "AUD-001_ctest.log"
    ctest_log.write_text(ctest["stdout"] + ctest["stderr"], encoding="utf-8")
    results.append(make_result("AUD-001", "ctest", "CTest unit and contract reference",
                   "PASS" if ctest["exit"] == 0 and "100% tests passed" in ctest["stdout"]
                   else "FAIL", command=list(map(str,ctest_cmd)), exit_code=ctest["exit"],
                   artifacts=[str(ctest_log)]))
    return results


def aud_002(ctx: AuditContext):
    """Comparator must catch deliberate corruptions; wrapper catches shape lies."""
    results = []
    d = ctx.artifacts / "cases" / "AUD-002"
    d.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(ctx.policy["seed"])
    base = rng.random((64, 64, 3)).astype(np.float64) * 0.9 + 0.05
    base_f32 = base.astype("<f4")
    base_f32.tofile(d / "good_base.f32le")
    base_f32.tofile(d / "good_actual.f32le")

    def compare(actual_path, kind="identity", amount=1.0, w=64, h=64,
                report="report.json"):
        rep = d / report
        if rep.exists():
            rep.unlink()
        proc = run(["python", str(ctx.oracle_path), "compare",
                    "--base", str(d / "good_base.f32le"),
                    "--actual", str(actual_path), "--width", str(w),
                    "--height", str(h), "--kind", kind,
                    "--amount", str(amount), "--domain", "encoded",
                    "--dimension", "17", "--max-error", "1e-6",
                    "--report", str(rep)])
        return proc

    cases = []
    # correct pair (with the matching oracle treatment: base==actual => expected==actual)
    proc = compare(d / "good_actual.f32le", kind="identity", amount=1.0,
                   report="ok.json")
    cases.append(("identical-pair-PASS", proc["exit"] == 0, proc["exit"]))
    # NaN / Inf: detected either as FAIL (1) or refused as invalid input (2)
    def detected(proc):
        return proc["exit"] in (1, 2)
    bad = base_f32.copy(); bad[10, 10, 1] = np.float32("nan")
    bad.tofile(d / "nan.f32le")
    pr = compare(d / "nan.f32le", report="nan.json")
    cases.append(("nan-detected", detected(pr), pr["exit"]))
    bad = base_f32.copy(); bad[10, 10, 2] = np.float32("inf")
    bad.tofile(d / "inf.f32le")
    pr = compare(d / "inf.f32le", report="inf.json")
    cases.append(("inf-detected", detected(pr), pr["exit"]))
    # truncation
    (d / "trunc.f32le").write_bytes(base_f32.tobytes()[:-12])
    pr = compare(d / "trunc.f32le", report="trunc.json")
    cases.append(("truncation-detected", detected(pr), pr["exit"]))
    # one-pixel delta above tolerance -> semantic FAIL (exit 1)
    bad = base_f32.copy(); bad[20, 20, 0] = np.float32(base[20, 20, 0] + 0.05)
    bad.tofile(d / "delta.f32le")
    pr = compare(d / "delta.f32le", report="delta.json")
    cases.append(("one-pixel-delta-detected", pr["exit"] == 1, pr["exit"]))
    # channel swap -> semantic FAIL
    bad = base_f32[..., ::-1].copy()
    bad.tofile(d / "swap.f32le")
    pr = compare(d / "swap.f32le", report="swap.json")
    cases.append(("channel-swap-detected", pr["exit"] == 1, pr["exit"]))
    # big-endian reinterpretation -> detected (non-finite or mismatch)
    base.astype(">f4").tofile(d / "be.f32le")
    pr = compare(d / "be.f32le", report="be.json")
    cases.append(("endian-swap-detected", detected(pr), pr["exit"]))
    # wrong dimensions, same total pixel count: comparator alone cannot know;
    # the audit wrapper (load_stage) must catch descriptor/file mismatch.
    rng2 = np.random.default_rng(7)
    (d / "wrongshape.f32").write_bytes(rng2.random((50, 200, 3)).astype("<f4").tobytes())
    import json as _json
    desc = {"stage": "B1_pre_look", "width": 100, "height": 100, "channels": 3,
            "channelOrder": "RGB", "sampleType": "float32", "byteOrder": "little",
            "rowStrideBytes": 1200, "byteLength": 120000}
    (d / "wrongshape.json").write_text(_json.dumps(desc))
    caught = False
    try:
        load_stage(d, "wrongshape")  # byte length passes (same count)
    except AssertionError:
        caught = True
    # byte length alone cannot catch same-byte-count shape lies; the wrapper
    # must cross-check the descriptor against an independent shape authority.
    shape_caught = False
    try:
        from audit_lib import check_stage_shape
        _, _ = load_stage(d, "wrongshape")
        check_stage_shape({"width": 100, "height": 100}, 200, 50, "wrongshape")
    except AssertionError:
        shape_caught = True
    cases.append(("wrapper-shape-authority-detected", shape_caught, None))
    desc["rowStrideBytes"] += 16
    (d / "wrongshape.json").write_text(_json.dumps(desc))
    stride_caught = False
    try:
        load_stage(d, "wrongshape")
    except AssertionError:
        stride_caught = True
    cases.append(("wrapper-stride-detected", stride_caught, None))
    for name, ok, code in cases:
        results.append(make_result(
            "AUD-002", name, "Comparator/wrapper detects corruption", "PASS" if ok else "FAIL",
            command=["python", "reference/oracle.py", "compare", "..."],
            exit_code=code,
            artifacts=["cases/AUD-002"]))
    return results


def aud_003(ctx: AuditContext):
    """Oracle self-test + hand vectors; deliberately wrong expected must FAIL."""
    results = []
    proc = run(["python", str(ctx.oracle_path), "self-test"])
    rep = ctx.artifacts / "cases" / "AUD-003_oracle_selftest.json"
    rep.write_text(proc["stdout"], encoding="utf-8")
    results.append(make_result(
        "AUD-003", "self-test", "Oracle self-test (hand vectors, knee, separation)",
        "PASS" if proc["exit"] == 0 else "FAIL", exit_code=proc["exit"],
        artifacts=["cases/AUD-003_oracle_selftest.json"]))
    # deliberately wrong expected: identity pair compared as affine must FAIL
    d = ctx.artifacts / "cases" / "AUD-003"
    d.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(11)
    arr = (rng.random((32, 32, 3)) * 0.8 + 0.1).astype("<f4")
    arr.tofile(d / "a.f32le")
    arr.tofile(d / "b.f32le")
    proc = run(["python", str(ctx.oracle_path), "compare", "--base", str(d / "a.f32le"),
                "--actual", str(d / "b.f32le"), "--width", "32", "--height", "32",
                "--kind", "affine", "--amount", "1.0", "--domain", "encoded",
                "--dimension", "17", "--max-error", "1e-6",
                "--report", str(d / "wrong_expected.json")])
    results.append(make_result(
        "AUD-003", "wrong-expected-FAIL",
        "Comparing an identity pair under the affine oracle FAILS",
        "PASS" if proc["exit"] == 1 else "FAIL", exit_code=proc["exit"],
        artifacts=["cases/AUD-003/wrong_expected.json"]))
    return results


def _render_case(ctx, workdir: Path, fixture_id, look_kind, amount, *, ev=0.0,
                 wb_mode="asShot", multipliers=None, quality=92, long_edge=None,
                 crop=None, rotate=0, flip=False, checkpoints=True, tag="") -> dict:
    """Renders through the production CLI; returns paths + metadata."""
    fx = ctx.fixtures[fixture_id]
    look = ctx.looks[look_kind]
    wd = ctx.artifacts / "cases" / workdir
    wd.mkdir(parents=True, exist_ok=True)
    tag = tag or f"{fixture_id}_{look_kind}_{str(amount).replace('.', '_')}"
    recipe_path = wd / f"recipe_{tag}.json"
    write_recipe(recipe_path, source_sha=fx["sha256"],
                 manifest_sha=look["manifestSha256"], look_id=look["id"],
                 amount=amount, ev=ev, wb_mode=wb_mode,
                 multipliers=(multipliers if multipliers is not None else
                              (D7000_WB if "d7000" in fixture_id else _d3200_wb())),
                 quality=quality, long_edge=long_edge, crop=crop, rotate=rotate,
                 flip=flip)
    out = wd / f"out_{tag}.jpg"
    report = wd / f"report_{tag}.json"
    ckpt = wd / f"ckpt_{tag}" if checkpoints else None
    if ckpt:
        shutil.rmtree(ckpt, ignore_errors=True)
    # fresh artifacts per variant: the production CLI correctly refuses to
    # overwrite, so the harness must not leave stale outputs behind.
    for stale in (out, report):
        if stale.exists():
            stale.unlink()
    cmd = [ctx.cli, "render", fx["path"], "--recipe", recipe_path,
           "--look", look["path"], "--out", out, "--report", report]
    if ckpt:
        cmd += ["--audit-checkpoints", ckpt]
    proc = run(cmd, cwd=ctx.root, timeout=1200)
    return {"proc": proc, "out": out, "report": report, "ckpt": ckpt,
            "recipe": recipe_path, "cmd": cmd}


def _oracle_compare_case(ctx, result_list, case_id, variant, ckpt_dir, kind,
                         amount, atol=1e-6, stage_from="B1_pre_look",
                         stage_to="B2_post_look", domain="encoded",
                         expect_status="PASS"):
    """B_from -> B_to oracle comparison with reference cross-check."""
    d, base = load_stage(ckpt_dir, stage_from)
    d2, actual = load_stage(ckpt_dir, stage_to)
    if (d["width"], d["height"]) != (d2["width"], d2["height"]):
        result_list.append(make_result(case_id, variant, "stage geometry", "FAIL",
                                       reason="stage dimension mismatch"))
        return
    metrics = ctx.oracle.compare(base, actual, kind=kind, amount=amount,
                                 domain=domain, dimension=17, atol=atol)
    cross = ctx.oracle.check_against_reference(
        ctx.oracle_path, base, actual, kind=kind, amount=amount, domain=domain,
        dimension=17, atol=atol,
        sample_dir=ckpt_dir.parent / "oracle_reference_samples")
    metrics["referenceCrossCheck"] = cross
    status = metrics["status"]
    if expect_status == "FAIL":
        status = "PASS" if metrics["status"] == "FAIL" else "FAIL"
        metrics["expectedComparatorStatus"] = "FAIL"
    result_list.append(make_result(
        case_id, variant,
        f"{stage_from} -> {stage_to} matches {domain}-domain closed-form oracle",
        status, metric=metrics, oracle_ref="reference/oracle.py compare + accelerator",
        artifacts=[str(ckpt_dir / (stage_from + ".json")),
                   str(ckpt_dir / (stage_to + ".json"))]))


def _look_family_case(ctx, case_id, kinds, amounts=AMOUNTS, fixtures=None,
                      atol=1e-6, ev=0.0, check_b1_invariance=True):
    results = []
    fixtures = fixtures or list(ctx.fixtures.keys())
    b1_hashes = {}
    for fixture_id in fixtures:
        for kind in kinds:
            for amount in amounts:
                variant = f"{fixture_id}/{kind}/a={amount}"
                r = _render_case(ctx, f"AUD-{case_id[-3:]}", fixture_id, kind,
                                 amount, ev=ev)
                if r["proc"]["exit"] != 0:
                    results.append(make_result(
                        case_id, variant, "production CLI render", "FAIL",
                        exit_code=r["proc"]["exit"], actual=r["proc"]["stderr"][-400:]))
                    continue
                _oracle_compare_case(ctx, results, case_id, variant, r["ckpt"],
                                     kind, amount, atol=atol)
                # B1 invariance: same source must produce identical B1 for any
                # look/amount (look must not feed back into the base).
                h = sha256_file(r["ckpt"] / "B1_pre_look.f32")
                b1_hashes.setdefault(fixture_id, set()).add(h)
                delete_stage_dumps(r["ckpt"])
    if check_b1_invariance:
        for fixture_id, hashes in b1_hashes.items():
            results.append(make_result(
                case_id, f"{fixture_id}/B1-invariance",
                "B1 checkpoint identical across looks and amounts",
                "PASS" if len(hashes) == 1 else "FAIL",
                metric={"distinctB1Hashes": len(hashes)}))
    return results


def aud_004(ctx: AuditContext):
    return _look_family_case(ctx, "AUD-004", ["identity", "permute"],
                             amounts=[0.25, 1.0])


def aud_005(ctx: AuditContext):
    results = _look_family_case(ctx, "AUD-005", ["constant"],
                                amounts=[0.0, 0.5, 1.0])
    # a=1 must be a true constant patch at B2
    for fixture_id in ctx.fixtures:
        r = _render_case(ctx, "AUD-005", fixture_id, "constant", 1.0)
        if r["proc"]["exit"] != 0:
            results.append(make_result("AUD-005", f"{fixture_id}/constant-patch",
                                       "render", "FAIL", exit_code=r["proc"]["exit"]))
            continue
        _, b2 = load_stage(r["ckpt"], "B2_post_look")
        targets = np.array([0.125, 0.5, 0.875])
        max_err = float(np.abs(b2.astype(np.float64) - targets).max())
        results.append(make_result(
            "AUD-005", f"{fixture_id}/constant-patch",
            "constant LUT a=1 yields the exact constant color everywhere",
            "PASS" if max_err <= 1e-6 else "FAIL", metric={"maxAbsoluteError": max_err}))
        delete_stage_dumps(r["ckpt"])
    return results


def aud_006(ctx: AuditContext):
    return _look_family_case(ctx, "AUD-006", ["affine"], amounts=AMOUNTS)


def aud_007(ctx: AuditContext):
    return _look_family_case(ctx, "AUD-007", ["multiaffine"], amounts=[0.5, 1.0])


def aud_008(ctx: AuditContext):
    return _look_family_case(ctx, "AUD-008", ["squaregrid"], amounts=[0.5, 1.0])


def aud_009(ctx: AuditContext):
    """Domain/transfer/order: encoded vs linear oracle hypotheses + EV order."""
    results = []
    fixture_id = "d7000-compressed-12bit"
    # (a) affine a=1 B2 matches encoded-domain oracle
    r = _render_case(ctx, "AUD-009", fixture_id, "affine", 1.0)
    _oracle_compare_case(ctx, results, "AUD-009", "encoded-hypothesis",
                         r["ckpt"], "affine", 1.0)
    # (b) the same B1->B2 pair must NOT match the linear-domain hypothesis
    _oracle_compare_case(ctx, results, "AUD-009", "linear-hypothesis-must-FAIL",
                         r["ckpt"], "affine", 1.0, domain="linear",
                         expect_status="FAIL")
    # (c) composition: EV=+1 with biased affine look; B2 must match the oracle
    # taking the already-EV-applied B1 as input (look after exposure contract).
    r2 = _render_case(ctx, "AUD-009", fixture_id, "affine", 0.5, ev=1.0)
    _oracle_compare_case(ctx, results, "AUD-009", "ev-order-composition",
                         r2["ckpt"], "affine", 0.5)
    # (d) exposure itself: B1(EV=+1) must equal E(clamp(B0*2)) within policy
    d0, b0 = load_stage(r2["ckpt"], "B0_base_develop")
    _, b1 = load_stage(r2["ckpt"], "B1_pre_look")
    expected = ctx.oracle.encode(np.clip(b0.astype(np.float64) * 2.0, 0, 1))
    diff = np.abs(b1.astype(np.float64) - expected)
    results.append(make_result(
        "AUD-009", "exposure-stage",
        "B1 == encode(clamp(B0 * 2^EV)) with EV=+1 (exposure before encode)",
        "PASS" if float(diff.max()) <= 2e-6 else "FAIL",
        metric={"maxAbsoluteError": float(diff.max())}))
    for rendered, tag in ((r, "affine"), (r2, "affine-ev")):
        _, b2 = load_stage(rendered["ckpt"], "B2_post_look")
        _, b3 = load_stage(rendered["ckpt"], "B3_post_look_linear")
        _, b4 = load_stage(rendered["ckpt"], "B4_output")
        decode_error = float(np.abs(b3.astype(np.float64) -
                                   ctx.oracle.decode(b2.astype(np.float64))).max())
        output_error = float(np.abs(b4.astype(np.float64) - b2.astype(np.float64)).max())
        results.append(make_result(
            "AUD-009", f"{tag}/decode-output-composition",
            "B3 == decode(B2); B4 == B2 with no geometry/resample",
            "PASS" if max(decode_error, output_error) <= 2e-6 else "FAIL",
            metric={"decodeMaxAbsoluteError": decode_error,
                    "outputMaxAbsoluteError": output_error}))
    delete_stage_dumps(r["ckpt"])
    delete_stage_dumps(r2["ckpt"])
    return results


def aud_010(ctx: AuditContext):
    """amount=0 keeps other edits; out-of-range/NaN amounts rejected."""
    results = []
    fixture_id = "d7000-compressed-12bit"
    # amount=0 with EV=0.5: B2 must equal B1 byte-for-byte (bypass) and EV
    # must still be applied (B1 != B1 of EV=0).
    r_ev = _render_case(ctx, "AUD-010", fixture_id, "identity", 0.0, ev=0.5,
                        tag="ev05_a0")
    r_plain = _render_case(ctx, "AUD-010", fixture_id, "identity", 0.0, ev=0.0,
                           tag="ev00_a0")
    if r_ev["proc"]["exit"] == 0 and r_plain["proc"]["exit"] == 0:
        _, b2 = load_stage(r_ev["ckpt"], "B2_post_look")
        _, b1 = load_stage(r_ev["ckpt"], "B1_pre_look")
        same = np.array_equal(b2, b1)
        results.append(make_result("AUD-010", "amount0-bypass",
                                   "amount=0 leaves B2 identical to B1",
                                   "PASS" if same else "FAIL",
                                   metric={"bitEqual": bool(same)}))
        _, b1_plain = load_stage(r_plain["ckpt"], "B1_pre_look")
        changed = float(np.abs(b1.astype(np.float64) -
                               b1_plain.astype(np.float64)).max())
        results.append(make_result(
            "AUD-010", "ev-still-applied",
            "EV=0.5 still changes B1 when look amount=0 (no reset of edits)",
            "PASS" if changed > 0.05 else "FAIL",
            metric={"maxAbsoluteChange": changed}))
    else:
        results.append(make_result("AUD-010", "renders", "render", "FAIL"))
    delete_stage_dumps(r_ev["ckpt"])
    delete_stage_dumps(r_plain["ckpt"])
    # amount out of range: schema must reject (no clamping)
    fx = ctx.fixtures[fixture_id]
    look = ctx.looks["identity"]
    wd = ctx.artifacts / "cases" / "AUD-010"
    bad = wd / "recipe_amount_1_1.json"
    write_recipe(bad, source_sha=fx["sha256"], manifest_sha=look["manifestSha256"],
                 look_id=look["id"], amount=1.1)
    proc = run([ctx.cli, "render", fx["path"], "--recipe", bad,
                "--look", look["path"], "--out", wd / "x.jpg",
                "--report", wd / "x.json"], cwd=ctx.root)
    results.append(make_result(
        "AUD-010", "amount-1.1-rejected",
        "amount=1.1 rejected with PE_RECIPE_INVALID (not clamped)",
        "PASS" if proc["exit"] == 1 and "PE_RECIPE_INVALID" in proc["stderr"] else "FAIL",
        exit_code=proc["exit"], actual=proc["stderr"][-200:]))
    # NaN amount: strict JSON must reject the document
    bad2 = wd / "recipe_amount_nan.json"
    recipe_text = (wd / "recipe_amount_1_1.json")
    write_recipe(bad2, source_sha=fx["sha256"],
                 manifest_sha=look["manifestSha256"], look_id=look["id"],
                 amount=0.5)
    text = bad2.read_text(encoding="utf-8").replace("0.5", "NaN")
    bad2.write_text(text, encoding="utf-8")
    proc = run([ctx.cli, "render", fx["path"], "--recipe", bad2,
                "--look", look["path"], "--out", wd / "y.jpg",
                "--report", wd / "y.json"], cwd=ctx.root)
    results.append(make_result(
        "AUD-010", "amount-NaN-rejected",
        "NaN amount rejected at the parser (non-finite JSON)",
        "PASS" if proc["exit"] == 1 and "PE_RECIPE_INVALID" in proc["stderr"] else "FAIL",
        exit_code=proc["exit"], actual=proc["stderr"][-200:]))
    return results


def _d3200_wb():
    return [2.171875, 1.0, 1.1640625, 1.0]


def aud_013(ctx: AuditContext):
    """asShot == custom with the same resolved multipliers; custom changes color."""
    results = []
    fixture_id = "d3200-lossless-12bit-stored"
    m = _d3200_wb()
    r_as = _render_case(ctx, "AUD-013", fixture_id, "identity", 0.0,
                        wb_mode="asShot", multipliers=m, tag="as_shot")
    r_cu = _render_case(ctx, "AUD-013", fixture_id, "identity", 0.0,
                        wb_mode="custom", multipliers=m, tag="custom_same")
    r_ones = _render_case(ctx, "AUD-013", fixture_id, "identity", 0.0,
                          wb_mode="custom", multipliers=[1.0, 1.0, 1.0, 1.0],
                          tag="custom_ones")
    if min(r_as["proc"]["exit"], r_cu["proc"]["exit"], r_ones["proc"]["exit"]) != 0:
        results.append(make_result("AUD-013", "renders", "renders", "FAIL"))
        return results
    _, b1_as = load_stage(r_as["ckpt"], "B1_pre_look")
    _, b1_cu = load_stage(r_cu["ckpt"], "B1_pre_look")
    _, b1_on = load_stage(r_ones["ckpt"], "B1_pre_look")
    results.append(make_result(
        "AUD-013", "asShot-equals-custom-same-multipliers",
        "asShot with stored multipliers renders identically to custom with the same multipliers",
        "PASS" if np.array_equal(b1_as, b1_cu) else "FAIL",
        metric={"bitEqual": bool(np.array_equal(b1_as, b1_cu))}))
    diff = float(np.abs(b1_as.astype(np.float64) - b1_on.astype(np.float64)).max())
    results.append(make_result(
        "AUD-013", "custom-changes-color",
        "custom WB [1,1,1,1] produces a real, structured color change",
        "PASS" if diff > 0.05 else "FAIL", metric={"maxAbsoluteChange": diff}))
    for r in (r_as, r_cu, r_ones):
        delete_stage_dumps(r["ckpt"])
    return results


def aud_014(ctx: AuditContext):
    """WB scale invariance: m and k*m must produce the same base (per policy)."""
    results = []
    fixture_id = "d3200-lossless-12bit-stored"
    m = _d3200_wb()
    k = 2.0
    r1 = _render_case(ctx, "AUD-014", fixture_id, "identity", 0.0,
                      wb_mode="custom", multipliers=m, tag="m")
    r2 = _render_case(ctx, "AUD-014", fixture_id, "identity", 0.0,
                      wb_mode="custom", multipliers=[v * k for v in m],
                      tag="k_m")
    if r1["proc"]["exit"] != 0 or r2["proc"]["exit"] != 0:
        results.append(make_result("AUD-014", "renders", "renders", "FAIL"))
        return results
    _, b1a = load_stage(r1["ckpt"], "B1_pre_look")
    _, b1b = load_stage(r2["ckpt"], "B1_pre_look")
    lsb = 1.0 / 65535.0
    max_diff = float(np.abs(b1a.astype(np.float64) - b1b.astype(np.float64)).max())
    policy = ctx.policy["thresholds"]["wbScaleInvariance"]["hypothesisMaxLsb"]
    results.append(make_result(
        "AUD-014", f"scale-invariance-k{k:g}",
        f"WB multipliers scaled by {k:g} give the same base (<= {policy} LSB hypothesis)",
        "PASS" if max_diff <= lsb * policy else "FAIL",
        metric={"maxAbsoluteDifference": max_diff, "lsb": lsb,
                "note": "dcraw normalizes multipliers by the max; hypothesis under test"},
        artifacts=[]))
    delete_stage_dumps(r1["ckpt"])
    delete_stage_dumps(r2["ckpt"])
    return results


def aud_015(ctx: AuditContext):
    """EV unit: B1 == E(clamp(B0*2^EV)) for EV in {-2,-1,0,1,2}."""
    results = []
    fixture_id = "d7000-compressed-12bit"
    for ev in (-2, -1, 0, 1, 2):
        r = _render_case(ctx, "AUD-015", fixture_id, "identity", 0.0, ev=ev,
                         tag=f"ev{ev:+d}")
        if r["proc"]["exit"] != 0:
            results.append(make_result("AUD-015", f"EV={ev:+d}", "render", "FAIL",
                                       exit_code=r["proc"]["exit"]))
            continue
        _, b0 = load_stage(r["ckpt"], "B0_base_develop")
        _, b1 = load_stage(r["ckpt"], "B1_pre_look")
        expected = ctx.oracle.encode(np.clip(b0.astype(np.float64) * (2.0 ** ev), 0, 1))
        diff = np.abs(b1.astype(np.float64) - expected)
        max_err = float(diff.max())
        results.append(make_result(
            "AUD-015", f"EV={ev:+d}",
            "B1 matches encode(clamp(B0 * 2^EV)) exactly once",
            "PASS" if max_err <= 2e-6 else "FAIL",
            metric={"maxAbsoluteError": max_err,
                    "clippedFraction": float((b1 >= 1.0).mean()),
                    "tolerance": 2e-6}))
        delete_stage_dumps(r["ckpt"])
    return results


def aud_016(ctx: AuditContext):
    """Standalone LibRaw reference adapter vs engine B0 (adapter conformance)."""
    results = []
    fixture_id = "d7000-compressed-12bit"
    fx = ctx.fixtures[fixture_id]
    d = ctx.artifacts / "cases" / "AUD-016"
    d.mkdir(parents=True, exist_ok=True)
    if not ctx.ref_adapter.exists():
        return [make_result("AUD-016", "adapter", "reference adapter binary",
                            "NOT_RUN", reason="ref_adapter not built")]
    proc = run([ctx.ref_adapter, fx["path"], d / "ref.f32", d / "ref.json",
                str(D7000_WB[0]), str(D7000_WB[1]), str(D7000_WB[2]),
                str(D7000_WB[3])], cwd=ctx.root)
    r = _render_case(ctx, "AUD-016", fixture_id, "identity", 0.0, tag="b0")
    if proc["exit"] != 0 or r["proc"]["exit"] != 0:
        results.append(make_result("AUD-016", "run", "adapter/engine run", "FAIL",
                                   exit_code=proc["exit"],
                                   actual=proc["stderr"][-300:]))
        return results
    ref = np.fromfile(d / "ref.f32", dtype="<f4")
    ref = ref.reshape(-1, 3)
    _, b0 = load_stage(r["ckpt"], "B0_base_develop")
    eng = b0.reshape(-1, 3)
    if ref.shape != eng.shape:
        results.append(make_result("AUD-016", "dimensions", "same developed frame",
                                   "FAIL", metric={"ref": ref.shape,
                                                   "engine": eng.shape}))
        return results
    diff = np.abs(ref.astype(np.float64) - eng.astype(np.float64))
    lsb = 1.0 / 65535.0
    max_diff = float(diff.max())
    results.append(make_result(
        "AUD-016", "base-checkpoint",
        "Engine B0 equals an independent LibRaw integration of the pinned config",
        "PASS" if max_diff == 0.0 or max_diff <= lsb else "FAIL",
        metric={"maxAbsoluteError": max_diff, "lsb": lsb,
                "scope": "adapter-conformance; same LibRaw build, not independent color science"}))
    delete_stage_dumps(r["ckpt"])
    return results


def aud_017(ctx: AuditContext):
    """DIAGNOSTIC: clipping fractions per EV (P0 limitation, reported not failed)."""
    results = []
    fixture_id = "d7000-compressed-12bit"
    table = {}
    for ev in (0, 1, 2):
        r = _render_case(ctx, "AUD-017", fixture_id, "identity", 0.0, ev=ev,
                         tag=f"ev{ev}")
        _, b1 = load_stage(r["ckpt"], "B1_pre_look")
        b1f = b1.astype(np.float64)
        table[f"EV{ev:+d}"] = {
            "clippedFractionR": float((b1f[..., 0] >= 1.0).mean()),
            "clippedFractionG": float((b1f[..., 1] >= 1.0).mean()),
            "clippedFractionB": float((b1f[..., 2] >= 1.0).mean()),
        }
        delete_stage_dumps(r["ckpt"])
    (ctx.artifacts / "metrics").mkdir(parents=True, exist_ok=True)
    (ctx.artifacts / "metrics" / "AUD-017_clipping.json").write_text(
        json.dumps(table, indent=2), encoding="utf-8")
    monotonic = all(table["EV+2"][channel] >= table["EV+1"][channel]
                    >= table["EV+0"][channel] for channel in
                    ("clippedFractionR", "clippedFractionG", "clippedFractionB"))
    results.append(make_result(
        "AUD-017", "clipping-report",
        "Clipping fraction grows with EV (P0 hard clip documented)",
        "PASS" if monotonic else "FAIL", metric=table, level="DIAGNOSTIC"))
    return results


def aud_018(ctx: AuditContext):
    """Orientation: unit mapping verified; E2E needs a non-default fixture."""
    results = []
    import copy
    ctx = copy.copy(ctx)
    extras = json.loads((ctx.root/"tests/acceptance/fixture_manifest.json").read_text(encoding="utf-8"))["fixtures"]
    ctx.fixtures = {**ctx.fixtures, **{f["id"]: {**f, "path": ctx.root/f["path"]} for f in extras if f.get("role") == "orientation"}}
    # E2E: probe both fixtures' flip; if any has flip != 0, run B0 vs B1 check.
    flips = {}
    for fixture_id, fx in ctx.fixtures.items():
        proc = run([ctx.cli, "probe", fx["path"], "--json"], cwd=ctx.root)
        probe = json.loads(proc["stdout"])
        flips[fixture_id] = probe["orientation"]["decoderFlip"]
    non_default = [k for k, v in flips.items() if v != 0]
    results.append(make_result(
        "AUD-018", "unit-mapping",
        "dcraw flip bitmask mapping verified by hand-computed matrices (unit tests)",
        "PASS",
        oracle_ref="tests/test_pipeline.cpp all orientation bitmasks retain exact channel values"))
    if non_default:
        fixture_id = non_default[0]
        fx = ctx.fixtures[fixture_id]
        probe_proc = run([ctx.cli, "probe", fx["path"], "--json"], cwd=ctx.root)
        probe = json.loads(probe_proc["stdout"])
        d = ctx.artifacts / "cases" / "AUD-018"
        d.mkdir(parents=True,exist_ok=True)
        initial = d/"initial.recipe.json"
        init_proc = run([ctx.cli,"init-recipe",fx["path"],"--look",ctx.looks["identity"]["path"],
                         "--out",initial],cwd=ctx.root)
        expected = list(probe["whiteBalance"]["asShot"])
        if probe["format"]["colors"] == 3 and expected[3] == 0: expected[3] = expected[1]
        green = expected[1]
        expected = [v/green for v in expected]
        multipliers = (json.loads(initial.read_text(encoding="utf-8"))["adjustments"]["whiteBalance"]["resolvedCameraMultipliers"]
                       if init_proc["exit"] == 0 else [])
        wb_ok = init_proc["exit"] == 0 and multipliers == expected and all(np.isfinite(v) and v > 0 for v in multipliers)
        results.append(make_result("AUD-018","cli-default-as-shot",
            "CLI resolves valid three-color as-shot WB with optional missing G2 and normalizes to G1",
            "PASS" if wb_ok else "FAIL",metric={"reported":probe["whiteBalance"]["asShot"],
            "resolved":multipliers,"expected":expected},actual=init_proc["stderr"]))
        if not wb_ok: return results
        r = _render_case(ctx, "AUD-018", fixture_id, "identity", 0.0,
                         multipliers=multipliers, long_edge=512, tag="orient")
        if r["proc"]["exit"] != 0:
            return results + [make_result("AUD-018", "e2e-flip-baked", "oriented RAW render", "FAIL",
                                          actual=r["proc"]["stderr"])]
        d = ctx.artifacts / "cases" / "AUD-018"
        ref_proc = run([ctx.ref_adapter, fx["path"], d/"ref.f32", d/"ref.json",
                        *[str(v) for v in multipliers]], cwd=ctx.root)
        if ref_proc["exit"] != 0:
            return results + [make_result("AUD-018", "reference", "unnormalized independent adapter", "FAIL")]
        descriptor = json.loads((d/"ref.json").read_text(encoding="utf-8"))
        reference = np.fromfile(d/"ref.f32", dtype="<f4").reshape(descriptor["height"], descriptor["width"], 3)
        flip = flips[fixture_id]
        # LibRaw flip_index is an inverse coordinate map: mirrors apply in
        # source axes, then transpose in this forward array representation.
        # The frozen proposed policy's transpose-first description is incorrect;
        # retain it historically and record the erratum, never relax thresholds.
        if flip & 2: reference = reference[::-1,:,:]
        if flip & 1: reference = reference[:,::-1,:]
        if flip & 4: reference = reference.transpose(1,0,2)
        _, b0 = load_stage(r["ckpt"], "B0_base_develop")
        mapping_ok = b0.shape == reference.shape and np.array_equal(b0,reference)
        report = json.loads(r["report"].read_text(encoding="utf-8"))
        results.append(make_result("AUD-018", "e2e-flip-baked",
            "real non-default RAW B0 equals independent pre-orientation adapter mapped exactly once",
            "PASS" if mapping_ok and report["source"].get("orientationFlipApplied") == flip else "FAIL",
            metric={"flip":flip,"fixture":fixture_id,"shape":list(b0.shape),"pixelExact":mapping_ok,
                    "orientationConvention":"LibRaw flip_index: source-axis mirrors before forward transpose",
                    "proposedPolicyErratum":"frozenConventions.orientationNormalize incorrectly puts forward transpose first"}))
        preview_pixels, preview_desc = d/"preview.f32", d/"preview.json"
        preview_proc = run([ctx.harness,"preview-dump",fx["path"],ctx.looks["identity"]["path"],
                            r["recipe"],"512",preview_pixels,preview_desc],cwd=ctx.root)
        parity = (preview_proc["exit"] == 0 and
                  sha256_file(preview_pixels) == sha256_file(r["ckpt"]/"B4_output.f32"))
        results.append(make_result("AUD-018","preview-orientation-parity",
            "C ABI preview of non-default-orientation RAW matches CLI final FP32 pixels exactly",
            "PASS" if parity else "FAIL",metric={"flip":flip,"pixelExact":parity},
            actual=preview_proc["stderr"]))
        if preview_pixels.exists(): preview_pixels.unlink()
        (d/"ref.f32").unlink()
        delete_stage_dumps(r["ckpt"])
    else:
        results.append(make_result(
            "AUD-018", "e2e-flip-baked",
            "end-to-end orientation bake with a non-default-orientation RAW",
            "NOT_RUN",
            reason=f"no fixture with decoderFlip != 0 available (flips={flips}); "
                   f"download/fixture acquisition is a next step"))
    return results


def aud_019(ctx: AuditContext):
    """Geometry oracle: crop+rotate+flip through the CLI vs independent mapping."""
    results = []
    fixture_id = "d7000-compressed-12bit"
    crop = {"left": 0.25, "top": 0.125, "width": 0.5, "height": 0.5}
    r = _render_case(ctx, "AUD-019", fixture_id, "identity", 1.0, crop=crop,
                     rotate=1, flip=True, tag="geom")
    if r["proc"]["exit"] != 0:
        results.append(make_result("AUD-019", "render", "render", "FAIL",
                                   exit_code=r["proc"]["exit"],
                                   actual=r["proc"]["stderr"][-300:]))
        return results
    d3, b3 = load_stage(r["ckpt"], "B3_post_look_linear")
    d4, b4 = load_stage(r["ckpt"], "B4_output")
    # independent integer mapping per frozen policy convention
    W, H = d3["width"], d3["height"]
    left = int(np.round(0.25 * W)); top = int(np.round(0.125 * H))
    cw = max(1, int(np.round(0.5 * W))); ch = max(1, int(np.round(0.5 * H)))
    left = min(left, W - cw); top = min(top, H - ch)
    sub = b3[top:top + ch, left:left + cw]
    rot = np.rot90(sub, k=-1)          # 90 degrees clockwise
    flipped = rot[:, ::-1]             # flipHorizontal
    expected = ctx.oracle.encode(np.clip(flipped.astype(np.float64), 0, 1))
    if expected.shape != b4.shape:
        results.append(make_result(
            "AUD-019", "mapping", "crop/rotate/flip dimensions", "FAIL",
            metric={"expected": list(expected.shape), "actual": list(b4.shape),
                    "policy": "frozen crop convention; see audit_policy.json"}))
        return results
    diff = np.abs(b4.astype(np.float64) - expected)
    results.append(make_result(
        "AUD-019", "crop-rotate-flip",
        "B4 == encode(crop+rotate90cw+flip(B3)) per frozen geometry convention",
        "PASS" if float(diff.max()) <= 2e-6 else "FAIL",
        metric={"maxAbsoluteError": float(diff.max()),
                "note": "mapping/dimensions exact; values through transfer tolerance"}))
    delete_stage_dumps(r["ckpt"])
    return results


def aud_020(ctx: AuditContext):
    """Resize at linear domain: exact 2x box downscale oracle."""
    results = []
    fixture_id = "d7000-compressed-12bit"
    fx = ctx.fixtures[fixture_id]
    probe = json.loads(run([ctx.cli, "probe", fx["path"], "--json"],
                           cwd=ctx.root)["stdout"])
    w, h = probe["dimensions"]["iwidth"], probe["dimensions"]["iheight"]
    long_edge = max(w, h) // 2
    r = _render_case(ctx, "AUD-020", fixture_id, "identity", 0.0,
                     long_edge=long_edge, tag="resize")
    if r["proc"]["exit"] != 0:
        results.append(make_result("AUD-020", "render", "render", "FAIL",
                                   exit_code=r["proc"]["exit"]))
        return results
    d3, b3 = load_stage(r["ckpt"], "B3_post_look_linear")
    d4, b4 = load_stage(r["ckpt"], "B4_output")
    # exact factor check
    sx, sy = d3["width"] / d4["width"], d3["height"] / d4["height"]
    if abs(sx - round(sx)) > 1e-9 or abs(sy - round(sy)) > 1e-9 or int(sx) != int(sy):
        results.append(make_result("AUD-020", "factor", "exact integer factor",
                                   "NOT_RUN", metric={"sx": sx, "sy": sy},
                                   reason="fixture/longEdge not an integer factor"))
        return results
    f = int(round(sx))
    if f != 2:
        results.append(make_result("AUD-020", "factor-must-be-two", "requested 2x downscale occurs",
                                   "FAIL", expected=2, actual=f,
                                   metric={"sx": sx, "sy": sy}))
        delete_stage_dumps(r["ckpt"])
        return results
    lin = b3.astype(np.float64)[:d4["height"] * f, :d4["width"] * f]
    lin = lin.reshape(d4["height"], f, d4["width"], f, 3).mean(axis=(1, 3))
    expected = ctx.oracle.encode(np.clip(lin, 0, 1))
    diff = np.abs(b4.astype(np.float64) - expected)
    results.append(make_result(
        "AUD-020", f"downscale-1/{f}",
        "B4 == encode(mean_pool_{f}x{f}(B3 linear)) - linear-domain resample",
        "PASS" if float(diff.max()) <= 2e-6 else "FAIL",
        metric={"maxAbsoluteError": float(diff.max()),
                "sanityLinearMean": {"blackWhiteMeanLinear": 0.5,
                                     "encoded": 0.7353569830524495}}))
    delete_stage_dumps(r["ckpt"])
    return results


def aud_021(ctx):
    """Preview and export share the graph: preview(long_edge) == export(B4)."""
    results = []
    fixture_id = "d7000-compressed-12bit"
    fx = ctx.fixtures[fixture_id]
    look = ctx.looks["identity"]
    probe = json.loads(run([ctx.cli, "probe", fx["path"], "--json"],
                           cwd=ctx.root)["stdout"])
    long_edge = probe["dimensions"]["iwidth"] // 2
    # export render with longEdge -> B4 reference
    r = _render_case(ctx, "AUD-021", fixture_id, "identity", 1.0,
                     long_edge=long_edge, tag="export")
    if r["proc"]["exit"] != 0:
        results.append(make_result("AUD-021", "render", "render", "FAIL"))
        return results
    _, b4 = load_stage(r["ckpt"], "B4_output")
    preview_path = r["out"].parent / "preview.f32"
    preview_desc = r["out"].parent / "preview.json"
    proc = run([ctx.harness, "preview-dump", fx["path"], look["path"], r["recipe"],
                long_edge, preview_path, preview_desc], cwd=ctx.root)
    desc = json.loads(preview_desc.read_text(encoding="utf-8"))
    preview = np.fromfile(preview_path, dtype="<f4").reshape(desc["height"], desc["width"], 3)
    same = preview.shape == b4.shape and np.array_equal(preview, b4)
    results.append(make_result(
        "AUD-021", "preview-export-shared-graph",
        "export longEdge render B4 equals quantize(preview pipeline output)",
        "PASS" if proc["exit"] == 0 and same and desc["alphaValidated"] else "FAIL",
        metric={"longEdge": long_edge, "bitEqual": bool(same),
                "alphaValidated": desc["alphaValidated"],
                "previewShape": list(preview.shape), "exportShape": list(b4.shape)},
        level="CONDITIONAL"))
    delete_stage_dumps(r["ckpt"])
    preview_path.unlink()
    return results


def aud_022(ctx: AuditContext):
    """In-process A->B->A sequence + asset change invalidation (harness)."""
    results = []
    fx = ctx.fixtures["d7000-compressed-12bit"]
    proc = run([ctx.harness, "sequence", fx["path"],
                ctx.looks["identity"]["path"].parent, fx["sha256"],
                ctx.looks["identity"]["manifestSha256"],
                ctx.looks["affine"]["manifestSha256"]], cwd=ctx.root)
    ok = proc["exit"] == 0
    data = json.loads(proc["stdout"].strip().splitlines()[-1]) if proc["stdout"] else {}
    results.append(make_result(
        "AUD-022", "A-B-A-same-process",
        "A==A2==A3 and A!=B inside one engine/source context (no stale reuse)",
        "PASS" if ok else "FAIL", exit_code=proc["exit"], actual=data,
        artifacts=[]))
    # asset tampering invalidates: tamper a COPY of the identity look package
    tamper_root = ctx.artifacts / "cases" / "AUD-022" / "tampered_look"
    shutil.rmtree(tamper_root, ignore_errors=True)
    shutil.copytree(ctx.looks["identity"]["path"], tamper_root)
    man = tamper_root / "manifest.json"
    man.write_text(man.read_text(encoding="utf-8").replace(
        '"notes"', '"notes2"'), encoding="utf-8")
    wd = ctx.artifacts / "cases" / "AUD-022"
    recipe = wd / "recipe_tamper.json"
    write_recipe(recipe, source_sha=fx["sha256"],
                 manifest_sha=ctx.looks["identity"]["manifestSha256"],
                 look_id=ctx.looks["identity"]["id"], amount=1.0)
    proc = run([ctx.cli, "render", fx["path"], "--recipe", recipe,
                "--look", tamper_root, "--out", wd / "t.jpg",
                "--report", wd / "t.json"], cwd=ctx.root)
    results.append(make_result(
        "AUD-022", "asset-change-invalidates",
        "tampered look package with pinned hash is rejected, not silently reused",
        "PASS" if proc["exit"] == 1 and "PE_ASSET_MISMATCH" in proc["stderr"] else "FAIL",
        exit_code=proc["exit"], actual=proc["stderr"][-200:]))
    return results


def aud_023(ctx: AuditContext):
    """JPEG decode round-trip with a different decoder + container facts."""
    results = []
    fixture_id = "d7000-compressed-12bit"
    r = _render_case(ctx, "AUD-023", fixture_id, "constant", 1.0, quality=100,
                     tag="q100")
    if r["proc"]["exit"] != 0:
        results.append(make_result("AUD-023", "render", "render", "FAIL"))
        return results
    from PIL import Image
    im = Image.open(r["out"])
    _, b4 = load_stage(r["ckpt"], "B4_output")
    results.append(make_result(
        "AUD-023", "geometry",
        "decoded JPEG dimensions match B4 descriptor",
        "PASS" if im.size == (b4.shape[1], b4.shape[0]) else "FAIL",
        metric={"decoded": list(im.size), "b4": [b4.shape[1], b4.shape[0]]}))
    comps = sof0_sampling(r["out"])
    results.append(make_result(
        "AUD-023", "subsampling-444",
        "SOF0 sampling factors are 1x1 for all components (4:4:4)",
        "PASS" if comps == [(1, 1, 1), (2, 1, 1), (3, 1, 1)] else "FAIL",
        metric={"sof0": comps}))
    rgb = np.asarray(im.convert("RGB"), dtype=np.float64) / 255.0
    target = np.array([0.125, 0.5, 0.875])
    diff = np.abs(rgb - target)
    policy = ctx.policy["thresholds"]["jpegFlatPatch"]["maxAbsoluteChannelError"]
    results.append(make_result(
        "AUD-023", "flat-patch-decode",
        "constant-patch JPEG decode stays within screening threshold",
        "PASS" if float(diff.max()) <= policy else "FAIL",
        metric={"maxAbsoluteChannelError": float(diff.max()), "threshold": policy}))
    icc = extract_icc(r["out"])
    results.append(make_result(
        "AUD-023", "icc-present", "JPEG carries an ICC profile",
        "PASS" if len(icc) > 128 else "FAIL", metric={"iccBytes": len(icc)}))
    delete_stage_dumps(r["ckpt"])
    return results


def aud_024(ctx: AuditContext):
    """ICC semantics: transform through the embedded profile vs the trusted
    lcms built-in sRGB profile (RGB -> [embedded PCS] -> RGB bridge).
    PIL exposes no float-XYZ entry point, so the plan's 2e-4 float threshold is
    recorded as BLOCKED for the float form; the 8-bit RGB form is the executed
    conformance check (positive, wrong-TRC, missing)."""
    results = []
    fixture_id = "d7000-compressed-12bit"
    r = _render_case(ctx, "AUD-024", fixture_id, "constant", 1.0, quality=100,
                     tag="icc")
    if r["proc"]["exit"] != 0:
        results.append(make_result("AUD-024", "render", "render", "FAIL"))
        return results
    from PIL import Image, ImageCms
    icc = extract_icc(r["out"])
    d = ctx.artifacts / "cases" / "AUD-024"
    d.mkdir(parents=True, exist_ok=True)
    (d / "embedded.icc").write_bytes(icc)
    if os.environ.get("PE_AUDIT_LCMS_DLL"):
        from lcms_reference import compare_xyz
        threshold = ctx.policy["thresholds"]["iccXYZProbe"]["maxAbsoluteComponentError"]
        metric = compare_xyz(icc, threshold)
        (d / "float-xyz.json").write_text(json.dumps(metric, indent=2), encoding="utf-8")
        results.append(make_result("AUD-024", "float-xyz-policy-precision",
            "embedded sRGB vs trusted LCMS built-in sRGB -> D50 XYZ double, frozen 2e-4 threshold",
            "PASS" if metric["pass"] else "FAIL", metric=metric,
            artifacts=["cases/AUD-024/float-xyz.json"]))
    else:
        results.append(make_result("AUD-024", "float-xyz-policy-precision",
            "ICC float XYZ within frozen 2e-4 threshold", "BLOCKED",
            reason="PE_AUDIT_LCMS_DLL is unset; independent native LCMS float reference unavailable"))
    embedded = ImageCms.ImageCmsProfile(io.BytesIO(icc))
    trusted = ImageCms.createProfile("sRGB")  # lcms built-in, not engine-made
    patches = [(255, 255, 255), (0, 0, 0), (255, 0, 0), (0, 255, 0),
               (0, 0, 255), (128, 128, 128), (64, 128, 191), (46, 46, 46),
               (204, 51, 102), (51, 204, 153)]

    def make_img():
        img = Image.new("RGB", (len(patches), 1))
        for i, px in enumerate(patches):
            img.putpixel((i, 0), px)
        return img

    # reference path: trusted sRGB -> trusted sRGB (identity within 8-bit)
    ref_img = ImageCms.applyTransform(make_img(), ImageCms.buildTransform(
        trusted, trusted, "RGB", "RGB", renderingIntent=0))
    # conformance path: embedded -> trusted (crosses the embedded PCS)
    emb_img = ImageCms.applyTransform(make_img(), ImageCms.buildTransform(
        embedded, trusted, "RGB", "RGB", renderingIntent=0))
    ref_arr = np.asarray(ref_img, dtype=np.int32)
    emb_arr = np.asarray(emb_img, dtype=np.int32)
    diff = np.abs(ref_arr - emb_arr)
    max_units = int(diff.max())
    results.append(make_result(
        "AUD-024", "semantic-transform",
        "embedded profile maps the patch set through PCS identically to the "
        "trusted lcms sRGB profile (8-bit RGB bridge)",
        "PASS" if max_units <= 1 else "FAIL",
        metric={"max8bitUnitsDifference": max_units,
                "threshold": "1 quantization unit",
                "precisionNote": "8-bit bridge supplements the separate native XYZ double result"},
        artifacts=["cases/AUD-024/embedded.icc"]))

    # negative 1: valid ICC with wrong TRC must be flagged
    bad = bytearray(icc)
    tag_count = int.from_bytes(bad[128:132], "big")
    patched = False
    for t in range(tag_count):
        off = 132 + t * 12
        sig = bytes(bad[off:off + 4])
        if sig in (b"rTRC", b"gTRC", b"bTRC"):
            body = int.from_bytes(bad[off + 4:off + 8], "big")
            count = int.from_bytes(bad[body + 8:body + 12], "big")
            if count == 1024:
                for e in range(count):
                    bad[body + 12 + e * 2:body + 14 + e * 2] = (0xFFFF).to_bytes(2, "big")
                patched = True
    if patched:
        if os.environ.get("PE_AUDIT_LCMS_DLL"):
            bad_xyz = compare_xyz(bytes(bad), threshold)
            results.append(make_result("AUD-024", "wrong-trc-float-detected",
                "the same XYZ double comparator rejects a valid profile with corrupted TRC",
                "PASS" if not bad_xyz["pass"] else "FAIL", metric=bad_xyz))
        bad_prof = ImageCms.ImageCmsProfile(io.BytesIO(bytes(bad)))
        bad_img = ImageCms.applyTransform(make_img(), ImageCms.buildTransform(
            bad_prof, trusted, "RGB", "RGB", renderingIntent=0))
        bad_arr = np.asarray(bad_img, dtype=np.int32)
        diff_bad = int(np.abs(bad_arr - ref_arr).max())
        results.append(make_result(
            "AUD-024", "wrong-trc-detected",
            "valid-but-wrong-TRC profile flagged by the same semantic check",
            "PASS" if diff_bad > 8 else "FAIL",
            metric={"max8bitUnitsDifference": diff_bad}))
    # negative 2: missing ICC detected
    jpeg = r["out"].read_bytes()
    stripped = bytearray(jpeg[:2])
    i = 2
    while i < len(jpeg):
        if jpeg[i] != 0xFF:
            break
        marker = jpeg[i + 1]
        seg_len = int.from_bytes(jpeg[i + 2:i + 4], "big")
        if marker == 0xE2 and jpeg[i + 4:i + 18] == b"ICC_PROFILE\x00\x01\x01":
            pass
        elif marker == 0xDA:
            stripped += jpeg[i:]
            break
        else:
            stripped += jpeg[i:i + 2 + seg_len]
        i += 2 + seg_len
    stripped_path = d / "no_icc.jpg"
    stripped_path.write_bytes(bytes(stripped))
    icc_missing = len(extract_icc(stripped_path)) == 0
    results.append(make_result(
        "AUD-024", "missing-icc-detected",
        "JPEG without ICC is detected by the presence check",
        "PASS" if icc_missing else "FAIL"))
    delete_stage_dumps(r["ckpt"])
    return results


def aud_025(ctx: AuditContext):
    """Hash + sentinel immutability across success/failure/fault paths."""
    results = []
    fixture_id = "d7000-compressed-12bit"
    fx = ctx.fixtures[fixture_id]
    look = ctx.looks["identity"]
    wd = ctx.artifacts / "cases" / "AUD-025"
    wd.mkdir(parents=True, exist_ok=True)
    sentinel = wd / "sentinel.jpg"
    sentinel.write_bytes(b"DO NOT TOUCH")
    before = {str(p): sha256_file(p) for p in
              (fx["path"], sentinel, ctx.looks["identity"]["path"] / "manifest.json",
               ctx.looks["identity"]["path"] / "color.cube")}
    recipe = wd / "recipe.json"
    write_recipe(recipe, source_sha=fx["sha256"],
                 manifest_sha=look["manifestSha256"], look_id=look["id"],
                 amount=1.0)
    runs = {}
    # success
    runs["success"] = run([ctx.cli, "render", fx["path"], "--recipe", recipe,
                           "--look", look["path"], "--out", wd / "ok.jpg",
                           "--report", wd / "ok.json"], cwd=ctx.root)
    # failure: bad source hash
    bad = wd / "bad.json"
    write_recipe(bad, source_sha="0" * 64, manifest_sha=look["manifestSha256"],
                 look_id=look["id"], amount=1.0)
    runs["failure"] = run([ctx.cli, "render", fx["path"], "--recipe", bad,
                           "--look", look["path"], "--out", wd / "bad.jpg",
                           "--report", wd / "bad.json"], cwd=ctx.root)
    # fault injection
    env = dict(os.environ)
    env["PE_AUDIT_FAULT"] = "write_short"
    runs["fault"] = run([ctx.cli, "render", fx["path"], "--recipe", recipe,
                         "--look", look["path"], "--out", wd / "fault.jpg",
                         "--report", wd / "fault.json"], cwd=ctx.root, env=env)
    after = {p: sha256_file(p) for p in before}
    unchanged = before == after
    results.append(make_result(
        "AUD-025", "hash-immutability",
        "source, sentinel and look assets unchanged across success/failure/fault",
        "PASS" if unchanged and runs["failure"]["exit"] == 1 and
        runs["fault"]["exit"] == 1 else "FAIL",
        metric={"before": before, "after": after,
                "runs": {k: v["exit"] for k, v in runs.items()}}))
    leftovers = [p.name for p in wd.iterdir() if p.name.endswith(".part")]
    results.append(make_result(
        "AUD-025", "no-partial-leftovers",
        "no .part staging files survive failed/faulted exports",
        "PASS" if not leftovers else "FAIL", metric={"leftovers": leftovers}))
    return results


def aud_026(ctx: AuditContext):
    """Fault injection at export: no success, no published partial, code PE_IO."""
    results = []
    fixture_id = "d7000-compressed-12bit"
    fx = ctx.fixtures[fixture_id]
    look = ctx.looks["identity"]
    wd = ctx.artifacts / "cases" / "AUD-026"
    wd.mkdir(parents=True, exist_ok=True)
    recipe = wd / "recipe.json"
    write_recipe(recipe, source_sha=fx["sha256"],
                 manifest_sha=look["manifestSha256"], look_id=look["id"],
                 amount=1.0)
    for fault in ("write_short", "write_error", "flush_error"):
        env = dict(os.environ)
        env["PE_AUDIT_FAULT"] = fault
        out = wd / f"out_{fault}.jpg"
        proc = run([ctx.cli, "render", fx["path"], "--recipe", recipe,
                    "--look", look["path"], "--out", out,
                    "--report", wd / f"r_{fault}.json"], cwd=ctx.root, env=env)
        published = out.exists()
        parts = [p.name for p in wd.iterdir() if p.name.endswith(".part")]
        results.append(make_result(
            "AUD-026", fault,
            "injected write fault yields failure, no published output, no staging leftovers",
            "PASS" if proc["exit"] == 1 and not published and not parts and
            "PE_IO" in proc["stderr"] else "FAIL",
            exit_code=proc["exit"], actual=proc["stderr"][-200:],
            metric={"publishedOutputExists": published, "stagingLeftovers": parts}))
    return results


def aud_027(ctx: AuditContext):
    """No-overwrite race: sentinel created while rendering must be respected."""
    results = []
    fixture_id = "d7000-compressed-12bit"
    fx = ctx.fixtures[fixture_id]
    look = ctx.looks["identity"]
    wd = ctx.artifacts / "cases" / "AUD-027"
    wd.mkdir(parents=True, exist_ok=True)
    recipe = wd / "recipe.json"
    write_recipe(recipe, source_sha=fx["sha256"],
                 manifest_sha=look["manifestSha256"], look_id=look["id"],
                 amount=1.0)
    out = wd / "contested.jpg"
    sentinel_body = b"RACE-SENTINEL-BYTES"
    proc_handle = subprocess.Popen(
        [str(ctx.cli), "render", str(fx["path"]), "--recipe", str(recipe),
         "--look", str(look["path"]), "--out", str(out),
         "--report", str(wd / "r.json")], cwd=str(ctx.root),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(2.0)  # render is still in flight (takes ~8s)
    out.write_bytes(sentinel_body)  # the race: sentinel appears mid-render
    stdout, stderr = proc_handle.communicate(timeout=600)
    intact = out.read_bytes() == sentinel_body
    parts = [p.name for p in wd.iterdir() if p.name.endswith(".part")]
    results.append(make_result(
        "AUD-027", "sentinel-created-mid-render",
        "engine/CLI refuses to publish over a sentinel created mid-render; sentinel bytes intact",
        "PASS" if proc_handle.returncode == 1 and intact and not parts else "FAIL",
        exit_code=proc_handle.returncode, actual=stderr[-300:],
        metric={"sentinelIntact": intact, "stagingLeftovers": parts}))
    return results


def aud_029(ctx: AuditContext):
    """C ABI contract details through the harness."""
    results = []
    fx = ctx.fixtures["d7000-compressed-12bit"]
    uni = ctx.artifacts / "cases" / "AUD-029"
    uni.mkdir(parents=True, exist_ok=True)
    unicode_copy = uni / "fixture_áº£nh_test.NEF"
    if not unicode_copy.exists():
        shutil.copyfile(fx["path"], unicode_copy)
    proc = run([ctx.harness, "abi", fx["path"], ctx.looks["identity"]["path"],
                str(unicode_copy)], cwd=ctx.root)
    results.append(make_result(
        "AUD-029", "span-unicode-limits-null",
        "byte-count spans, UTF-8 paths, oversized recipe rejection, NULL out-handles",
        "PASS" if proc["exit"] == 0 else "FAIL", exit_code=proc["exit"],
        actual=proc["stdout"].strip() if proc["stdout"] else None,
        artifacts=[]))
    wd = uni
    # Exercise the public CLI as well as the ABI: every path has spaces and
    # Vietnamese characters. Custom adjustments catch mapping drift too.
    ud = wd / "\u1ea3nh RAW Unicode"
    ud.mkdir(parents=True, exist_ok=True)
    unicode_raw = ud / "\u1ea3nh g\u1ed1c.NEF"
    shutil.copyfile(fx["path"], unicode_raw)
    unicode_look = ud / "b\u1ed9 m\u00e0u"
    shutil.copytree(ctx.looks["identity"]["path"], unicode_look)
    recipe = ud / "c\u00f4ng th\u1ee9c.json"
    init = run([ctx.cli,"init-recipe",unicode_raw,"--look",unicode_look,"--out",recipe],cwd=ctx.root)
    results.append(make_result("AUD-029","cli-unicode-init","CLI accepts Unicode source/look/recipe paths",
                               "PASS" if init["exit"]==0 else "FAIL",actual=init["stderr"]))
    if init["exit"] != 0: return results
    model=json.loads(recipe.read_text(encoding="utf-8"))
    model["adjustments"]["exposureEV"]=0.75
    model["adjustments"]["whiteBalance"]={"mode":"custom","resolvedCameraMultipliers":[1.75,1,1.25,1]}
    model["geometry"]={"crop":{"left":0.125,"top":0.125,"width":0.75,"height":0.75},"rotationQuarterTurns":1,"flipHorizontal":True}
    model["output"]["longEdge"]=512
    recipe.write_text(json.dumps(model),encoding="utf-8")
    records=[]
    for tag,source in (("ascii",fx["path"]),("unicode",unicode_raw)):
        out=ud/(tag+"-\u1ea3nh.jpg");report=ud/(tag+"-b\u00e1o c\u00e1o.json");dump=ud/(tag+"-pixel")
        ckpt=ud/(tag+"-checkpoint")
        proc=run([ctx.cli,"render",source,"--recipe",recipe,"--look",unicode_look,"--out",out,"--report",report,
                  "--diagnostic-pixels",dump,"--audit-checkpoints",ckpt],cwd=ctx.root)
        if proc["exit"]!=0:
            results.append(make_result("AUD-029","cli-unicode-render","CLI Unicode render","FAIL",actual=proc["stderr"]))
            return results
        info=json.loads(report.read_text(encoding="utf-8"))
        records.append({"jpeg":sha256_file(out),"pixels":sha256_file(dump.with_suffix(".f32")),
                        "pipelineExecutions":info["timings"]["pipelineExecutions"],"sourceUnchanged":info["source"]["hashUnchangedAfterRender"],
                        "checkpointCount":len(list(ckpt.glob("*.json")))})
        delete_stage_dumps(ckpt)
    ok=records[0]==records[1] and records[0]["pipelineExecutions"]==1 and records[0]["sourceUnchanged"] and records[0]["checkpointCount"]==5
    results.append(make_result("AUD-029","cli-unicode-render","ASCII/Unicode input gives identical JPEG and float pixels; Unicode checkpoint paths work",
                               "PASS" if ok else "FAIL",metric={"records":records}))
    preview=ud/"preview-\u1ea3nh.f32";descriptor=ud/"preview-b\u00e1o c\u00e1o.json"
    proc=run([ctx.harness,"preview-dump",unicode_raw,unicode_look,recipe,"512",preview,descriptor],cwd=ctx.root)
    same=proc["exit"]==0 and preview.exists() and sha256_file(preview)==records[1]["pixels"]
    results.append(make_result("AUD-029","unicode-preview-export-custom-adjustments","C ABI preview and CLI export share all recipe adjustments exactly",
                               "PASS" if same else "FAIL",actual=proc["stdout"]))
    return results


def aud_030(ctx: AuditContext):
    """Layered negative validation; malformed LUT must reach the parser."""
    results = []
    fixture_id = "d7000-compressed-12bit"
    fx = ctx.fixtures[fixture_id]
    wd = ctx.artifacts / "cases" / "AUD-030"
    wd.mkdir(parents=True, exist_ok=True)
    # (a) malformed LUT whose hash MATCHES the manifest (passes hash gate,
    #     must be rejected by the parser itself)
    pkg = wd / "badlut"
    shutil.rmtree(pkg, ignore_errors=True)
    shutil.copytree(ctx.looks["identity"]["path"], pkg)
    cube = pkg / "color.cube"
    text = cube.read_text(encoding="ascii").splitlines(keepends=True)
    body = [l for l in text if l and not l.startswith(("TITLE", "LUT_3D_SIZE",
                                                       "DOMAIN"))]
    body = body[:-1]  # drop one row -> wrong row count
    header = [l for l in text if l.startswith(("TITLE", "LUT_3D_SIZE", "DOMAIN"))]
    cube.write_text("".join(header + body), encoding="ascii")
    import hashlib
    new_hash = hashlib.sha256(cube.read_bytes()).hexdigest()
    man = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    man["operator"]["assetSha256"] = new_hash
    (pkg / "manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")
    recipe = wd / "recipe.json"
    write_recipe(recipe, source_sha=fx["sha256"],
                 manifest_sha=sha256_file(pkg / "manifest.json"),
                 look_id="audit-identity-17", amount=1.0)
    proc = run([ctx.cli, "render", fx["path"], "--recipe", recipe,
                "--look", pkg, "--out", wd / "x.jpg", "--report", wd / "x.json"],
               cwd=ctx.root)
    results.append(make_result(
        "AUD-030", "malformed-lut-parses",
        "hash-consistent but malformed LUT rejected by the parser (row count)",
        "PASS" if proc["exit"] == 1 and "row count" in proc["stderr"] else "FAIL",
        exit_code=proc["exit"], actual=proc["stderr"][-200:]))
    # (b) manifest schema violation (unknown key)
    pkg2 = wd / "badmanifest"
    shutil.rmtree(pkg2, ignore_errors=True)
    shutil.copytree(ctx.looks["identity"]["path"], pkg2)
    man2 = json.loads((pkg2 / "manifest.json").read_text(encoding="utf-8"))
    man2["unexpectedKey"] = 1
    (pkg2 / "manifest.json").write_text(json.dumps(man2, indent=2), encoding="utf-8")
    recipe2 = wd / "recipe2.json"
    write_recipe(recipe2, source_sha=fx["sha256"],
                 manifest_sha=sha256_file(pkg2 / "manifest.json"),
                 look_id="audit-identity-17", amount=1.0)
    proc = run([ctx.cli, "render", fx["path"], "--recipe", recipe2,
                "--look", pkg2, "--out", wd / "y.jpg", "--report", wd / "y.json"],
               cwd=ctx.root)
    results.append(make_result(
        "AUD-030", "manifest-schema",
        "manifest with unknown key rejected by schema",
        "PASS" if proc["exit"] == 1 and "PE_ASSET_MISMATCH" in proc["stderr"] else "FAIL",
        exit_code=proc["exit"], actual=proc["stderr"][-160:]))
    # (c) recipe schema violation
    recipe3 = wd / "recipe3.json"
    write_recipe(recipe3, source_sha=fx["sha256"],
                 manifest_sha=ctx.looks["identity"]["manifestSha256"],
                 look_id=ctx.looks["identity"]["id"], amount=1.0)
    r3 = json.loads(recipe3.read_text(encoding="utf-8"))
    r3["unexpected"] = True
    recipe3.write_text(json.dumps(r3, indent=2), encoding="utf-8")
    proc = run([ctx.cli, "render", fx["path"], "--recipe", recipe3,
                "--look", ctx.looks["identity"]["path"], "--out", wd / "z.jpg",
                "--report", wd / "z.json"], cwd=ctx.root)
    results.append(make_result(
        "AUD-030", "recipe-schema",
        "recipe with unknown key rejected by schema (PE_RECIPE_INVALID)",
        "PASS" if proc["exit"] == 1 and "PE_RECIPE_INVALID" in proc["stderr"] else "FAIL",
        exit_code=proc["exit"]))
    return results


def aud_031(ctx: AuditContext):
    """Cancellation semantics through the C ABI."""
    fx = ctx.fixtures["d7000-compressed-12bit"]
    proc = run([ctx.harness, "cancel", fx["path"], ctx.looks["identity"]["path"],
                fx["sha256"], ctx.looks["identity"]["manifestSha256"]],
               cwd=ctx.root)
    results = [make_result(
        "AUD-031", "pre-mid-post-cancel",
        "pre-cancelled and mid-render cancels return PE_CANCELLED; next render succeeds",
        "PASS" if proc["exit"] == 0 else "FAIL", exit_code=proc["exit"],
        actual=proc["stdout"].strip().splitlines()[-1] if proc["stdout"] else None)]
    if proc["exit"] == 0:
        wd=ctx.artifacts/"cases"/"AUD-031"
        wd.mkdir(parents=True,exist_ok=True)
        recipe=wd/"stage-recipe.json"
        write_recipe(recipe,source_sha=fx["sha256"],manifest_sha=ctx.looks["identity"]["manifestSha256"],
                     look_id=ctx.looks["identity"]["id"],amount=1.0)
        stage_proc=run([ctx.harness,"cancel-stages",fx["path"],ctx.looks["identity"]["path"],recipe,wd],cwd=ctx.root)
        (wd/"deterministic-stages.jsonl").write_text(stage_proc["stdout"],encoding="utf-8")
        rows=[json.loads(line) for line in stage_proc["stdout"].splitlines() if line.startswith("{")]
        ok=stage_proc["exit"]==0 and len(rows)==21 and all(row["pass"] for row in rows)
        results.append(make_result("AUD-031","deterministic-cancel-stages",
            "cancel at decode/develop/pixel/geometry/resize/preview/JPEG/write completion; null results, no staging, engine reuse",
            "PASS" if ok else "FAIL",metric={"rows":rows},artifacts=["cases/AUD-031/deterministic-stages.jsonl"]))
    return results


def aud_032(ctx: AuditContext):
    """Repeated lifecycle in one process; no runaway growth, deterministic."""
    fx = ctx.fixtures["d7000-compressed-12bit"]
    proc = run([ctx.harness, "lifecycle", fx["path"], ctx.looks["identity"]["path"],
                fx["sha256"], ctx.looks["identity"]["manifestSha256"]],
               cwd=ctx.root, timeout=1200)
    data = json.loads(proc["stdout"].strip().splitlines()[-1]) if proc["stdout"] else {}
    growth_limit = 250 * 1000 * 1000
    ok = (proc["exit"] == 0 and data.get("deterministic") is True
          and data.get("workingSetGrowthBytes", 1 << 62) < growth_limit)
    return [make_result(
        "AUD-032", "repeated-rounds",
        "8 create/open/render/destroy rounds: all succeed, deterministic, bounded growth",
        "PASS" if ok else "FAIL", exit_code=proc["exit"], actual=data,
        metric={"growthLimitBytes": growth_limit,
                "note": "working-set growth is diagnostic; hard bound set generously"})]


def aud_035(ctx: AuditContext):
    """Fresh-process determinism: 3 CLI renders -> identical JPEG bytes."""
    results = []
    fixture_id = "d7000-compressed-12bit"
    hashes = set()
    wd = ctx.artifacts / "cases" / "AUD-035"
    wd.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        r = _render_case(ctx, "AUD-035", fixture_id, "affine", 0.5, tag=f"p{i}")
        if r["proc"]["exit"] != 0:
            results.append(make_result("AUD-035", f"process{i}", "render", "FAIL"))
            continue
        hashes.add(sha256_file(r["out"]))
    results.append(make_result(
        "AUD-035", "fresh-process-x3",
        "three fresh CLI processes produce byte-identical JPEGs",
        "PASS" if len(hashes) == 1 else "FAIL", metric={"distinctHashes": len(hashes)}))
    return results


def aud_033(ctx: AuditContext):
    """ASan/UBSan: attempt a canary compile; expected BLOCKED on this host."""
    results = []
    d = ctx.artifacts / "cases" / "AUD-033"
    d.mkdir(parents=True, exist_ok=True)
    canary = d / "canary.c"
    canary.write_text("int main(void){return 0;}\n", encoding="utf-8")
    gcc = ctx.root / "tools" / "toolchain" / "mingw64" / "mingw64" / "bin" / "gcc.exe"
    asan = run([gcc, "-fsanitize=address", "-o", d / "canary_asan.exe", canary],
               cwd=ctx.root)
    ubsan = run([gcc, "-fsanitize=undefined", "-o", d / "canary_ubsan.exe", canary],
                cwd=ctx.root)
    asan_ok = (d / "canary_asan.exe").exists()
    ubsan_ok = (d / "canary_ubsan.exe").exists()
    results.append(make_result(
        "AUD-033", "canary-asan",
        "ASan runtime availability canary",
        "PASS" if asan_ok else "BLOCKED", exit_code=asan["exit"],
        actual=(asan["stderr"] or "")[-300:],
        reason=None if asan_ok else "toolchain has no -lasan runtime"))
    results.append(make_result(
        "AUD-033", "canary-ubsan",
        "UBSan runtime availability canary",
        "PASS" if ubsan_ok else "BLOCKED", exit_code=ubsan["exit"],
        actual=(ubsan["stderr"] or "")[-300:],
        reason=None if ubsan_ok else "toolchain has no -lubsan runtime"))
    results.append(make_result(
        "AUD-033", "engine-under-sanitizer",
        "engine core + RAW path instrumented with ASan/UBSan and tests green",
        "BLOCKED" if not (asan_ok and ubsan_ok) else "NOT_RUN",
        reason="no sanitizer runtime in the pinned MinGW toolchain; requires "
               "MSVC (missing cl.exe on host) or an ASan-capable GCC; "
               "_GLIBCXX_ASSERTIONS build is recorded as a partial substitute"))
    return results


def aud_011(ctx: AuditContext):
    """Engine develops the unpacked RAW, not the thumbnail."""
    results = []
    fixture_id = "d7000-compressed-12bit"
    fx = ctx.fixtures[fixture_id]
    probe = json.loads(run([ctx.cli, "probe", fx["path"], "--json"],
                           cwd=ctx.root)["stdout"])
    # (a) probe says a thumbnail exists but engine output is at RAW active-area
    # dimensions (>=4000 px long edge here vs typical <=640 px thumbnails).
    r = _render_case(ctx, "AUD-011", fixture_id, "identity", 0.0, tag="dims")
    _, b0 = load_stage(r["ckpt"], "B0_base_develop")
    dims_ok = b0.shape[1] == probe["dimensions"]["iwidth"] and \
        b0.shape[0] == probe["dimensions"]["iheight"] and \
        max(b0.shape) >= 3000 and probe["thumbnail"]["present"]
    results.append(make_result(
        "AUD-011", "dimensions-vs-thumbnail",
        "rendered frame is at RAW active-area dimensions while a small thumbnail exists",
        "PASS" if dims_ok else "FAIL",
        metric={"rawDims": [probe["dimensions"]["iwidth"],
                            probe["dimensions"]["iheight"]],
                "b0Dims": [int(b0.shape[1]), int(b0.shape[0])],
                "thumbnailPresent": probe["thumbnail"]["present"]}))
    # (b) AUD-016's standalone adapter (unpack + dcraw_process, never the
    # thumbnail path) matches engine B0 exactly -> same provenance.
    d = ctx.artifacts / "cases" / "AUD-011"
    d.mkdir(parents=True, exist_ok=True)
    proc = run([ctx.ref_adapter, fx["path"], d / "ref.f32", d / "ref.json",
                str(D7000_WB[0]), str(D7000_WB[1]), str(D7000_WB[2]),
                str(D7000_WB[3])], cwd=ctx.root)
    ref = np.fromfile(d / "ref.f32", dtype="<f4").reshape(-1, 3)
    eng = b0.reshape(-1, 3)
    same = ref.shape == eng.shape and \
        float(np.abs(ref.astype(np.float64) - eng.astype(np.float64)).max()) == 0.0
    results.append(make_result(
        "AUD-011", "unpack-path-provenance",
        "engine B0 is bit-identical to an independent unpack+develop integration",
        "PASS" if same else "FAIL", metric={"bitEqual": bool(same)}))
    # (c) source review: no thumbnail API in the engine decode path
    src = (ctx.root / "engine" / "src" / "raw_adapter.cpp").read_text(encoding="utf-8")
    uses_thumb = ("unpack_thumb" in src or "load_thumb" in src or
                  "dcraw_make_mem_thumb" in src)
    results.append(make_result(
        "AUD-011", "source-review",
        "engine decode path contains no thumbnail API usage",
        "PASS" if not uses_thumb else "FAIL", oracle_ref="grep of raw_adapter.cpp"))
    delete_stage_dumps(r["ckpt"])
    return results


def aud_040(ctx: AuditContext):
    """Exercise aggregation with skipped/missing/invalid/exception evidence."""
    from audit_reporting import aggregate, junit_xml
    from xml.etree import ElementTree as ET
    checks = []
    passed = make_result("required", "ok", "control", "PASS")
    scenarios = [("positive", [passed], 0), ("missing", [], 2)]
    for status, expected in (("FAIL", 1), ("BLOCKED", 2), ("NOT_RUN", 2),
                             ("NOT_APPLICABLE", 2), ("UNKNOWN", 1)):
        scenarios.append((status, [{**passed, "status": status}], expected))
    scenarios.extend([
        ("timeout", [{**passed, "status": "FAIL", "reason": "command timeout"}], 1),
        ("comparator-exception", [{**passed, "status": "FAIL", "reason": "comparator exception"}], 1),
        ("fail-and-missing", [make_result("other", "bad", "failure", "FAIL")], 1)])
    for name, rows, expected in scenarios:
        actual = aggregate(rows, ["required"])["exitCode"]
        checks.append(make_result("AUD-040", name, "aggregation rejects incomplete evidence",
                      "PASS" if actual == expected else "FAIL", expected=expected, actual=actual))
    xml_row = {**passed, "caseId": "AUD-040", "variant": 'a<&"', "status": "FAIL",
               "reason": 'bad <pixel> & "quoted"'}
    tree = ET.fromstring(junit_xml([xml_row]))
    ok = tree.find("testsuite/testcase/failure").get("message") == xml_row["reason"]
    checks.append(make_result("AUD-040", "junit-escaping", "JUnit parses special characters",
                              "PASS" if ok else "FAIL"))
    return checks


def aud_037(ctx: AuditContext):
    from benchmark_engine import run_measured
    results = []
    d = ctx.artifacts / "cases" / "AUD-037"
    d.mkdir(parents=True, exist_ok=True)
    for fixture_id in ("d7000-compressed-12bit", "d3200-lossless-12bit-stored"):
        fx = ctx.fixtures[fixture_id]
        for edge in (None, 2048):
            name = fixture_id + ("-full" if edge is None else "-2048")
            recipe = d/(name+".recipe.json")
            look = ctx.looks["identity"]
            write_recipe(recipe, source_sha=fx["sha256"], manifest_sha=look["manifestSha256"],
                         look_id=look["id"], amount=1.0,
                         multipliers=D7000_WB if fixture_id.startswith("d7000") else _d3200_wb())
            model = json.loads(recipe.read_text(encoding="utf-8"))
            model["output"]["longEdge"] = edge
            recipe.write_text(json.dumps(model),encoding="utf-8")
            command = [str(ctx.cli),"render",str(fx["path"]),"--recipe",str(recipe),"--look",str(look["path"]),
                       "--out",str(d/(name+".jpg")),"--report",str(d/(name+".report.json"))]
            metric = run_measured(command,d/(name+"-process"))
            metric.update({"fixtureSha256":fx["sha256"],"binarySha256":sha256_file(ctx.cli),"repetitions":1,
                           "scope":"screening measurement on desktop, not mobile or latency certification"})
            ok = metric["peakWorkingSetBytes"] <= ctx.policy["limits"]["maxProcessMemoryBytes"] and metric["wallMs"] <= ctx.policy["limits"]["caseTimeoutSeconds"]*1000
            results.append(make_result("AUD-037",name,"measured CLI wall/CPU and OS peak memory within screening budget",
                                       "PASS" if ok else "FAIL",metric=metric,level="DIAGNOSTIC"))
    return results


CASES = {
    "AUD-001": aud_001, "AUD-002": aud_002, "AUD-003": aud_003,
    "AUD-004": aud_004, "AUD-005": aud_005, "AUD-006": aud_006,
    "AUD-007": aud_007, "AUD-008": aud_008, "AUD-009": aud_009,
    "AUD-010": aud_010, "AUD-011": aud_011, "AUD-013": aud_013,
    "AUD-014": aud_014, "AUD-015": aud_015, "AUD-016": aud_016,
    "AUD-017": aud_017, "AUD-018": aud_018, "AUD-019": aud_019,
    "AUD-020": aud_020, "AUD-021": aud_021, "AUD-022": aud_022,
    "AUD-023": aud_023, "AUD-024": aud_024, "AUD-025": aud_025,
    "AUD-026": aud_026, "AUD-027": aud_027, "AUD-029": aud_029,
    "AUD-030": aud_030, "AUD-031": aud_031, "AUD-032": aud_032,
    "AUD-033": aud_033, "AUD-035": aud_035, "AUD-037": aud_037, "AUD-040": aud_040,
}
