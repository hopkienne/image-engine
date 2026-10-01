# G1 Report — baseline end-to-end (CPU reference, desktop CLI)

Ngày: 2026-09-30. Trạng thái: báo cáo kỹ thuật cho review, **không tự phê duyệt G1**.
Tham chiếu: docs/rnd/G0_SCOPE_DRAFT.md, docs/rnd/G1_IMPLEMENTATION_PLAN.md,
gói tài liệu `../raw_photo_app_rnd_v0.1` (Proposed v0.1).

Kết luận ngắn: luồng dọc **RAW thật → phát triển P0 → identity look → xuất JPEG sRGB →
chạy lại bằng recipe đã lưu cho cùng pixel** đã chạy được và được kiểm chứng trên 2
fixture RAW thật (Nikon D7000, Nikon D3200) trên host Windows. Source bất biến
(re-hash trước/sau), reproducibility byte-identical trước JPEG, các đường lỗi trả mã
PE_* rõ ràng. Sanitizer bị BLOCKED do toolchain không có runtime; đã chạy thay thế
bằng build `_GLIBCXX_ASSERTIONS` + stack-protector (34/34 tests pass).

---

## 1. IMPLEMENTED (đã viết, nằm trong repository)

- **Core C++17** (`engine/`), target CMake `photoengine_core` (static, không phụ thuộc UI):
  - C ABI theo `include/photo_engine.h` (draft + 1 amendment chờ review, đánh dấu
    `[PE-G1-NOTE]`): `pe_engine_create/destroy`, `pe_source_open_local/info_json/release`,
    `pe_cancel_create/request/release`, `pe_render_preview`, `pe_image_describe/release`,
    `pe_export_jpeg`, `pe_last_error_json`, `pe_blob_*`. Không exception qua ABI; RAII toàn core.
  - `strict_json` — SAX parser: từ chối duplicate key, NaN/Infinity, vượt depth/size.
  - `schema_validate` — mini JSON-Schema (draft 2020-12) cho đúng tập keyword của 2 schema
    trong contracts/; **fail-closed** với keyword lạ (không tuyên bố hỗ trợ full 2020-12).
    Schema nhúng vào binary từ `contracts/*.schema.json` lúc build (không có bản copy thứ hai).
  - `recipe` — parse + schema + semantic validation: pipeline/engineCompatibility/developerBuild,
    cameraProfile phải null (P0), `renderedImage` bị chặn, WB mode/multipliers, crop bounds
    (schema không diễn đạt được), grain.enabled=true bị từ chối (`PE_RECIPE_INVALID`).
  - `look` — look package loader: schema manifest, domain `srgb-display-v1`, amountPolicy,
    compatiblePipelines, sourceKinds, hash manifest + hash asset, dimension 17/33/65,
    số dòng = n³, mọi giá trị finite ∈ [0,1], DOMAIN_MIN/MAX [0,1], filename an toàn
    (không `/ \ ..`). LUT .cube parser strict (báo số dòng lỗi).
    `cube3d_apply`: trilinear, red-fastest (`r + n·g + n²·b`), edge clamp, amount blend
    trong encoded look domain `y=(1-a)x+a·Look(x)`; **amount=0 bypass hoàn toàn** (bit-exact).
  - `raw_adapter` — probe (open_file, không tin đuôi file; classify Proposed:
    cameraRaw/linearDng/proRaw) + develop P0 với cấu hình pin đầy đủ
    (`use_camera_wb=0, user_mul=R,G,B,G2 từ recipe, no_auto_bright, output_bps=16,
    output_color=1 sRGB, gamm=1/1 linear, user_flip=0, use_fuji_rotate=0, user_qual=3 AHD,
    med_passes=0, highlight=0, half_size=0, four_color_rgb=0, adjust_maximum_thr=0,
    exp_correc=0`). Không dùng embedded JPEG làm dữ liệu ảnh. Config echo JSON cho report.
  - `render` — pipeline đúng graph docs/03 §3.4: develop → normalize orientation
    (dcraw flip bitmask: transpose → vertical → horizontal) → exposure (×2^EV, linear) →
    clamp [0,1] + encode sRGB → look+amount (`srgb-display-v1`) → decode sRGB →
    crop (mapping deterministic llround) → rotate 90/180/270 → flip → downscale box
    (chỉ giảm, FP64 accumulators) → clamp + encode sRGB → quantize round-half-up → JPEG.
  - `buffer` — BufferDescriptor đầy đủ: width/height/channels/channelOrder/sampleType/
    rowStride/alphaMode/primaries/whitePoint/transferFunction/rangePolicy/referenceDomain/
    orientationState. Domain: `baseline-linear-bounded-v0` (linear sRGB D65 FP32 [0,1],
    clip tại white level của decoder — **không** tuyên bố scene-linear/unbounded) và
    `srgb-display-v1`.
  - `geometry`, `color` (sRGB piecewise exact FP64 nội bộ/FP32 biên), `sha256` (FIPS 180-4,
    tự viết), `icc_srgb` (profile sRGB v2 matrix/TRC tự sinh deterministic, không dùng
    profile bên thứ ba), `jpeg_encoder` (libjpeg-turbo: JFIF APP0 + ICC APP2 đúng spec
    "ICC_PROFILE\0"+chunk + EXIF APP1 tối thiểu Orientation=1/ColorSpace=sRGB/Software;
    không GPS, không serial), `cancel_flag` (atomic one-way), `file_util` (UTF-8 paths).
  - Export staging: `pe_export_jpeg` từ chối path tồn tại, xóa output dở của chính nó khi lỗi;
    CLI render dùng `<out>.part` + rename không-replace; source không bao giờ bị ghi.
