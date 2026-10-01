# RAW multi-engine benchmark — bàn giao 01/10/2026

Run: `20261001/run-v1` · Runner: **PARTIAL** · Scope: **Proposed**.
Policy SHA-256: `c8dbfefe00e6b81f388055aeedfddec1eb9c7b9c839edf828b60f01057034f44`.

Đã tải/xác minh **40/40 RAW** và thực hiện ma trận xử lý với ours,
darktable 5.6.1 và RawTherapee 5.13. Có **118 export BASE_CONTROLLED
full resolution thành công**. Execution counts: `{"SUCCESS": 118, "FAILED": 1, "BLOCKED": 1}` trên
denominator **120 jobs**. Pairwise: `{"COMPARABLE": 113, "NOT_COMPARABLE": 4, "PARTIAL_REFERENCE": 3}`. Có 24 nhóm
camera/session thận trọng; **không** gọi đó là 24 scene độc lập đã xác minh.
Split cố định 28 development / 12 holdout, pilot 12 development trước holdout.

**Chưa nghiệm thu G2.** Human review: NOT_REVIEWED. Hai converter không phải ground truth;
LibRaw có thể là dependency chung. Chưa có chart/reference/lighting hợp lệ để kết luận
độ chính xác màu, dynamic range hay màu đúng của cảnh. Thiếu scope portrait/low-light
được ghi BLOCKED trong issues.json, không gán nhãn từ tên file. X-Trans là exploratory.

## Bằng chứng đã xác minh

- Snapshot source + binary baseline được lưu trước render: baseline.json,
  baseline-source.zip, baseline-photo-cli.exe và smoke/. **Không sửa thuật toán core**;
  hashes source vẫn khớp. Các lỗi thử setup/XMP/path được giữ nguyên ở attempts/logs.
- Từng RAW có evidence CC0 publisher row + URL + hash/byte thật. Original không đổi,
  mỗi job dùng copy độc lập. FiveK: PENDING_LICENSE_REVIEW, không tải.
- Ours đo FP32 production trước JPEG, RT/darktable TIFF RGB 16-bit thật. Native và
  normalized FP32 lossless được giữ; JPEG chỉ cung cấp ICC metadata cho ours.
- LCMS float transform thực, ICC pin bằng hash; H01–H14: PASS.
  Test nonidentity gamma độc lập: color-transform-tests.json. Config-effect cả ba:
  PASS; repeatability: PASS.
- Geometry chỉ orientation/integer translation/crop có evidence. Không resize/warp
  để tạo metric. Thiếu mapping → NOT_COMPARABLE; không fill missing reference bằng 0.
  Endpoint domain encoded sRGB, Y quantiles linear sRGB; ngưỡng chỉ tạo review.
- Ma trận BMQ01–26, metrics JSON/CSV, đầy đủ planned rows và log/exact argv trong artifact.
  Cache kiểm actual binary/dependency + config/source/profile/normalizer/metric hashes.

## Cần xem / chưa chạy được

Flagged bởi rule thăm dò: `['R007', 'R020']`. Sample nonflagged để kiểm false negative:
`['R014', 'R011', 'R018', 'R009', 'R037', 'R005', 'R036', 'R004']`. Trường hợp mapping bị chặn và toàn bộ issue,
owner/repro/next-step: **issues.json**. Report từng ảnh giữ lỗi và nguyên nhân.
Nhánh không xuất được: `['R011/ours: recipe init failed; see init logs', 'R011/darktable: BASE_BLOCKED: headless default history generation failed']`. R011/ours: as-shot cam_mul không hợp lệ;
R011/darktable: default init đã thử nhưng decoder không đọc được, BASE bị BLOCKED.
Absolute chart accuracy: **NOT_RUN — NO_VALID_COLOR_REFERENCE (BLOCKED input)**.
Human feedback: **NOT_REVIEWED (BLOCKED reviewer)**. Scope scene/lighting: **UNKNOWN**.
AI đã xem overview R001 và R007, nhãn AI_SUGGESTION, không thay phiếu người dùng.
ASan/UBSan, fuzz và mobile của audit trước được hoãn theo yêu cầu người dùng.
Decoder dependency evidence: decoder-dependencies.json (ours và RT release source
đều LibRaw 0.22.2; RT EnableLibRaw=true; backend fallback theo file chưa instrument).

