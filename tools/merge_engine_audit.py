#!/usr/bin/env python3
"""Aggregate a full run and a later scoped regression, preserving both builds."""
import argparse
import hashlib
import json
from pathlib import Path

from audit_reporting import aggregate, junit_xml


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for data in iter(lambda: f.read(1 << 20), b""):
            h.update(data)
    return h.hexdigest()


def read(run, filename):
    return json.loads((run / filename).read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full-run", type=Path, required=True)
    ap.add_argument("--regression-run", type=Path, required=True)
    ap.add_argument("--artifact-dir", type=Path, required=True)
    args = ap.parse_args()
    full, regression, out = [p.resolve() for p in
                             (args.full_run, args.regression_run, args.artifact_dir)]
    if out.exists():
        raise RuntimeError("aggregate destination must be fresh")
    full_summary = read(full, "summary.json")
    reg_summary = read(regression, "summary.json")
    assert sha(full / "policy.json") == sha(regression / "policy.json"), "policy drift"
    assert not reg_summary["failedVariants"], "regression failures remain"
    full_rows, reg_rows = read(full, "results.json"), read(regression, "results.json")
    replaced = {r["caseId"] for r in reg_rows}
    rows = []
    for component, values in ((full, [r for r in full_rows if r["caseId"] not in replaced]),
                              (regression, reg_rows)):
        for row in values:
            row["evidenceRun"] = str(component)
            row["artifacts"] = [str(Path(p) if Path(p).is_absolute() else component / p)
                                for p in row.get("artifacts", [])]
            rows.append(row)
    check = aggregate(rows, full_summary["effectiveRequired"])
    assert not check["missing"], "aggregate has missing required reports"
    out.mkdir(parents=True)
    env = read(regression, "environment.json")
    components = []
    for component in (full, regression):
        components.append({"run": str(component), "summary": read(component, "summary.json"),
                           "environmentSha256": sha(component / "environment.json"),
                           "manifestSha256": sha(component / "manifest.sha256"),
                           "binaries": read(component, "environment.json")["binaries"]})
    env["componentRuns"] = components
    env["componentExecutionSourceUpdates"] = {
        str(full): read(full, "environment.json").get("executionSourceUpdates", {})}
    env["evidenceNote"] = ("Full pre-fault-hook audit and scoped post-fix regression use different builds; "
                           "each result names its executed evidence run. Unaffected math/RAW/mutation results "
                           "are retained; export/immutability/normal-output checks rerun after adding test-only fault hooks.")
    (out / "environment.json").write_text(json.dumps(env, indent=2), encoding="utf-8")
    (out / "policy.json").write_bytes(full.joinpath("policy.json").read_bytes())
    before_jpeg = full / "cases/AUD-025/ok.jpg"
    after_jpeg = regression / "cases/AUD-025/ok.jpg"
    same = sha(before_jpeg) == sha(after_jpeg)
    assert same, "normal output changed after fault-hook patch; broader rerun required"
    (out / "normal-output-comparison.json").write_text(json.dumps({
        "before": str(before_jpeg), "after": str(after_jpeg), "bitIdentical": same,
        "sha256": sha(after_jpeg), "scope": "full-resolution identity JPEG, no fault environment"
    }, indent=2), encoding="utf-8")
    if (full / "dependency-verification.json").exists():
        (out / "dependency-verification.json").write_bytes((full / "dependency-verification.json").read_bytes())
    summary = {**full_summary, "componentRuns": [str(full), str(regression)],
               "supersededCaseIds": sorted(replaced), "exitCode": check["exitCode"],
               "conclusion": "FAIL" if check["exitCode"] == 1 else "INCOMPLETE (required evidence remains BLOCKED/NOT_RUN)"
               if check["exitCode"] == 2 else "All effective-required cases PASS; policy remains PROPOSED",
               "counts": {"total": len(rows), "pass": sum(r["status"] == "PASS" for r in rows),
                          "fail": len(check["fails"]), "blocked": len(check["incomplete"]),
                          "notApplicable": sum(r["status"] == "NOT_APPLICABLE" for r in rows),
                          "byStatus": check["countsByStatus"]},
               "failedVariants": [r["caseId"] + "/" + r["variant"] for r in check["fails"]],
               "blockedVariants": [r["caseId"] + "/" + r["variant"] + " :: " + str(r.get("reason"))
                                   for r in check["incomplete"]], "missingRequiredReports": check["missing"]}
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (out / "junit.xml").write_text(junit_xml(rows), encoding="utf-8")
    (out / "manifest.sha256").write_text("\n".join(
        f"{sha(p)}  {p.relative_to(out).as_posix()}" for p in sorted(out.rglob("*"))
        if p.is_file() and p.name != "manifest.sha256") + "\n", encoding="utf-8")
    print(json.dumps({"conclusion": summary["conclusion"], "counts": summary["counts"]}))


if __name__ == "__main__":
    main()
