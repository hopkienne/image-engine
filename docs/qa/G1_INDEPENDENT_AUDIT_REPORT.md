# G1 Independent Audit Report

**Kết luận: INCOMPLETE (required evidence remains BLOCKED/NOT_RUN). G1 chưa được nghiệm thu.**

Bộ bằng chứng `handoff-20260930`, snapshot build cuối `2026-09-30T11:03:21Z`, kết quả cuối `2026-09-30T11:07:51Z` (UTC). Policy `G1-INDEPENDENT-AUDIT-v1` vẫn **PROPOSED**; không thay required IDs hoặc tolerance để làm xanh kết quả.

## 1. Build và phạm vi

Windows / MinGW-w64 GCC 16.2.0, Release C++17, static linkage, core `-ffp-contract=off`. AUD-001 build source hiện tại vào thư mục mới và chạy lại unit/contract suite trên binary đó. Workspace không có `.git`; dùng snapshot trước sửa, source hash và patch thay cho commit/diff Git.

Artifact root: `G:\zalo_mini_app\app\photo_engine\artifacts\engine-audit\handoff-20260930`. Các hash policy/oracle/dependency/source/binary nằm trong `environment.json`; recipe/asset/command/checkpoint descriptor được giữ trong artifact và manifest. Snapshot trước tiếp tục: `artifacts/engine-audit/resume-snapshot-20260930/source-before.zip`.

Mutation runner được hoàn thiện phạm vi probe trước khi module AUD-039 được import; hash ban đầu và hash module thực thi được ghi riêng trong `executionSourceUpdates` ở environment component đầy đủ. Code production và ngưỡng không thay đổi trong lượt đầy đủ. LUT mutants dùng một frame phân biệt đầy đủ pixel, với đúng variant đã PASS ở baseline.

Nếu `componentRuns` có trong environment/summary, đây là aggregate của lượt đầy đủ trước sửa hook và lượt hồi quy sau sửa; mỗi variant có `evidenceRun` để xác định binary/source đã chạy. Không gọi các kết quả trên hai build là một lượt thực thi duy nhất. Output JPEG identity không fault được so byte-for-byte trong `normal-output-comparison.json`.

Policy SHA-256: `554f60ba3035a8f3723c546200973bcf1f9fa4d8cfb4b1252fa58945191997ac`. Oracle SHA-256: `f53491b34dca8b5e061c7d4ff85ea1130f2e79a84e561de2cff628f291862440`.

Fixtures: `d7000-compressed-12bit`, `d3200-lossless-12bit-stored`; bytes/hash đã đối chiếu manifest. Nguồn và khai báo license CC0 được lưu trong `tests/acceptance/fixture_manifest.json`; lượt tiếp tục không tải hay upload ảnh. LUT dimension 17: identity, permutation, constant, affine, multiaffine, square-grid.

## 2. Kết luận riêng từng lớp

| Lớp | Trạng thái suite | Case | Giới hạn |
|---|---|---|---|
| LUT/domain/recipe | PASS | AUD-004, AUD-005, AUD-006, AUD-007, AUD-008, AUD-009, AUD-010 | Oracle công thức đóng; kiểm tra toàn pixel B1→B2, B3/B4 composition. |
| RAW adapter/baseline | PASS | AUD-011, AUD-013, AUD-014, AUD-015, AUD-016 | Hai Nikon Bayer; reference adapter vẫn dùng chung LibRaw, không chứng minh màu vật lý. |
| Orientation/geometry/export/ICC | BLOCKED | AUD-018, AUD-019, AUD-020, AUD-021, AUD-023, AUD-024 | Thiếu RAW orientation khác 0 và phép đo ICC float XYZ theo policy. |
| Integrity/fault/cancel/lifecycle | PASS | AUD-022, AUD-025, AUD-026, AUD-027, AUD-029, AUD-030, AUD-031, AUD-032 | Cancel giữa render dùng delay 300 ms; chưa có barrier stage xác định. |
| Memory safety/fuzz | BLOCKED | AUD-033, AUD-034 | Thiếu runtime ASan/UBSan và campaign libFuzzer. |
| Tái lập host | PASS | AUD-035 | Ba process cùng toolchain/host; chưa chứng minh cross-build/cross-platform. |
| Mutation sensitivity | PASS | AUD-039 | Compile error, timeout và detector exception không được tính là semantic kill. |
| Chất lượng ảnh G2 | NOT_RUN | AUD-036 | Chưa có holdout/chart/reference developer khác. |
| Mobile/performance G3 | NOT_RUN | AUD-037/038 | Chưa chạy iOS/Android hoặc budget thiết bị. |

