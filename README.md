# photo_engine â€” Shared Photo Engine (G1)

Implementation repository for the Shared Photo Engine vertical slice at milestone
**G1** (baseline end-to-end), following the Proposed documents in
`../raw_photo_app_rnd_v0.1` (docs 01â€“10, contracts, C ABI draft). Status of
what is implemented vs verified vs not run lives in
[docs/rnd/G1_REPORT.md](docs/rnd/G1_REPORT.md).

For a fresh clone, see [repository setup and excluded local data](docs/REPOSITORY_SETUP.md).
Build tools, RAW inputs, and historical benchmark artifacts are restored separately.

## What runs (G1 vertical)

```
RAW tháº­t -> photo-cli probe -> init-recipe (pins source/look hashes, resolves as-shot WB)
        -> render (develop via LibRaw P0 -> identity/cube3d look -> JPEG sRGB export)
        -> run report (hashes, build fingerprint, stage timings, warnings)
        -> re-render with the saved recipe reproduces the same pixels
```

Only `cameraRaw` (Bayer RGB mosaic) sources are executable in this build;
`renderedImage`, `linearDng`, `proRaw` are recognized by probe but rejected with
`PE_UNSUPPORTED_SOURCE`. Grain is rejected when enabled (not implemented â€” the
color pipeline is intentionally isolated). There is no embedded-JPEG fallback
anywhere in the decode path.

## Repository layout

```
engine/    core C++17: C ABI (include/photo_engine.h), decode, color, look, recipe, export
cli/       photo-cli (probe / init-recipe / render)
tests/     doctest unit tests (34 cases, 1392 assertions)
contracts/ verbatim copies of recipe.schema.json + look.schema.json (embedded at build time)
fixtures/  RAW fixtures + fixtures_manifest.json (license, hash, provenance)
tools/     integration_test.py (end-to-end runner), build_fingerprint comes from CMake
docs/rnd/  G0 scope draft, G1 implementation plan, G1 report
third_party/ pinned dependency sources + manifest.json (tags, sha256, licenses)
```

## Toolchain (this host)

- MinGW-w64 GCC 16.2.0 (WinLibs portable, extracted under `tools/toolchain/`,
  no system changes) â€” pinned + sha256 in `third_party/manifest.json`
- CMake 4.4.3 + Ninja 1.13.2 (pip wheels)
- MSVC was not usable on this host (VS 2022/2019 installed without the C++
  toolchain or Windows SDK)

## Reproducible build on this host

```bash
# from the repository root (photo_engine/)
export PATH="$PWD/tools/toolchain/mingw64/mingw64/bin:$PATH"
cmake -G Ninja -B build -S . -DCMAKE_BUILD_TYPE=Release
cmake --build build

# unit tests
./build/photoengine_tests.exe

# end-to-end on a real RAW fixture (see fixtures/fixtures_manifest.json)
python tools/integration_test.py \
  --cli build/photo-cli.exe \
  --fixture fixtures/raw/D7000_compressed_12bit_NIK_3876.NEF \
  --looks fixtures/looks \
  --work build/integration_d7000
```

Third-party libraries (zlib, libjpeg-turbo, LibRaw) build automatically from the
vendored, hash-verified tarballs in `third_party/src/`.

## CLI

```bash
# 1. Inspect the source (JSON on stdout; hashes + decoder metadata, no extension guessing)
photo-cli probe <input.raw> --json

# 2. Create a recipe pinning the source hash, the look package hash and the
#    resolved as-shot white balance (G = 1 normalization)
photo-cli init-recipe <input.raw> --look fixtures/looks/identity-technical-fixture \
        --out recipe.json [--amount 1.0] [--quality 92] [--subsampling 444|420]

# 3. Render + export + report (never overwrites the source or an existing output)
photo-cli render <input.raw> --recipe recipe.json \
        --look fixtures/looks/identity-technical-fixture \
        --out output.jpg --report run.json [--diagnostic-pixels <prefix>]
```

