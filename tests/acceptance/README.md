# G1 Independent Audit (AUD-001..040)

Bộ kiểm chứng độc lập cho `RAW_Engine_Independent_Audit_v1/TEST_PLAN_G1_INDEPENDENT_AUDIT.md`.
Policy/tolerance vẫn **PROPOSED**; việc chạy test không nghiệm thu G1.

## Chạy lại trên Windows

Từ root `photo_engine`, trong PowerShell, với Python có numpy, Pillow và jsonschema:

```powershell
$env:PATH = "$PWD/tools/toolchain/mingw64/mingw64/bin;$env:PATH"
# Bootstrap binary cho snapshot môi trường ban đầu; AUD-001 sẽ build lại
# vào thư mục mới và dùng chính binary clean-build cho lượt audit.
cmake -G Ninja -B build-audit-base -S . -DCMAKE_BUILD_TYPE=Release -DPHOTO_ENGINE_AUDIT_FAULTS=ON
cmake --build build-audit-base --parallel 4
python tools/run_engine_audit.py --artifact-dir artifacts/engine-audit/new-run-id --full-required --with-mutations
python tools/finalize_engine_audit.py --run artifacts/engine-audit/new-run-id
```

Subset dùng thư mục mới:

```powershell
python tools/run_engine_audit.py --artifact-dir artifacts/engine-audit/subset-new-id --cases AUD-017,AUD-022,AUD-029,AUD-031,AUD-032
```

Không dùng lại artifact directory. `--cases` và `--full-required` không đi cùng nhau.
`--full-required` thêm các diagnostic/out-of-scope groups để ma trận có đủ 40 IDs.
AUD-039 yêu cầu `--with-mutations`; thiếu flag được ghi NOT_RUN, không skip thành PASS.

Exit code: **0** khi mọi effective-required PASS; **1** khi có FAIL (kể cả còn thiếu report);
**2** khi không FAIL nhưng required còn BLOCKED/NOT_RUN/NOT_APPLICABLE hoặc thiếu report.
Subset có thể PASS mọi variant được chọn nhưng exit 2 vì còn required IDs chưa chạy.

## Bàn giao

- [Báo cáo QA](../../docs/qa/G1_INDEPENDENT_AUDIT_REPORT.md)
- [Ma trận đầy đủ](test_matrix.json)
- Lượt kết quả được chỉ rõ trong hai file trên; các thư mục debug/subset không thay kết luận đầy đủ.

Mỗi run có `policy.json`, `environment.json`, `summary.json`, `results.json`, `junit.xml`,
command logs, checkpoint descriptors, oracle samples/metrics và `manifest.sha256`.
Manifest là danh sách SHA-256 từng file theo đường dẫn tương đối.
`finalize_engine_audit.py` kiểm tra summary/aggregate nhất quán, XML hợp lệ, không thiếu required reports,
rồi sinh matrix/report/patch so snapshot và cập nhật manifest.

## Oracle và instrumentation

Oracle gốc `RAW_Engine_Independent_Audit_v1/reference/oracle.py` được hash-pin và đối chiếu
với bản copy; không import production để tính expected. Accelerator numpy FP64 được
cross-check với oracle tham chiếu trên mẫu >=200.000 pixel; comparator quét toàn pixel.
B1→B2 kiểm tra look stage, không tự chứng minh RAW development đúng về màu vật lý.
Standalone reference adapter dùng chung LibRaw 0.22.2; chỉ chứng minh adapter conformance.

Test hooks: `--audit-checkpoints` xuất B0..B4; `PE_AUDIT_FAULT` mô phỏng write/flush lỗi khi build với `PHOTO_ENGINE_AUDIT_FAULTS=ON`; option mặc định OFF ở build thường.
Harness gọi C ABI thật cho sequence, cancel, ABI, lifecycle và preview-vs-export; chuyển
RGBA native sang packed RGB chỉ để serialize, kiểm tra alpha/stride, không thay màu.

Mutation runner copy source vào artifact riêng, áp từng patch, build rồi chạy detector.
Control trên baseline phải PASS. Compile lỗi, timeout, process crash hay detector exception
được ghi NOT_RUN, không tính là semantic kill. MUT-01..14 là engine/CLI; MUT-15 là comparator.
Sau mỗi mutant, source copy được phục hồi byte-for-byte trong `finally`; source sản phẩm không bị sửa.

## Giới hạn cần đọc cùng kết quả

- AUD-018 bổ sung Olympus XZ-10 CC0 có orientation khác 0, chỉ dùng cho conformance xoay ảnh; so toàn pixel với adapter trước orientation qua mapping độc lập.
- AUD-024 chạy XYZ double qua Little CMS khi có `PE_AUDIT_LCMS_DLL`; thiếu thư viện vẫn BLOCKED. Ngưỡng giữ nguyên `2e-4`; 8-bit bridge là kết quả bổ sung.
- AUD-033: canary cho thấy toolchain pin không có runtime ASan/UBSan; không thay bằng tuyên bố memory-safe.
- AUD-034 chưa có campaign libFuzzer; AUD-036/038 chưa có quality holdout/mobile harness. AUD-037 đo wall/CPU và OS peak memory trên Windows; không chứng nhận mobile.
- Cancel gồm test async delay 300 ms và observer nội bộ hủy tại stage/chunk xác định; observer không nằm trong C ABI sản phẩm.
- Checkpoint FP32 lớn được xóa sau so; descriptor, metric và sample giữ lại để trace. Chạy lại để tái tạo toàn buffer.
- Hai Nikon Bayer và LUT dimension 17 không chứng nhận camera khác, màu vật lý hoặc iOS/Android.

Lượt 30/09 là lịch sử aggregate trước/sau sửa, từng variant ghi evidenceRun.
Lượt cải tiến 01/10 và benchmark nằm trong [báo cáo mới](../../docs/qa/ENGINE_IMPROVEMENTS_20261001.md).
Để tái lập toàn bộ trên source hiện tại, chạy lệnh full-required ở trên và đặt `PE_AUDIT_LCMS_DLL` khi có reference đã xác minh.