## 3. Claim và bằng chứng

Non-identity LUT được chạy qua loader và production CLI trên RAW thật, so toàn pixel với oracle Python ngoài tiến trình. Checkpoint B1 là đầu vào kiểm tra look; reference adapter conformance vẫn chia sẻ LibRaw. Preview/export hiện được đối chiếu bằng pixel C ABI thật, gồm alpha và stride native. ICC 8-bit bridge có kết quả riêng; nó không thay phép đo float XYZ còn BLOCKED.

## 4. Kết quả đầy đủ

33 effective-required groups: `{'PASS': 30, 'NOT_RUN': 1, 'BLOCKED': 2}`. Toàn bộ 40 groups: `{'PASS': 31, 'NOT_APPLICABLE': 2, 'NOT_RUN': 5, 'BLOCKED': 2}`. Runner exit code `2`; missing required reports `[]`. Không tính tỷ lệ PASS trên riêng các test đã chạy.

Chi tiết variant/metric/reason: [test_matrix.json](../../tests/acceptance/test_matrix.json). Kết quả máy đọc được: [summary.json](../../artifacts/engine-audit/handoff-20260930/summary.json), [results.json](../../artifacts/engine-audit/handoff-20260930/results.json), [junit.xml](../../artifacts/engine-audit/handoff-20260930/junit.xml).

| Case | Level | Required | Trạng thái | Variants |
|---|---|---|---|---|
| AUD-001 | CORE | yes | PASS | 3 |
| AUD-002 | CORE | yes | PASS | 9 |
| AUD-003 | CORE | yes | PASS | 2 |
| AUD-004 | CORE | yes | PASS | 10 |
| AUD-005 | CORE | yes | PASS | 10 |
| AUD-006 | CORE | yes | PASS | 12 |
| AUD-007 | CORE | yes | PASS | 6 |
| AUD-008 | CORE | yes | PASS | 6 |
| AUD-009 | CORE | yes | PASS | 6 |
| AUD-010 | CORE | yes | PASS | 4 |
| AUD-011 | CORE | yes | PASS | 3 |
| AUD-012 | CONDITIONAL | no | NOT_APPLICABLE | 1 |
| AUD-013 | CORE | yes | PASS | 2 |
| AUD-014 | CORE | yes | PASS | 1 |
| AUD-015 | CORE | yes | PASS | 5 |
| AUD-016 | CORE | yes | PASS | 1 |
| AUD-017 | DIAGNOSTIC | no | PASS | 1 |
| AUD-018 | CORE | yes | NOT_RUN | 2 |
| AUD-019 | CONDITIONAL | yes | PASS | 1 |
| AUD-020 | CONDITIONAL | yes | PASS | 1 |
| AUD-021 | CONDITIONAL | yes | PASS | 1 |
| AUD-022 | CORE | yes | PASS | 2 |
| AUD-023 | CORE | yes | PASS | 4 |
| AUD-024 | CORE | yes | BLOCKED | 4 |
| AUD-025 | CORE | yes | PASS | 2 |
| AUD-026 | CORE | yes | PASS | 3 |
| AUD-027 | CORE | yes | PASS | 1 |
| AUD-028 | CONDITIONAL | no | NOT_APPLICABLE | 1 |
| AUD-029 | CORE | yes | PASS | 1 |
| AUD-030 | CORE | yes | PASS | 3 |
| AUD-031 | CONDITIONAL | yes | PASS | 1 |
| AUD-032 | CORE | yes | PASS | 1 |
| AUD-033 | CORE | yes | BLOCKED | 3 |
| AUD-034 | CONDITIONAL | no | NOT_RUN | 1 |
| AUD-035 | CORE | yes | PASS | 1 |
| AUD-036 | DIAGNOSTIC | no | NOT_RUN | 1 |
| AUD-037 | DIAGNOSTIC | no | NOT_RUN | 1 |
| AUD-038 | DIAGNOSTIC | no | NOT_RUN | 1 |
| AUD-039 | CORE | yes | PASS | 16 |
| AUD-040 | CORE | yes | PASS | 11 |