- **CLI** `photo-cli` (`cli/`): `probe`, `init-recipe`, `render` đúng cú pháp trong README;
  exit code 0/1/2; error `PE_*` + JSON diagnostics ra stderr; `--diagnostic-pixels` ghi
  `.f32` (FP32 pre-quantize) + `.json` descriptor; `--report` ghi run.json.
- **Tests** (`tests/`, doctest 2.5.3): 34 test cases / 1392 assertions — SHA-256 vectors,
  strict JSON negative, schema negative (bộ 8 case của `validate_contracts.py` + mở rộng),
  semantic recipe (grain/pipeline/cameraProfile/renderedImage/crop/WB), LUT identity/
  permuted (bắt đảo trục-kênh)/red-ramp/amount 0-0.25-1/boundary clamp + 11 negative
  package cases, geometry (flip bitmask 3/5/6/0, crop, rotate 90/270/4×90, downscale),
  sRGB encode/decode, ICC profile header + determinism, C ABI paths.
- **Build config**: root CMakeLists — target `photoengine_core`, `photo-cli`,
  `photoengine_tests`; zlib 1.3.2 + libjpeg-turbo 3.2.0 (SIMD off) + LibRaw 0.22.2 build
  từ tarball đã hash; embedded schemas; build fingerprint header (compiler/flags/deps).

## 2. VERIFIED (đã chạy, có artifact)

### 2.1. Toolchain & dependency pin

- Host Windows 10 x64; VS 2022/2019 trên máy **không có** `cl.exe`/Windows SDK usable
  → dùng MinGW-w64 GCC 16.2.0 (WinLibs portable, giải nén cục bộ, không đổi cấu hình hệ
  thống) + CMake 4.4.3 + Ninja 1.13.2 (pip). Pin + sha256 trong `third_party/manifest.json`.
- Clean build từ đầu (`rm -rf build; cmake -G Ninja; cmake --build`): thành công, exit 0.

### 2.2. Unit/contract tests

- `photoengine_tests`: **34/34 cases, 1392/1392 assertions PASS** (Release và cả biến thể
  `-D_GLIBCXX_ASSERTIONS -fstack-protector-strong`).
- `ctest`: 2/2 PASS — `unit`, `contract_python_reference` (chạy `scripts/validate_contracts.py`
  gốc của gói docs với jsonschema 4.25.1 → PASS: 2 schema, 2 fixture, hash, 4913 điểm LUT,
  8 negative).

### 2.3. RAW integration (2 fixture thật, license CC0/raw.pixls.us)

Runner: `tools/integration_test.py` — **ALL INTEGRATION CHECKS PASSED** trên cả hai fixture
(30 PASS mỗi fixture; log: `build/integration_d7000.log`, `build/integration_d3200.log`).

