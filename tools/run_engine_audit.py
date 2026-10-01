#!/usr/bin/env python3
"""One-command G1 independent audit runner.

Exit codes (per audit policy):
  0 - every effective-required case PASS
  1 - at least one FAIL anywhere
  2 - no FAIL, but at least one effective-required case is BLOCKED/NOT_RUN,
      or a required report is missing (fail-closed; AUD-040)
Runner errors never become engine PASS.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACCEPT = HERE.parent / "tests" / "acceptance"
ENGINE_ROOT = HERE.parent
AUDIT_PACKAGE = ENGINE_ROOT.parent / "RAW_Engine_Independent_Audit_v1"


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_oracle_module(path: Path):
    spec = importlib.util.spec_from_file_location("audit_oracle_ref", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["audit_oracle_ref"] = mod
    spec.loader.exec_module(mod)
    return mod


from audit_reporting import aggregate, junit_xml


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-dir", type=Path, required=True,
                    help="fresh directory for this run (never reused)")
    ap.add_argument("--cases", default="",
                    help="comma-separated subset, e.g. AUD-004,AUD-006")
    ap.add_argument("--full-required", action="store_true",
                    help="run the full effective-required set from the policy")
    ap.add_argument("--with-mutations", action="store_true",
                    help="also run AUD-039 mutation testing (slow)")
    args = ap.parse_args()

    artifacts: Path = args.artifact_dir.resolve()
    if artifacts.exists():
        print(f"REFUSING to reuse an existing artifact directory: {artifacts}",
              file=sys.stderr)
        return 2
    artifacts.mkdir(parents=True)

    sys.path.insert(0, str(ACCEPT))
    sys.path.insert(0, str(HERE))
    policy = json.loads((ACCEPT / "audit_policy.json").read_text(encoding="utf-8"))
    fixtures = json.loads((ACCEPT / "fixture_manifest.json").read_text(encoding="utf-8"))

    # Verify the oracle copy matches the reference package byte-for-byte.
    oracle_src = AUDIT_PACKAGE / "reference" / "oracle.py"
    oracle_copy = ACCEPT / "oracle" / "oracle.py"
    oracle_copy.parent.mkdir(parents=True, exist_ok=True)
    if not oracle_copy.exists():
        shutil.copyfile(oracle_src, oracle_copy)
    if sha256_file(oracle_src) != sha256_file(oracle_copy):
        print("FATAL: oracle copy diverges from the reference package",
              file=sys.stderr)
        return 2
    oracle_sha = sha256_file(oracle_copy)

    # Integrity: audit look packages against their index manifest.
    idx = json.loads((AUDIT_PACKAGE / "reference" / "generated_looks_17" /
                      "index.json").read_text(encoding="utf-8"))
    looks = {}
    for p in idx["packages"]:
        folder = AUDIT_PACKAGE / "reference" / "generated_looks_17" / p["package"]
        if sha256_file(folder / "manifest.json") != p["manifestSha256"] or \
                sha256_file(folder / "color.cube") != p["assetSha256"]:
            print(f"FATAL: look package integrity failure: {p['package']}",
                  file=sys.stderr)
            return 2
        looks[p["kind"]] = {"path": folder, "id": f"audit-{p['kind']}-17",
                            "manifestSha256": p["manifestSha256"],
                            "assetSha256": p["assetSha256"]}
    fixture_map = {f["id"]: f for f in fixtures["fixtures"] if f.get("role") != "orientation"}
    for f in fixtures["fixtures"]:
        actual = sha256_file(ENGINE_ROOT / f["path"])
        if actual != f["sha256"]:
            print(f"FATAL: RAW fixture hash mismatch: {f['path']}", file=sys.stderr)
            return 2

    # environment.json: full provenance snapshot for this run
    env = {
        "sourceHashes": {str(p.relative_to(ENGINE_ROOT)): sha256_file(p)
                         for folder in ("engine", "cli", "tests", "tools")
                         for p in (ENGINE_ROOT / folder).rglob("*") if p.is_file()
                         and "toolchain" not in p.parts and "__pycache__" not in p.parts
                         and p.name != "test_matrix.json"},
        "runnerSha256": sha256_file(Path(__file__)),
        "dependencyManifestSha256": sha256_file(ENGINE_ROOT / "third_party/manifest.json"),
        "gitStatus": "workspace has no .git; source hashes and resume snapshot retained",
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "policySha256": sha256_file(ACCEPT / "audit_policy.json"),
        "oracleSha256": oracle_sha,
        "fixtureManifestSha256": sha256_file(ACCEPT / "fixture_manifest.json"),
        "binaries": {b: sha256_file(ENGINE_ROOT / "build-audit-base" / b) for b in
                     ("photo-cli.exe", "photoengine_tests.exe",
                      "photoengine_audit_harness.exe", "ref_adapter.exe")},
        "fixtures": {f["id"]: f["sha256"] for f in fixtures["fixtures"]},
        "lookPackages": {k: v["manifestSha256"] for k, v in looks.items()},
        "testOnlyHooks": [
            "render.cpp audit_dump checkpoints (B0..B4) via --audit-checkpoints",
            "export.cpp PE_AUDIT_FAULT export fault injection (write_short/write_error/flush_error)",
        ],
        "lcmsReference": {"path": __import__("os").environ.get("PE_AUDIT_LCMS_DLL"),
                          "sha256": sha256_file(__import__("os").environ["PE_AUDIT_LCMS_DLL"]) if __import__("os").environ.get("PE_AUDIT_LCMS_DLL") else None},
        "policyApprovalStatus": policy["approvalStatus"],
    }
    env["sourceHashes"]["CMakeLists.txt"] = sha256_file(ENGINE_ROOT/"CMakeLists.txt")
    (artifacts / "environment.json").write_text(json.dumps(env, indent=2),
                                                encoding="utf-8")
    shutil.copyfile(ACCEPT / "audit_policy.json", artifacts / "policy.json")

    import audit_cases
    importlib.reload(audit_cases)
    ctx = audit_cases.AuditContext(ENGINE_ROOT, artifacts, policy, fixture_map,
                                   looks, oracle_copy)

    if args.cases and args.full_required:
        ap.error("--cases and --full-required cannot be combined")
    if args.cases:
        requested = [c.strip() for c in args.cases.split(",") if c.strip()]
    else:
        requested = (policy["coreRequired"] + policy["conditionalRequired"])
    if args.full_required:
        requested += policy["diagnostic"] + list(policy["notApplicable"]) + list(policy["notRun"])
    if args.with_mutations:
        requested.append("AUD-039")
    requested = list(dict.fromkeys(requested))

    all_results = []
    for case_id in requested:
        started = time.time()
        if case_id == "AUD-039" and args.with_mutations:
            sys.path.insert(0, str(HERE))
            import run_mutations
            try:
                rows = run_mutations.run_mutations(ctx, artifacts, [], all_results)
            except Exception as exc:
                rows = [audit_cases.make_result("AUD-039", "runner", "mutation execution",
                        "FAIL", reason=f"runner exception: {exc}", actual=traceback.format_exc())]
            all_results.extend(rows)
            cdir = artifacts / "cases" / case_id
            cdir.mkdir(parents=True, exist_ok=True)
            (cdir / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
            continue
        fn = audit_cases.CASES.get(case_id)
        if fn is None:
            reason = policy["notApplicable"].get(case_id) or policy["notRun"].get(case_id)
            status = "NOT_APPLICABLE" if case_id in policy["notApplicable"] else "NOT_RUN"
            if case_id == "AUD-039":
                reason = "mutation testing requires --with-mutations"
            all_results.append(audit_cases.make_result(case_id, "runner", "case implementation",
                status, reason=reason or "no implementation registered for this case ID"))
            continue
        started = time.time()
        try:
            rows = fn(ctx)
            if not rows:
                raise RuntimeError("case returned no variants")
        except Exception as exc:  # runner error is never an engine PASS
            rows = [audit_cases.make_result(
                case_id, "runner", "case execution", "FAIL",
                reason=f"runner exception: {exc}",
                actual=traceback.format_exc()[-1500:])]
        for r in rows:
            r["seconds"] = round(time.time() - started, 1)
            all_results.append(r)
        # incremental per-case results so a long run is inspectable mid-flight
        cdir = artifacts / "cases" / case_id
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "results.json").write_text(
            json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        statuses = {r["status"] for r in rows}
        worst = "PASS"
        if "FAIL" in statuses:
            worst = "FAIL"
        elif statuses - {"PASS"}:
            worst = "INCOMPLETE"
        print(f"[{worst:>10}] {case_id} ({round(time.time() - started, 1)}s, "
              f"{len(rows)} variants)", flush=True)

    # ---------------- fail-closed aggregation (AUD-040) ----------------
    effective = policy["coreRequired"] + policy["conditionalRequired"]
    aggregation = aggregate(all_results, effective)
    missing = aggregation["missing"]
    fails = aggregation["fails"]
    blocked = aggregation["incomplete"]
    not_applicable = [r for r in all_results if r["status"] == "NOT_APPLICABLE"]
    summary = {
        "schemaVersion": 1, "planId": "G1-INDEPENDENT-AUDIT-v1",
        "policyApprovalStatus": policy["approvalStatus"],
        "effectiveRequired": effective,
        "requested": requested,
        "missingRequiredReports": missing,
        "counts": {"total": len(all_results),
                   "pass": sum(1 for r in all_results if r["status"] == "PASS"),
                   "fail": len(fails), "blocked": len(blocked),
                   "notApplicable": len(not_applicable),
                   "byStatus": aggregation["countsByStatus"]},
        "failedVariants": [f"{r['caseId']}/{r['variant']}" for r in fails],
        "blockedVariants": [f"{r['caseId']}/{r['variant']} :: {r.get('reason')}"
                            for r in blocked],
        "conclusion": None,
        "enginePassClaim": False,
        "note": "Per-layer conclusions live in the QA report; a single aggregate "
                "PASS is forbidden while any effective-required case is not PASS.",
    }
    exit_code = aggregation["exitCode"]
    summary["exitCode"] = exit_code
    if exit_code == 1:
        summary["conclusion"] = "FAIL"
    elif exit_code == 2:
        summary["conclusion"] = "INCOMPLETE (effective-required evidence remains missing/BLOCKED/NOT_RUN)"
    else:
        summary["conclusion"] = "All effective-required cases PASS; policy approval remains " + policy["approvalStatus"]
    (artifacts / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (artifacts / "junit.xml").write_text(junit_xml(all_results), encoding="utf-8")
    (artifacts / "results.json").write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest_lines = [f"{sha256_file(p)}  {p.relative_to(artifacts).as_posix()}"
                      for p in sorted(artifacts.rglob("*")) if p.is_file()
                      and p.name != "manifest.sha256"]
    (artifacts / "manifest.sha256").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in
                      ("conclusion", "counts", "missingRequiredReports")}, indent=1))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
