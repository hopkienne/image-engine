# G1 Implementation Plan — ánh xạ B-01..B-07 vào công việc thực tế

Ngày: 2026-09-30. Trạng thái: kế hoạch ngắn cho vòng G1, cập nhật theo kết quả thực tế
(xem G1_REPORT.md). Tham chiếu docs/08_delivery_backlog.md.

## Ánh xạ backlog → công việc

| ID | Công việc thực tế trong repo này | Kết quả |
|---|---|---|
| B-01 | `docs/rnd/G0_SCOPE_DRAFT.md` (scope, TBD, rủi ro). Không tự duyệt | Proposed |
| B-02 | `fixtures/fixtures_manifest.json` (theo cấu trúc `templates/dataset_manifest.json` của gói docs) + 1-2 RAW công khai có license/hash; chưa chia development/holdout | 1-2 fixture |
| B-03 | `third_party/manifest.json`: LibRaw, zlib, libjpeg-turbo, nlohmann/json, doctest — tag + URL + sha256 + license + lý do chọn; toolchain ghi trong G1_REPORT | Pinned |
| B-04 | Repo `photo_engine/`: target CMake `photoengine_core` (static), `photo-cli`, `photoengine_tests`; C ABI trong `engine/include/photo_engine.h` + `engine/src/c_api.cpp`; RAII toàn core; exception không qua ABI | Core+CLI |
| B-05 | `engine/src/raw_adapter.*`: adapter LibRaw pin cấu hình (output_color=1, gamm=1/1, output_bps=16, no_auto_bright, adjust_maximum_thr=0, user_flip=0, use_fuji_rotate=0, user_qual=AHD, highlight=0, WB=user_mul từ recipe); probe JSON không tin đuôi file; không dùng embedded JPEG | Adapter+P0 |
| B-06 | `engine/src/buffer.hpp` + `color.*`: BufferDescriptor đầy đủ (kích thước, stride, channelOrder, sampleType, transfer, primaries, range, orientation); domain `baseline-linear-bounded-v0` (linear sRGB D65 FP32 [0,1], clip tại white level của decoder) và `srgb-display-v1`; diagnostic pixel dump FP32 pre-quantize + descriptor JSON | Domain contract |
| B-07 | `engine/src/look.*` + `recipe.*` + `schema_validate.*`: load look package (schema, version/domain, hash manifest+asset, số mẫu, finite, dimension, path an toàn), LUT .cube parser strict, cube3d trilinear red-fastest, amount blend encoded-domain, amount=0 bypass; strict JSON (SAX: duplicate key, NaN/Inf, depth/size limit); mini JSON-Schema validator cho đúng tập keyword của 2 schema trong contracts/ + semantic checks | Look+validate |

## Trình tự build/verify

1. Third-party: build zlib → libjpeg-turbo (SIMD off) → LibRaw (static, link zlib+jpeg) bằng
   MinGW GCC pin; hash và version ghi vào build fingerprint.
2. Core: sha256 → strict_json → schema_validate → color → look → recipe → raw_adapter →
   geometry → icc_srgb → jpeg_encoder → render → c_api.
3. CLI: probe / init-recipe / render (+ --diagnostic-pixels, --report).
4. Tests (doctest): SHA-256 vectors; strict JSON negative; schema negative (bộ 8 case của
   scripts/validate_contracts.py + bổ sung); LUT parser negative (số dòng, NaN/Inf, sai
   dimension, sai domain, path escape); LUT bất đối xứng bắt lỗi đảo trục/kênh; sRGB
   encode/decode; identity == input (tolerance 1e-6); amount 0/0.5/1 và không reset
   exposure/WB; crop/rotate; C ABI success/error paths, export refuse existing path,
   cancellation; recipe semantic (crop bounds, grain, pipeline, longEdge upscale).
5. Python reference: chạy `scripts/validate_contracts.py` gốc của gói tài liệu (jsonschema
   4.x) như một test độc lập.
6. Integration (fixture thật): probe → init-recipe → render → report; re-hash source;
   render lần 2 so pixel dump pre-quantize (byte-identical) và so JPEG hash; test hash
   mismatch recipe → PE_ASSET_MISMATCH.
7. Sanitizer host nếu có thể (GCC -fsanitize=address,undefined trên MinGW — thử, nếu
   không chạy được thì ghi BLOCKED).

## Định nghĩa xong (G1)

- `photo-cli probe|init-recipe|render` chạy được với RAW thật; source hash trước/sau không đổi.
- Identity/recipe/export tái lập (pixel dump pre-quantize giống nhau giữa hai lần render).
- Mỗi lỗi trả mã PE_* + message rõ; không stub trả thành công.
- G1_REPORT.md tách IMPLEMENTED / VERIFIED / NOT_RUN|BLOCKED.