| | D7000 (12-bit lossy-compressed NEF) | D3200 (12-bit-stored NEF) |
|---|---|---|
| source sha256 | `986db2bf…5749486` | `91657dd8…65f57cd3` |
| dimensions | 4948×3280 | 6034×4012 |
| WB asShot đã resolve (G=1) | 1.9609, 1.0, 1.5117, 1.0 | từ cam_mul file |
| output JPEG | 2,654,352 bytes | 7,229,993 bytes |
| develop (AHD) | ~2.0 s | ~2.6 s |
| look stage | ~2.2 s | ~2.7 s |
| export tổng (encode+write) | ~7.6 s | ~11.1 s |
| source hash trước/sau | không đổi | không đổi |

Kiểm chứng trong runner (mỗi fixture):
- probe không tin đuôi file; sha256 probe == hash thực; kind=cameraRaw; white level được ghi.
- init-recipe tự kiểm lại bằng validator của chính engine (self-check) trước khi ghi file.
- render ×2: **pixel dump pre-quantize byte-identical** và **JPEG byte-identical** giữa 2 lần chạy.
- identity: amount=0 vs amount=1 → max_abs_diff = **0.0** (bit-exact trên dump FP32).
- Negative: source hash khác → `PE_ASSET_MISMATCH`; look package bị sửa 1 byte →
  `PE_ASSET_MISMATCH` (không fallback); output path tồn tại → từ chối (không ghi đè);
  crop vượt biên → `PE_RECIPE_INVALID`; grain enabled → `PE_RECIPE_INVALID` (chưa thực thi
  được thì bị từ chối rõ, không âm thầm bỏ qua).
- JPEG: JFIF APP0 + ICC APP2 đúng spec; ICC trích ra **parse được bằng Pillow ImageCms**;
  kích thước khớp report; xem trực quan 2 ảnh xuất (cột + hàng rào; ghế đá công viên) —
  màu tự nhiên, đúng hướng, không false color nghiêm trọng ở scale xem.

### 2.4. Run report (run.json)

Mỗi lần render ghi report: source path/sha256/kind/make/model/fileSize/hashUnchangedAfterRender/
orientationFlipApplied; recipe sha256 + developerBuildMatchesEngine; resolved params (EV, WB
mode+multipliers, look id/version/manifestSha/assetSha/amount/dimension, geometry, output);
decoderConfig echo; domain note; stage timings (ms); warnings; output width/height/bytes/
jpegSha256; diagnosticDump sha256; build fingerprint (GNU 16.2.0, -O3, C++17, libraw
0.22.2, libjpeg-turbo 3.2.0, JPEG_LIB_VERSION 62, zlib 1.3.2, developerBuild
`photo-engine-g1-libraw-0.22.2`, numerics: no fast-math, `-ffp-contract=off`).

### 2.5. Ví dụ lệnh đã chạy (từ thư mục photo_engine/)

```bash
export PATH="$PWD/tools/toolchain/mingw64/mingw64/bin:$PATH"
cmake -G Ninja -B build -S . -DCMAKE_BUILD_TYPE=Release && cmake --build build
./build/photoengine_tests.exe
ctest --test-dir build -R "unit|contract"
python tools/integration_test.py --cli build/photo-cli.exe \
  --fixture fixtures/raw/D7000_compressed_12bit_NIK_3876.NEF \
  --looks fixtures/looks --work build/integration_d7000
```

## 3. NOT_RUN / BLOCKED

| Hạng mục | Trạng thái | Lý do |
|---|---|---|
| ASan/UBSan trên host | **BLOCKED** | WinLibs GCC 16.2.0 không kèm runtime `-lasan`/`-lubsan`; đã chạy thay thế build `_GLIBCXX_ASSERTIONS` + `-fstack-protector-strong` (34/34 PASS). ASan thật cần toolchain khác (MSVC cl.exe bị thiếu trên máy, hoặc bộ MinGW có sanitizer). |
| renderedImage/linearDng/proRaw | NOT_RUN (bị chặn chủ đích) | G1 chỉ thực thi cameraRaw; probe nhận diện nhưng trả `PE_UNSUPPORTED_SOURCE`. |
| Grain/sharpening | NOT_RUN (từ chối có kiểm soát) | Tắt để cô lập màu theo docs/03 §3.4; recipe bật grain bị từ chối. |
| X-Trans / ProRAW / HEIC | NOT_RUN | Ngoài scope G1; cần spike riêng (R-07/B-17). |
| Tương đương iOS/Android | NOT_RUN | Cần harness 2 nền tảng (B-08); host numbers không suy ra mobile. |
| Chất lượng P0 (highlight headroom, false color 100%, WB fallback) | NOT_RUN đầy đủ | Đo đạc R-02 thuộc G2; P0 clip tại white level đã ghi nhận là giới hạn thiết kế. |
| Corpus 60 ảnh / holdout / look thẩm mỹ | NOT_RUN | B-02/B-16, cần quyết định B-01 (camera ưu tiên, thiết bị) — TBD. |
| Cancellation giữa chừng trên job thật | PARTIAL | Token có kiểm thử unit + check points trong pipeline; kịch bản hủy giữa decode trên file thật chưa nằm trong runner. |
| 30 warm/5 cold perf runs | NOT_RUN | Thuộc R-04; report hiện là 1 lần chạy mỗi fixture (single-shot), không phải benchmark. |

