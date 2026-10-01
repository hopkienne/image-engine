#!/usr/bin/env python3
"""Create the audit matrix and QA handoff from completed runner evidence."""
import argparse
from collections import Counter
import difflib
import hashlib
import json
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

from audit_reporting import aggregate

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT.parent / "RAW_Engine_Independent_Audit_v1"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def status(rows):
    values = {r["status"] for r in rows}
    return next((s for s in ("FAIL", "BLOCKED", "NOT_RUN", "NOT_APPLICABLE", "PASS")
                 if s in values), "NOT_RUN")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    args = ap.parse_args()
    run = args.run.resolve()
    results = json.loads((run / "results.json").read_text(encoding="utf-8"))
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    env = json.loads((run / "environment.json").read_text(encoding="utf-8"))
    policy = json.loads((run / "policy.json").read_text(encoding="utf-8"))
    check = aggregate(results, summary["effectiveRequired"])
    assert check["exitCode"] == summary["exitCode"], "aggregate/report disagreement"
    assert not check["missing"], "full handoff cannot omit required case reports"
    assert not check["invalid"], "invalid result status"
    ET.parse(run / "junit.xml")
    checked_sources = 0
    for relative, recorded in env.get("sourceHashes", {}).items():
        path = ROOT / relative
        if path.suffix in {".cpp", ".h", ".py"}:
            recorded = env.get("executionSourceUpdates", {}).get(relative, {}).get(
                "executedSha256", recorded)
            assert digest(path) == recorded, f"tested source changed during run: {relative}"
            checked_sources += 1
    for name, recorded in env["binaries"].items():
        assert digest(Path(env["buildDirectory"]) / name) == recorded, f"binary changed: {name}"
    grouped = {}
    for row in results:
        grouped.setdefault(row["caseId"], []).append(row)
    matrix = json.loads((PACKAGE / "templates/test_matrix.json").read_text(encoding="utf-8"))
    matrix.update(status=summary["conclusion"], engineTested=True,
                  runId=run.name, artifactRoot=str(run),
                  policyApprovalStatus=policy["approvalStatus"],
                  generatorSha256=digest(Path(__file__)))
    for case in matrix["cases"]:
        cid = case["caseId"]
        rows = grouped.get(cid, [])
        case.update(status=status(rows), effectiveRequired=cid in summary["effectiveRequired"],
                    variants=rows, artifactPaths=sorted({str(path) for row in rows
                    for path in row.get("artifacts", [])}),
                    limitations=[r["reason"] for r in rows if r.get("reason")],
                    metrics=[r["metric"] for r in rows if r.get("metric") is not None],
                    applicabilityReason=policy["conditionalApplicability"].get(cid)
                    or policy["notApplicable"].get(cid) or policy["notRun"].get(cid))
    # Retain the exact implementation diff against the resume snapshot.
    before_zip = ROOT / "artifacts/engine-audit/resume-snapshot-20260930/source-before.zip"
    changes = []
    if before_zip.exists():
        with zipfile.ZipFile(before_zip) as archive:
            existing = {name.replace("\\", "/") for name in archive.namelist()}
            for name in archive.namelist():
                relative = name.replace("\\", "/")
                current = ROOT / relative
                if not current.is_file() or current.suffix not in {".cpp", ".h", ".py", ".txt"}:
                    continue
                old = archive.read(name).decode("utf-8", errors="replace")
                new = current.read_text(encoding="utf-8", errors="replace")
                if old.splitlines() != new.splitlines():
                    changes.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                   fromfile="before/" + relative, tofile="after/" + relative))
            for folder in ("engine", "cli", "tests/acceptance", "tools"):
                for current in (ROOT / folder).rglob("*"):
                    relative = current.relative_to(ROOT).as_posix()
                    if current.is_file() and current.suffix in {".cpp", ".h", ".py"} \
                            and "toolchain" not in current.parts and relative not in existing:
                        changes.extend(difflib.unified_diff([], current.read_text(encoding="utf-8").splitlines(True),
                                       fromfile="/dev/null", tofile="after/" + relative))
    (run / "resume-changes.patch").write_text("".join(changes), encoding="utf-8")
    text = json.dumps(matrix, indent=2, ensure_ascii=False)
    (ROOT / "tests/acceptance/test_matrix.json").write_text(text, encoding="utf-8")
    (run / "test_matrix.json").write_text(text, encoding="utf-8")
    case_lookup = {c["caseId"]: c for c in matrix["cases"]}

    def layer(ids):
        return status([{"status": case_lookup[c]["status"]} for c in ids])

    layers = [
        ("LUT/domain/recipe", [f"AUD-{i:03}" for i in range(4, 11)], "Oracle công thức đóng; kiểm tra toàn pixel B1→B2, B3/B4 composition."),
        ("RAW adapter/baseline", ["AUD-011", "AUD-013", "AUD-014", "AUD-015", "AUD-016"], "Hai Nikon Bayer; reference adapter vẫn dùng chung LibRaw, không chứng minh màu vật lý."),
        ("Orientation/geometry/export/ICC", ["AUD-018", "AUD-019", "AUD-020", "AUD-021", "AUD-023", "AUD-024"], "Thiếu RAW orientation khác 0 và phép đo ICC float XYZ theo policy."),
        ("Integrity/fault/cancel/lifecycle", ["AUD-022", "AUD-025", "AUD-026", "AUD-027", "AUD-029", "AUD-030", "AUD-031", "AUD-032"], "Cancel giữa render dùng delay 300 ms; chưa có barrier stage xác định."),
        ("Memory safety/fuzz", ["AUD-033", "AUD-034"], "Thiếu runtime ASan/UBSan và campaign libFuzzer."),
        ("Tái lập host", ["AUD-035"], "Ba process cùng toolchain/host; chưa chứng minh cross-build/cross-platform."),
        ("Mutation sensitivity", ["AUD-039"], "Compile error, timeout và detector exception không được tính là semantic kill."),
    ]
    required_counts = Counter(case_lookup[c]["status"] for c in summary["effectiveRequired"])
    all_counts = Counter(c["status"] for c in matrix["cases"])
    mutants = [r for r in grouped.get("AUD-039", []) if r["variant"].startswith("MUT-")]
    now = max((r.get("utc", "") for r in results), default=env["utc"])
    report = [
        "# G1 Independent Audit Report", "",
        f"**Kết luận: {summary['conclusion']}. G1 chưa được nghiệm thu.**", "",
        f"Bộ bằng chứng `{run.name}`, snapshot build cuối `{env['utc']}`, kết quả cuối `{now}` (UTC). "
        f"Policy `{policy['policyId']}` vẫn **{policy['approvalStatus']}**; không thay required IDs hoặc tolerance để làm xanh kết quả.", "",
        "## 1. Build và phạm vi", "",
        "Windows / MinGW-w64 GCC 16.2.0, Release C++17, static linkage, core `-ffp-contract=off`. "
        "AUD-001 build source hiện tại vào thư mục mới và chạy lại unit/contract suite trên binary đó. "
        "Workspace không có `.git`; dùng snapshot trước sửa, source hash và patch thay cho commit/diff Git.", "",
        f"Artifact root: `{run}`. Các hash policy/oracle/dependency/source/binary nằm trong `environment.json`; "
        "recipe/asset/command/checkpoint descriptor được giữ trong artifact và manifest. Snapshot trước tiếp tục: "
        "`artifacts/engine-audit/resume-snapshot-20260930/source-before.zip`.", "",
        "Mutation runner được hoàn thiện phạm vi probe trước khi module AUD-039 được import; hash ban đầu và hash module "
        "thực thi được ghi riêng trong `executionSourceUpdates` ở environment component đầy đủ. Code production và ngưỡng không thay đổi trong lượt đầy đủ. "
        "LUT mutants dùng một frame phân biệt đầy đủ pixel, với đúng variant đã PASS ở baseline.", "",
        "Nếu `componentRuns` có trong environment/summary, đây là aggregate của lượt đầy đủ trước sửa hook và "
        "lượt hồi quy sau sửa; mỗi variant có `evidenceRun` để xác định binary/source đã chạy. "
        "Không gọi các kết quả trên hai build là một lượt thực thi duy nhất. Output JPEG identity không fault được so byte-for-byte "
        "trong `normal-output-comparison.json`.", "",
        f"Policy SHA-256: `{env['policySha256']}`. Oracle SHA-256: `{env['oracleSha256']}`.", "",
        "Fixtures: `d7000-compressed-12bit`, `d3200-lossless-12bit-stored`; bytes/hash đã đối chiếu manifest. "
        "Nguồn và khai báo license CC0 được lưu trong `tests/acceptance/fixture_manifest.json`; lượt tiếp tục không tải hay upload ảnh. "
        "LUT dimension 17: identity, permutation, constant, affine, multiaffine, square-grid.", "",
        "## 2. Kết luận riêng từng lớp", "",
        "| Lớp | Trạng thái suite | Case | Giới hạn |", "|---|---|---|---|"]
    for name, ids, limit in layers:
        report.append(f"| {name} | {layer(ids)} | {', '.join(ids)} | {limit} |")
    report += ["| Chất lượng ảnh G2 | NOT_RUN | AUD-036 | Chưa có holdout/chart/reference developer khác. |",
               "| Mobile/performance G3 | NOT_RUN | AUD-037/038 | Chưa chạy iOS/Android hoặc budget thiết bị. |", "",
               "## 3. Claim và bằng chứng", "",
               "Non-identity LUT được chạy qua loader và production CLI trên RAW thật, so toàn pixel với oracle Python ngoài tiến trình. "
               "Checkpoint B1 là đầu vào kiểm tra look; reference adapter conformance vẫn chia sẻ LibRaw. "
               "Preview/export hiện được đối chiếu bằng pixel C ABI thật, gồm alpha và stride native. "
               "ICC 8-bit bridge có kết quả riêng; nó không thay phép đo float XYZ còn BLOCKED.", "",
               "## 4. Kết quả đầy đủ", "",
               f"33 effective-required groups: `{dict(required_counts)}`. Toàn bộ 40 groups: `{dict(all_counts)}`. "
               f"Runner exit code `{summary['exitCode']}`; missing required reports `{summary['missingRequiredReports']}`. "
               "Không tính tỷ lệ PASS trên riêng các test đã chạy.", "",
               "Chi tiết variant/metric/reason: [test_matrix.json](../../tests/acceptance/test_matrix.json). "
               f"Kết quả máy đọc được: [summary.json](../../artifacts/engine-audit/{run.name}/summary.json), "
               f"[results.json](../../artifacts/engine-audit/{run.name}/results.json), "
               f"[junit.xml](../../artifacts/engine-audit/{run.name}/junit.xml).", "",
               "| Case | Level | Required | Trạng thái | Variants |", "|---|---|---|---|---|"]
    for c in matrix["cases"]:
        report.append(f"| {c['caseId']} | {c['level']} | {'yes' if c['effectiveRequired'] else 'no'} | {c['status']} | {len(c['variants'])} |")
    report += ["", "## 5. Bug và sửa chữa", "",
        "- **ICC TRC (sửa ở lượt trước):** dữ liệu trước sửa trong `bugfixes/AUD-024-trc/results_before_fix.json` "
        "ghi sai khác tối đa 135 mức 8-bit qua trusted lcms. Lượt đầy đủ hiện tại chạy lại AUD-024; float XYZ vẫn BLOCKED.",
        "- **Harness escape JSON:** snapshot có cú pháp C++ sai khi escape backslash. Sửa literal và escape quote; "
        "AUD-022/029/031/032 chạy lại qua C ABI. AUD-017 sửa key EV và kiểm tra tăng clipping cả R/G/B.",
        "- **Đường dẫn Unicode:** `resume-002` tái hiện ABI mở file tiếng Việt FAIL 4/5 checks. "
        "Sửa Windows argv trong harness và chuyển UTF-8 sang `wchar_t` tại LibRaw open_file cho cả probe/develop; "
        "`resume-004` ghi PASS 6/6 checks, gồm render file Unicode bằng pixel hash với nguồn gốc.",
        "- **Lifecycle:** harness cũ bỏ qua hash khác giữa vòng; hiện sai khác sẽ làm FAIL.",
        "- **Preview/resize:** AUD-021 cũ ghi PASS chưa so pixel. Nay export B4 được so bit-exact với pe_render_preview; "
        "test thật bắt CLI checkpoint/report bỏ qua output.longEdge (4948×3280 so preview 2474×1640). "
        "Sửa request trong prepare_and_render theo recipe; AUD-020 yêu cầu đúng factor 2, không chấp nhận no-op 1/1 là PASS.",
        "- **Runner/mutation:** sửa root, isolated source copy, control baseline, phục hồi trong finally, "
        "hash mutant/patch, bổ sung stale-result MUT-10, không tính exception/compile lỗi là kill. "
        "AUD-040 kiểm tra missing/skip/status lạ/timeout/exception và XML escaping; FAIL có ưu tiên exit 1 hơn missing report.",
        "- **Dependency metadata:** 1.100 source files LibRaw/zlib/libjpeg-turbo khớp archive; JSON header khớp manifest. "
        "Hash doctest trong manifest cũ không khớp file, nhưng header dùng build khớp byte-for-byte "
        "[upstream v2.5.3](https://raw.githubusercontent.com/doctest/doctest/v2.5.3/doctest/doctest.h). "
        "Sửa riêng manifest hash, không sửa header; hash cũ/mới và kiểm tra độc lập nằm trong `dependency-verification.json`.",
        "- **Fault hook thiếu (AUD-025/026):** lượt đầy đủ trước sửa ghi fault exit 0/published output vì hook chỉ được khai báo "
        "trong tooling mà chưa có trong core. Bổ sung injection ngay tại fwrite/fflush, giữ chung nhánh kiểm tra/cleanup production; "
        "compile guard `PHOTO_ENGINE_AUDIT_FAULTS` mặc định OFF cho build thường, ON khi audit. Sau sửa chạy lại clean build/unit/contract, "
        "JPEG, immutability, ba loại fault, no-overwrite và aggregate controls; giữ nguyên dữ liệu FAIL trước sửa.",
        "", "Patch đối chiếu snapshot: `resume-changes.patch` trong artifact. Các lượt `resume-*` là debug/subset; "
        "lượt bị ngắt không có summary hoàn chỉnh không được dùng làm bằng chứng nghiệm thu.", "",
        "## 6. Mutation sensitivity", "",
        "| Mutant | Suite status | Kết quả | Detector |", "|---|---|---|---|"]
    for row in mutants:
        report.append(f"| {row['variant']} | {row['status']} | {row.get('reason') or (row.get('metric') or {}).get('mutantStatus', 'comparator sensitivity')} | {(row.get('metric') or {}).get('detector', 'AUD-002')} |")
    report += ["", "Manifest/hash, patch và build log từng mutant nằm dưới `mutations/MUT-*` của component full-run ghi trong environment. "
               "MUT-15 chứng minh comparator thật từ chối NaN, trong khi comparator bị sửa để skip NaN nhận PASS. "
               "Source sản phẩm không bị mutation runner sửa.", "", "## 7. Giới hạn và blockers", ""]
    for c in matrix["cases"]:
        for reason in c["limitations"]:
            report.append(f"- {c['caseId']} ({c['status']}): {reason}")
    report += ["- Tập fixture chỉ gồm hai Nikon Bayer; không chứng nhận camera khác, RAF/X-Trans/ProRAW, holdout hoặc màu vật lý.",
               "- `limits` trong policy khai báo budget; chưa có kiểm chứng peak memory cưỡng chế cho mọi subprocess. "
               "Checkpoint FP32 lớn được xóa sau so sánh; descriptor/metrics/sample được giữ để trace, chạy lại để tái tạo toàn pixel.",
               "- Các biến thể đã chạy không chứng minh toàn bộ nhánh yêu cầu trong plan: chưa có LUT dimension 33/65, "
               "container DNG cặp thumbnail, raw sample trace với thumbnail bị vô hiệu hóa, hoặc cancel barrier stage xác định. "
               "Kết luận theo các variant thực tế, không suy rộng thành chứng nhận toàn engine.",
               "", "## 8. Tái lập", "", "Từ root `photo_engine` trong PowerShell:", "", "```powershell",
               '$env:PATH = "$PWD/tools/toolchain/mingw64/mingw64/bin;$env:PATH"',
               'python tools/run_engine_audit.py --artifact-dir artifacts/engine-audit/new-run-id --full-required --with-mutations',
               'python tools/finalize_engine_audit.py --run artifacts/engine-audit/new-run-id', "```", "",
               "Dùng thư mục mới, giữ fixtures/dependencies theo manifest. Exit 0 chỉ khi tất cả required PASS; "
               "1 khi có FAIL; 2 khi không FAIL nhưng required BLOCKED/NOT_RUN hoặc thiếu report.", "",
               "## 9. Đề xuất review", "",
               "Ưu tiên cung cấp RAW có orientation khác 0 và môi trường sanitizer, bổ sung phép đo ICC float XYZ rồi chạy lại required set. "
               "Tech Lead + Imaging cần review policy/conventions trước nghiệm thu. Báo cáo này không duyệt G1, G2, G3 hay ADR.", ""]
    report_text = "\n".join(report)
    qa = ROOT / "docs/qa/G1_INDEPENDENT_AUDIT_REPORT.md"
    qa.parent.mkdir(parents=True, exist_ok=True)
    qa.write_text(report_text, encoding="utf-8")
    (run / "G1_INDEPENDENT_AUDIT_REPORT.md").write_text(report_text, encoding="utf-8")
    (run / "handoff-verification.json").write_text(json.dumps({
        "aggregateMatchesSummary": True, "junitParses": True,
        "allRequiredReportsPresent": True, "matrixGroups": len(matrix["cases"]),
        "testedSourceHashesVerified": checked_sources, "binaryHashesVerified": True,
        "generatorSha256": digest(Path(__file__)), "reportSha256": digest(qa),
        "policyStillProposed": policy["approvalStatus"] == "PROPOSED"
    }, indent=2), encoding="utf-8")
    (run / "manifest.sha256").write_text("\n".join(
        f"{digest(p)}  {p.relative_to(run).as_posix()}" for p in sorted(run.rglob("*"))
        if p.is_file() and p.name != "manifest.sha256") + "\n", encoding="utf-8")
    print(json.dumps({"report": str(qa), "caseCounts": dict(all_counts),
                      "requiredCounts": dict(required_counts)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
