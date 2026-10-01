# G0 Scope Draft — vòng G1 (baseline end-to-end, CPU reference, desktop CLI)

Ngày: 2026-09-30. Trạng thái: **Proposed — chưa có Product Owner/Tech Lead duyệt**. Toàn bộ
giả định dưới đây do vòng triển khai kỹ thuật đề xuất để có thể tiếp tục công việc độc lập;
không mục nào được coi là đã chốt.

Tài liệu tham chiếu: bộ `raw_photo_app_rnd_v0.1` (Proposed v0.1), đặc biệt
docs/01, 02, 03, 04, 06, 07, 08, 09; contracts/*.schema.json; include/photo_engine.h;
examples/recipe.synthetic.json; examples/identity-look.

## 1. Phạm vi đang thực hiện trong vòng này

- Luồng dọc nhỏ chạy được trên desktop Windows host:
  **RAW thật → phát triển ảnh nền (P0/LibRaw) → identity look → xuất JPEG sRGB → chạy lại bằng recipe đã lưu cho cùng pixel**.
- Core C++17, C ABI theo `include/photo_engine.h` (có 2 điểm lệch contract có ghi chú, xem §5).
- CLI `photo-cli` với `probe`, `init-recipe`, `render`.
- Dependency pin (LibRaw, zlib, libjpeg-turbo, nlohmann/json, doctest) với hash, license note.
- Unit tests (màu, LUT, recipe, JSON, SHA-256, C ABI) + RAW integration test trên fixture thật.
- Diagnostic pixel dump (FP32 pre-quantize, kèm descriptor JSON) + report theo lần chạy.

## 2. Phần trì hoãn (không làm trong vòng này)

- Mobile harness (iOS/Android), JNI/Swift binding, XCFramework — chỉ giữ ranh giới tích hợp
  (C ABI hẹp, không UI dependency, blocking API cho adapter worker).
- GPU, preview scheduler, cacheinvalidate/preview generation, Look Lab batch UI.
- JPEG/HEIC input branch (`sourceKind=renderedImage` → engine trả `PE_UNSUPPORTED_SOURCE`).
- ProRAW/linearDng/sRAW/X-Trans/monochrome — probe nhận diện nhưng engine G1 chỉ thực thi
  `cameraRaw` mosaic đã kiểm thử trên fixture; phần còn lại bị chặn có giải thích.
- Grain, sharpening, crop-resample nâng cao (chỉ crop/rotate 90°/downscale box).
- Chất lượng thẩm mỹ, golden gallery, holdout review, certification camera.

## 3. Camera/variant, fixture và môi trường thực tế

| Hạng mục | Giá trị | Trạng thái |
|---|---|---|
| Camera/variant ưu tiên | **TBD — chưa có quyết định PO/TL**. Vòng này dùng fixture Bayer RGB mosaic bất kỳ có license rõ để kiểm chứng kỹ thuật | Proposed |
| RAW fixture | Tải công khai, license ghi trong `fixtures/fixtures_manifest.json` (kèm URL, hash, license). Không dùng ảnh cá nhân | Xem manifest |
| Host | Windows 10 x64, MinGW-w64 GCC (WinLibs portable), CMake 4.4.3 + Ninja 1.13.2 (pip) | Đã xác nhận |
| Mạng | Có (GitHub, color.org) | Đã xác nhận |
| Compiler MSVC trên máy | VS 2022 Community / VS 2019 Build Tools tồn tại nhưng **không có** `cl.exe`/Windows SDK usable → không dùng được | Đã kiểm tra |

Kết quả với một mẫu máy không tạo ra chứng nhận hỗ trợ camera đó (docs/07 §7.5);
ma trận camera support trong repo vẫn chỉ là template rỗng cho tới khi có corpus thật.

## 4. Cần Product Owner / Tech Lead duyệt (TBD / Proposed)

1. Camera/variant ưu tiên và corpus 60 ảnh (B-01/B-02) — **TBD**.
2. Người duyệt từng vai trò (PO, TL, Imaging, QA…) — **TBD, không tự gán**.
3. ADR-0001..0006 — giữ **Proposed**; vòng này chỉ nộp bằng chứng, không tự chuyển Accepted.
4. Giấy phép phân phối sản phẩm (LGPL/CDDL link model, App Store/Play) — chỉ ghi nhận nguồn,
   **không kết luận pháp lý** (docs/09 §9.4).
5. Domain P1 (scene-linear Rec.2020) — ngoài vòng này; P0 giữ `baseline-linear-bounded-v0`.

## 5. Giả định tạm thời, rủi ro, lệch contract đề xuất

Giả định (Proposed, có ghi trong report):
- P0 dùng postprocess LibRaw cấu hình cố định (sRGB output, gamma tuyến tính, no auto-bright,
  no auto-max, user_flip=0, AHD demosaic, highlight=0 clip). Dữ liệu integer 16-bit bị clip
  tại white level ⇒ domain `baseline-linear-bounded-v0`, **không** tuyên bố scene-linear
  unbounded hay highlight recovery (docs/03 §3.1).
- WB asShot được resolve từ `color.cam_mul` của LibRaw tại init-recipe và lưu vào recipe;
  render luôn dùng multipliers đã lưu (không tự tính lại).
- Camera profile: `null` trong G1 (P0 dùng ma trận màu của decoder); recipe có cameraProfile
  khác null bị từ chối `PE_PIPELINE_UNAVAILABLE`.
- ICC sRGB nhúng vào JPEG là profile **tự sinh deterministically** trong engine (matrix/TRC
  v2, chuẩn sRGB primaries D50-adapted + sRGB TRC), không dùng profile bên thứ ba — tránh
  câu hỏi license; hash ghi trong report.
- metadataPolicy `strip_location` và `minimal` cho ra metadata giống nhau ở G1 (engine không
  re-embed EXIF máy ảnh/GPS; chỉ JFIF + ICC + EXIF tối thiểu ColorSpace/Orientation) — ghi rõ
  là giới hạn, không phải policy cuối.

Lệch contract đề xuất (chờ review, chưa Accepted):
1. `pe_image_info.color_contract` bản draft chỉ định nghĩa `1 = linear SDR sRGB`. Kết quả
   render cuối của engine là dữ liệu **encoded** sRGB (srgb-display-v1) để UI/preview dùng
   trực tiếp; đề xuất thêm `2 = sRGB-encoded SDR sRGB D65, FP32 RGBA, alpha=1` cho output
   render/export của pe_render_preview. Giữ nguyên `1` cho mục đích diagnostic nếu cần.
2. Draft `pe_render_preview` yêu cầu `long_edge_px > 0`; export theo recipe. Đề xuất thêm
   cờ `long_edge_px = 0` nghĩa là "không resize" cho đường render-check (dùng trong test
   reproducibility để so pre-JPEG ở kích thước gốc) — hoặc dùng pe_export_jpeg + pixel dump
   và không đổi struct. Hiện dùng phương án sau, struct không đổi.

Rủi ro:
- RK-01: chất lượng P0 (clip trước exposure) — đã ghi nhận giới hạn, quyết định tại G2.
- MinGW/GCC mới + LibRaw cũ: nguy cơ cảnh báo/lỗi biên dịch — xử lý bằng flag biên dịch
  riêng cho third_party nếu cần.
- Fixture tải mạng: license/phụ thuộc tải — manifest ghi URL/hash; nếu tải hỏng, RAW
  integration = NOT_RUN/BLOCKED và G1 **không** được tuyên bố xác minh đầy đủ.

## 6. Điều kiện kết thúc vòng (theo docs/06 §6.4 G1)

CLI từ RAW đến ảnh, source bất biến (re-hash), identity/recipe/export hoạt động, chạy lại
được bằng recipe đã lưu, lỗi xử lý rõ. Không tuyên bố: chất lượng Lightroom, mô phỏng
Fujifilm, tương đương iOS/Android, đã qua G0/G1 review.