## Hiệu năng quan sát, n=3

| RAW | Engine | n | Median s | Range s | Peak sampled MiB (max of 3) | Native pixels identical |
|---|---|---:|---:|---|---:|---|
| R001 | ours | 3 | 6.459 | 6.437–6.535 | 360.5 | True |
| R001 | darktable | 3 | 5.998 | 5.949–7.287 | 884.3 | True |
| R001 | rawtherapee | 3 | 7.996 | 7.993–9.008 | 749.9 | True |
| R006 | ours | 3 | 2.741 | 2.739–2.754 | 164.9 | True |
| R006 | darktable | 3 | 3.821 | 3.745–3.879 | 383.9 | True |
| R006 | rawtherapee | 3 | 2.977 | 2.931–3.154 | 318.4 | True |
| R008 | ours | 3 | 2.685 | 2.668–2.784 | 116.4 | True |
| R008 | darktable | 3 | 4.121 | 3.691–4.402 | 387.0 | True |
| R008 | rawtherapee | 3 | 2.765 | 2.762–2.841 | 335.8 | True |

Process mới ≠ OS/disk cache lạnh. Peak là working set process-tree lấy mẫu ~50ms,
không phải peak tuyệt đối và không phải memory runner Python. Thời gian export mỗi
converter không gồm normalize và lượt darktable sinh history riêng. Pipeline làm
khác lượng công việc, **không dùng bảng này để xếp hạng tối ưu engine**. Không có p95
hay suy luận mobile. Host: i3-10105F, 16 GiB RAM, Windows 10; ứng dụng khác vẫn mở.
Wall time ours bao gồm JPEG + ghi/hash dump FP32 diagnostic, không phải latency
production JPEG-only. Stage timers n=3 của ours: performance-breakdown.json,
trích trực tiếp từ engine-report.json; không trộn vào wall time của converter khác.

## Chạy lại / mở kết quả

HTML offline: **index.html**, gallery: scenes/, blind A/B/C: blind/index.html;
mapping riêng blind-mapping.json, feedback JSON tải tại trang blind. Không CDN.
README.md chứa lệnh chính xác, package/dependency/install evidence và hạn chế.

```powershell
Set-Location -LiteralPath G:\zalo_mini_app\app\photo_engine
python -m raw_benchmark doctor --policy benchmark/benchmark.policy.json
python -m benchmark.check_color_transform
python -m raw_benchmark run --policy benchmark/benchmark.policy.json --stage pilot --resume
python -m raw_benchmark run --policy benchmark/benchmark.policy.json --stage standard --resume
python -m benchmark.verify_evidence
```

Holdout freeze: holdout.freeze.json; actual source/engine/ICC/metric settings được khóa
trước holdout. Artifact integrity/link/count verification: artifact-verification.json.
Storage compaction, nếu có: storage-deduplication.json, chỉ hardlink derivative đã
xác minh byte-identical; không hardlink RAW, không recompress mất dữ liệu.
historical-storage.json ghi native container cũ được lưu bằng metadata nguyên gốc
+ payload nén byte-identical từ export giữ lại. Manifest *.history.json và README.md
có lệnh khôi phục từng byte; artifact-verification.json kiểm lại SHA toàn container.
Native latest và normalized measurement vẫn là file TIFF/ZIP thông thường.

**Việc kế tiếp quan trọng nhất:** project owner/imaging reviewer xem các case trong
issues.json cùng sample nonflagged và export feedback trước quyết định sửa thuật toán.