## 5. Bug và sửa chữa

- **ICC TRC (sửa ở lượt trước):** dữ liệu trước sửa trong `bugfixes/AUD-024-trc/results_before_fix.json` ghi sai khác tối đa 135 mức 8-bit qua trusted lcms. Lượt đầy đủ hiện tại chạy lại AUD-024; float XYZ vẫn BLOCKED.
- **Harness escape JSON:** snapshot có cú pháp C++ sai khi escape backslash. Sửa literal và escape quote; AUD-022/029/031/032 chạy lại qua C ABI. AUD-017 sửa key EV và kiểm tra tăng clipping cả R/G/B.
- **Đường dẫn Unicode:** `resume-002` tái hiện ABI mở file tiếng Việt FAIL 4/5 checks. Sửa Windows argv trong harness và chuyển UTF-8 sang `wchar_t` tại LibRaw open_file cho cả probe/develop; `resume-004` ghi PASS 6/6 checks, gồm render file Unicode bằng pixel hash với nguồn gốc.
- **Lifecycle:** harness cũ bỏ qua hash khác giữa vòng; hiện sai khác sẽ làm FAIL.
- **Preview/resize:** AUD-021 cũ ghi PASS chưa so pixel. Nay export B4 được so bit-exact với pe_render_preview; test thật bắt CLI checkpoint/report bỏ qua output.longEdge (4948×3280 so preview 2474×1640). Sửa request trong prepare_and_render theo recipe; AUD-020 yêu cầu đúng factor 2, không chấp nhận no-op 1/1 là PASS.
- **Runner/mutation:** sửa root, isolated source copy, control baseline, phục hồi trong finally, hash mutant/patch, bổ sung stale-result MUT-10, không tính exception/compile lỗi là kill. AUD-040 kiểm tra missing/skip/status lạ/timeout/exception và XML escaping; FAIL có ưu tiên exit 1 hơn missing report.
- **Dependency metadata:** 1.100 source files LibRaw/zlib/libjpeg-turbo khớp archive; JSON header khớp manifest. Hash doctest trong manifest cũ không khớp file, nhưng header dùng build khớp byte-for-byte [upstream v2.5.3](https://raw.githubusercontent.com/doctest/doctest/v2.5.3/doctest/doctest.h). Sửa riêng manifest hash, không sửa header; hash cũ/mới và kiểm tra độc lập nằm trong `dependency-verification.json`.
- **Fault hook thiếu (AUD-025/026):** lượt đầy đủ trước sửa ghi fault exit 0/published output vì hook chỉ được khai báo trong tooling mà chưa có trong core. Bổ sung injection ngay tại fwrite/fflush, giữ chung nhánh kiểm tra/cleanup production; compile guard `PHOTO_ENGINE_AUDIT_FAULTS` mặc định OFF cho build thường, ON khi audit. Sau sửa chạy lại clean build/unit/contract, JPEG, immutability, ba loại fault, no-overwrite và aggregate controls; giữ nguyên dữ liệu FAIL trước sửa.

Patch đối chiếu snapshot: `resume-changes.patch` trong artifact. Các lượt `resume-*` là debug/subset; lượt bị ngắt không có summary hoàn chỉnh không được dùng làm bằng chứng nghiệm thu.

## 6. Mutation sensitivity

| Mutant | Suite status | Kết quả | Detector |
|---|---|---|---|
| MUT-01/KILLED | PASS | KILLED | AUD-005 |
| MUT-02/KILLED | PASS | KILLED | AUD-006 |
| MUT-03/KILLED | PASS | KILLED | AUD-008 |
| MUT-04/KILLED | PASS | KILLED | AUD-007 |
| MUT-05/KILLED | PASS | KILLED | AUD-006 |
| MUT-06/KILLED | PASS | KILLED | AUD-009 |
| MUT-07/KILLED | PASS | KILLED | AUD-009 |
| MUT-08/KILLED | PASS | KILLED | AUD-015 |
| MUT-09/KILLED | PASS | KILLED | AUD-013 |
| MUT-10/KILLED | PASS | KILLED | AUD-022 |
| MUT-11/KILLED | PASS | KILLED | AUD-023 |
| MUT-12/KILLED | PASS | KILLED | AUD-027 |
| MUT-13/KILLED | PASS | KILLED | AUD-019 |
| MUT-14/KILLED | PASS | KILLED | AUD-031 |
| MUT-15/comparator-nan-skip | PASS | comparator sensitivity | AUD-002 |

Manifest/hash, patch và build log từng mutant nằm dưới `mutations/MUT-*` của component full-run ghi trong environment. MUT-15 chứng minh comparator thật từ chối NaN, trong khi comparator bị sửa để skip NaN nhận PASS. Source sản phẩm không bị mutation runner sửa.

## 7. Giới hạn và blockers

- AUD-012 (NOT_APPLICABLE): No valid synthetic DNG pair is in scope and the engine does not claim DNG-thumbnail-capability testing; real-camera fixtures are used instead (AUD-011/016). Capability remains unclaimed.
- AUD-018 (NOT_RUN): no fixture with decoderFlip != 0 available (flips={'d7000-compressed-12bit': 0, 'd3200-lossless-12bit-stored': 0}); download/fixture acquisition is a next step
- AUD-024 (BLOCKED): Pillow binding exposes only the 8-bit RGB bridge used below; float XYZ policy precision has not been measured. The bridge does not replace this requirement.
- AUD-028 (NOT_APPLICABLE): Engine writes no camera EXIF at all (only JFIF+ICC+minimal EXIF with Orientation/ColorSpace/Software); there is no GPS/serial stripping feature to conformance-test. Documented limitation, not a passed check.
- AUD-033 (BLOCKED): toolchain has no -lasan runtime
- AUD-033 (BLOCKED): toolchain has no -lubsan runtime
- AUD-033 (BLOCKED): no sanitizer runtime in the pinned MinGW toolchain; requires MSVC (missing cl.exe on host) or an ASan-capable GCC; _GLIBCXX_ASSERTIONS build is recorded as a partial substitute
- AUD-034 (NOT_RUN): Coverage-guided fuzzing requires a libFuzzer-capable toolchain; current MinGW host has none. Budget also not allocated.
- AUD-036 (NOT_RUN): no implementation registered for this case ID
- AUD-037 (NOT_RUN): no implementation registered for this case ID
- AUD-038 (NOT_RUN): no implementation registered for this case ID
- Tập fixture chỉ gồm hai Nikon Bayer; không chứng nhận camera khác, RAF/X-Trans/ProRAW, holdout hoặc màu vật lý.
- `limits` trong policy khai báo budget; chưa có kiểm chứng peak memory cưỡng chế cho mọi subprocess. Checkpoint FP32 lớn được xóa sau so sánh; descriptor/metrics/sample được giữ để trace, chạy lại để tái tạo toàn pixel.
- Các biến thể đã chạy không chứng minh toàn bộ nhánh yêu cầu trong plan: chưa có LUT dimension 33/65, container DNG cặp thumbnail, raw sample trace với thumbnail bị vô hiệu hóa, hoặc cancel barrier stage xác định. Kết luận theo các variant thực tế, không suy rộng thành chứng nhận toàn engine.

## 8. Tái lập

Từ root `photo_engine` trong PowerShell:

```powershell
$env:PATH = "$PWD/tools/toolchain/mingw64/mingw64/bin;$env:PATH"
python tools/run_engine_audit.py --artifact-dir artifacts/engine-audit/new-run-id --full-required --with-mutations
python tools/finalize_engine_audit.py --run artifacts/engine-audit/new-run-id
```

Dùng thư mục mới, giữ fixtures/dependencies theo manifest. Exit 0 chỉ khi tất cả required PASS; 1 khi có FAIL; 2 khi không FAIL nhưng required BLOCKED/NOT_RUN hoặc thiếu report.

## 9. Đề xuất review

Ưu tiên cung cấp RAW có orientation khác 0 và môi trường sanitizer, bổ sung phép đo ICC float XYZ rồi chạy lại required set. Tech Lead + Imaging cần review policy/conventions trước nghiệm thu. Báo cáo này không duyệt G1, G2, G3 hay ADR.