Exit codes: 0 success, 1 engine error (`PE_*` name + JSON diagnostics on stderr),
2 usage error. `--diagnostic-pixels <prefix>` writes `<prefix>.f32` (pre-quantize
FP32 RGB, sRGB-encoded) plus `<prefix>.json` (BufferDescriptor) â€” this is the
pixel state compared for reproducibility, before JPEG quantization.

## Engine configuration

`pe_engine_create` accepts a JSON config:

```json
{"configVersion": 1,
 "limits": {"maxInputBytes": 1073741824, "maxPixels": 100000000,
            "maxDecodedBytes": 3200000000, "maxLutBytes": 67108864,
            "maxLutDimension": 65, "maxJsonBytes": 2097152, "maxJsonDepth": 64},
 "assetSearchPaths": ["fixtures/looks"]}
```

Unknown keys are rejected (`PE_INVALID_ARGUMENT`). Look packages are resolved by
`manifestSha256` pin from the recipe; a pinned-but-invalid package is never
silently swapped for another one (`PE_ASSET_MISMATCH`).

## Notes

- The C ABI adds one review-pending amendment to the draft header
  (`color_contract = 2`, sRGB-encoded output) â€” see
  docs/rnd/G0_SCOPE_DRAFT.md Â§5 and the [PE-G1-NOTE] markers in
  engine/include/photo_engine.h.
- ADR-0001..0006 remain Proposed; nothing here approves them.
- Licensing: dependency pins and license identifiers are recorded in
  third_party/manifest.json and THIRD_PARTY_NOTES.md; distribution decisions
  still require legal review (docs/09 Â§9.4).

## Independent audit follow-up (30/09/2026)

Bằng chứng audit mới và các blocker hiện tại nằm trong [báo cáo QA](docs/qa/G1_INDEPENDENT_AUDIT_REPORT.md),
[ma trận 40 nhóm test](tests/acceptance/test_matrix.json) và [hướng dẫn chạy lại](tests/acceptance/README.md).
Báo cáo G1 ban đầu là lịch sử của lượt triển khai; dùng báo cáo QA để đánh giá kết quả kiểm chứng độc lập mới.

## Engine improvements (01/10/2026)

See [implementation, measured performance and remaining limits](docs/qa/ENGINE_IMPROVEMENTS_20261001.md).
CLI paths accept UTF-8 on Windows. CLI diagnostics and JPEG export use one render;
`timings.exportTotalMs` now measures encoding/staging I/O only, while
`renderAndExportMs` includes the pipeline and `pipelineExecutions` is 1.
Preview/export/CLI share recipe mapping. Cancellation covers LibRaw callbacks,
pixel chunks, geometry rows, preview packing, JPEG rows and staging cleanup.
Default as-shot WB resolves a missing second green coefficient for three-color
RAWs. Source orientation is retained before decoder processing clears it;
dcraw flip=5/6 correctly map to counterclockwise/clockwise 90-degree rotations.
The QA report records the earlier helper/unit-oracle error and the corresponding
erratum in the still-proposed frozen audit policy.
Full-frame crop and mirrors avoid replacement allocations. EV=0 pre-look sRGB
encoding caches exact scalar values for all 65,536 decoder samples (256 KiB),
with no interpolation or change to creative LUT math.

`highlightDiagnostics` reports post-develop saturated channels and exposure
clamping before crop/resize. Counts are observations, not sensor-clipping proof.
The P0 decoder remains bounded; highlight recovery needs a separate validated
pipeline version. The corrected ICC colorants use the same D50 convention as
the profile white point; JPEG ICC bytes change while compressed image data stays identical.

Paired Windows benchmarks: `tools/benchmark_engine.py` (wall/CPU time, lifetime
peak working set/commit, one excluded warm-up and at least three repetitions).
Audit float XYZ requires `PE_AUDIT_LCMS_DLL` pointing to a hash-recorded independent
Little CMS library; it is a test dependency and is not linked into the engine.