## 4. Giới hạn đã ghi nhận (không giấu)

1. **P0 bounded**: dữ liệu 16-bit integer từ decoder đã clip tại white level; FP32 phía sau
   không khôi phục highlight; exposure EV nhân trong linear, clamp [0,1] trước encode là
   hard clip. Không quảng cáo highlight recovery.
2. **WB normalized G=1** lưu trong recipe; LibRaw cam_mul trả thang ×256 nên init-recipe
   chia về G=1 — tương đương về tỉ lệ (dcraw tự normalize theo max multiplier), đã ghi trong code.
3. **ICC profile tự sinh** (không phải profile "sRGB IEC61966-2.1" chính hãng); đúng
   primaries/TRC matrix-shaper, parse được bằng ImageCms. Nếu sau này cần profile chứng
   nhận thì phải qua review provenance.
4. **metadataPolicy strip_location == minimal** trong G1: engine không re-embed EXIF máy ảnh
   (chỉ JFIF+ICC+EXIF tối thiểu) — hai policy cho ra metadata giống nhau; ghi rõ là giới hạn.
5. **output.longEdge > kích thước gốc**: không upscale (no-op giữ kích thước) — quyết định
   nhỏ đã ghi trong code, khác phương án "reject" nêu trong kế hoạch ban đầu.
6. **Lệch contract 1 điểm** (chờ review): `pe_image_info.color_contract = 2` (sRGB-encoded)
   cho output render — draft chỉ định nghĩa 1 (linear); lý do + marker trong header và G0 draft §5.
7. **Validator C++** chỉ phủ tập keyword của 2 schema hiện có (fail-closed với keyword lạ);
   không phải JSON-Schema 2020-12 đầy đủ. Python validator vẫn là tham chiếu.
8. Identity bit-exact giữa amount=0 và amount=1 quan sát được trên fixture (0.0 diff), nhưng
   đảm bảo kỹ thuật chỉ là ≤1e-6 (giữa grid point có sai số nội suy float) — tuyên bố theo test.

## 5. Vấn đề còn mở / đầu việc kế tiếp quan trọng nhất

Đầu việc kế tiếp **quan trọng nhất**: dựng **mobile harness gọi cùng core qua C ABI**
(B-08) — đây là bằng chứng duy nhất còn thiếu cho ADR-0001/ADR-0004 và gate G3; core đã
giữ ranh giới tích hợp sẵn (blocking C ABI, không UI dependency).

Các việc mở khác: (a) ASan trên toolchain có sanitizer cho test suite; (b) corpus B-02 +
quyết định camera ưu tiên B-01 (TBD với PO/TL); (c) R-02 đo clipping/headroom của P0 để
chuẩn bị quyết định G2; (d) cân nhắc thay `MOVEFILE`-based staging bằng cơ chế publish
của adapter khi tích hợp mobile.

## 6. Ý nghĩa Gate

Bằng chứng ở §2 đáp ứng điều kiện kỹ thuật G1 nêu trong docs/06 §6.4 (CLI từ RAW đến ảnh,
source bất biến, identity/recipe/export hoạt động, tái lập được, lỗi xử lý rõ). Việc **duyệt
G1 thuộc về Tech Lead + Imaging** — báo cáo này chỉ nộp bằng chứng. G1 chưa chứng minh
chất lượng thẩm mỹ, chưa tương đương iOS/Android, và không chuyển bất kỳ ADR nào sang Accepted.
