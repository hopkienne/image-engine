# Engine improvements and verification — 01/10/2026

Implemented the ordered correctness/performance improvements and ran a new clean-build independent audit.
Audit conclusion: **INCOMPLETE (required evidence remains BLOCKED/NOT_RUN)**. 32/33 required groups PASS.
This does not approve the proposed policy, G1/G2/G3, physical camera color or mobile readiness.

## Code changes

- Windows CLI converts wide arguments to UTF-8; source/look/recipe/output/report/checkpoint paths with Vietnamese and spaces are covered through CLI and C ABI.
- Default as-shot WB resolves an absent second green coefficient to G1 for three-color RAWs, following the decoder convention; zero/negative/non-finite required channels and missing four-color coefficients remain rejected. The new real-camera fixture exposed both a CLI init-recipe defect and invalid WB setup in AUD-018; both were corrected and rerun in a separate clean build.
- Source orientation is captured before `user_flip=0` causes LibRaw to clear `sizes.flip`. The engine now applies it exactly once before look/user geometry. Flip=5/6 map counterclockwise/clockwise respectively, matching LibRaw `flip_index`; old helpers and unit matrices had those directions swapped.
- CLI, preview and export share recipe mapping. CLI renders once; the same pixels feed diagnostics and a shared encode/staging path.
- Full-frame crop keeps its allocation; horizontal/vertical mirrors swap in place. JPEG output moves from a managed destination rather than copying a growing malloc buffer. Codec errors and cancel release state through RAII.
- Exact finite-u16 sRGB cache at EV=0 removes repeated scalar power calls before the look. All 65,536 possible decoder samples are checked for exact index recovery and bit-identical scalar results. No interpolation, fast-math, creative LUT change, or exposure approximation is introduced; the cache is 256 KiB.
- Cancel uses LibRaw progress callbacks, chunk/row checkpoints, RAII preview packing, JPEG rows and staging cleanup. Internal deterministic observers are absent from the public C ABI and unset for normal clients.
- Shared export uses exclusive creation to close the staging check/open race and retains write/flush/close fault handling. Audit fault injection is still compiled OFF by default.
- ICC colorants now use the same ICC D50 convention as header/wtpt. Independently derived Bradford colorants match the trusted Little CMS values. Prior maximum XYZ error was 0.0003105354608123889; new measurement is 1.913279902510112e-05, threshold unchanged at 0.0002.
- Post-develop saturation and exposure-clamp counts are reported by CLI. Diagnostics are disabled on the C ABI preview hot path. See [highlight evaluation](HIGHLIGHT_PIPELINE_EVALUATION.md); P0 clipping remains a documented limitation and no float-developer/highlight-recovery claim is made.
- Correct zlib build options exclude dependency installation/example tests from the engine's CTest configuration.

## Paired performance measurements

Release/GNU 16.2.0, same machine, fixed RAW SHA/recipe bytes, no audit checkpoint dumps.
One warm-up excluded, three measured repetitions, medians below. CPU time and every repetition are retained in JSON.
OS lifetime peak working set/commit counters were sampled every 10 ms; these are process peaks, not an enforcement mechanism for all audit subprocesses.
Benchmarked source is saved in `benchmark-source.zip`; the full audit core differs in formatting. The final scoped build additionally fixes default WB resolution and non-default orientation. Both benchmark Nikon fixtures have decoder flip=0 and fixed recipes, so the numerical path for these measurements is unchanged; the interleaved preview recheck runs the final production binary.

### CLI render/export

| Configuration | Before (s) | After (s) | Wall change | Peak working set before → after (MiB) |
|---|---:|---:|---:|---:|
| D3200_DSC_0059-full | 20.694 | 8.761 | +57.7% reduction | 837.4 → 516.5 |
| D3200_DSC_0059-2048 | 15.729 | 5.969 | +62.1% reduction | 592.3 → 516.5 |
| D7000_compressed_12bit_NIK_3876-full | 13.853 | 5.880 | +57.6% reduction | 563.7 → 349.0 |
| D7000_compressed_12bit_NIK_3876-2048 | 11.463 | 4.144 | +63.9% reduction | 409.8 → 349.0 |

All bytes outside ICC APP2 are identical to the baseline JPEGs, including compressed image data and other metadata.
ICC correction intentionally changes JPEG byte hashes. The earlier performance component before ICC correction also recorded byte-identical complete JPEGs.
`exportTotalMs` now means encoding/staging I/O; `renderAndExportMs` includes the pipeline and `pipelineExecutions` is 1.

### C ABI preview

| Configuration | Before (s) | After (s) | Wall change | Peak working set before → after (MiB) |
|---|---:|---:|---:|---:|
| D3200_DSC_0059-512 | 7.564 | 6.746 | +10.8% reduction | 562.3 → 516.6 |
| D3200_DSC_0059-2048 | 7.925 | 8.000 | -0.9% reduction | 562.0 → 516.6 |
| D7000_compressed_12bit_NIK_3876-512 | 5.055 | 3.670 | +27.4% reduction | 379.7 → 349.1 |
| D7000_compressed_12bit_NIK_3876-2048 | 5.419 | 4.064 | +25.0% reduction | 379.8 → 349.0 |

All serialized preview RGB FP32 bytes are identical to the baseline; the harness also validates RGBA alpha/layout.
D3200 timings showed substantial repetition variability; the 2048 preview wall median was effectively unchanged, with a 0.94% increase in this sample.
CPU medians fell across the preview configurations, and peak memory fell about 8%. These EV=0 desktop results do not guarantee all recipes or mobile latency.

A subsequent confirmatory D3200/2048 preview measurement uses five interleaved baseline/candidate pairs in alternating AB/BA order, with one initial warm-up pair excluded and no concurrent test workload.
Wall medians were 8.853 → 6.462 seconds (+27.0% reduction); CPU medians 8.578 → 6.219 seconds.
All FP32 output hashes are identical. Per-pair results are in `preview-interleaved-recheck/`; the original ambiguous measurement above is retained.

## Audit evidence

- 40 groups: {'PASS': 34, 'NOT_APPLICABLE': 2, 'BLOCKED': 1, 'NOT_RUN': 3}. Variant counts: {'PASS': 147, 'NOT_APPLICABLE': 2, 'BLOCKED': 3, 'NOT_RUN': 3}.
- Clean build, unit/contract results and tested binary hashes: `audit/cases/AUD-001/` and `audit/environment.json`.
- Final clean C++ build evidence is in `audit-regression-final/`; final source/production-binary orientation evidence is in `audit-orientation-harness-fix/`. Each aggregate result records its executed component. Initial failures remain in all historical runs. The clean final regression's AUD-018 runner failure was caused by a new comparator referencing the wrong checkpoint filename; changing it to the existing `B4_output.f32` is a harness-only correction and that case was rerun. One intermediate diagnostic regression was deliberately interrupted after discovering the direction mapping defect and is excluded from evidence.
- Final clean regression suite: 43/43 unit cases, 1,769/1,769 assertions; CTest unit/contract 2/2 PASS.
- Production binary at `build-audit-base/photo-cli.exe` has `PHOTO_ENGINE_AUDIT_FAULTS=OFF`. Unit/contract tests rerun on this build; a render with `PE_AUDIT_FAULT=write_short` succeeds and matches the prior normal JPEG byte-for-byte. Production flags, source and executable hashes are in `production/verification.json`.
- Real Olympus XZ-10 CC0 RAW with non-default orientation, SHA checked against repository record 2431. B0 is compared pixel-exact to independently mapped pre-orientation adapter output. Its scope is orientation conformance only; Nikon fixtures remain the LUT/color-conformance corpus.
- **Proposed policy erratum:** `frozenConventions.orientationNormalize` incorrectly describes forward transpose before source-axis mirrors. LibRaw's `src/write/file_write.cpp` `flip_index` swaps output coordinates for inverse sampling, then mirrors in source axes. The equivalent forward array map mirrors source axes before transpose. AUD-018 and hand-computed unit matrices now use that independently verified convention (flip=6 matches EXIF right/top, 90° clockwise). Policy bytes, required cases and numeric tolerances remain frozen; this correction is explicitly disclosed and does not approve the PROPOSED policy.
- ICC: 9,261 RGB double patches, including transfer breakpoints, converted to D50 XYZ with native Little CMS 2.17; no optimization, relative colorimetric intent. Wrong-TRC control is checked with the same comparator. Reference archive/library hashes and source derivation are in `reference-lcms/`.
- Cancel: 21 deterministic stage/reuse checks, plus async cancellation. Stage-return timings measure cleanup after a request at a checkpoint; they do not bound time to reach the next callback from an arbitrary external request.
- Mutation suite ran on the full improvement build before the later WB/orientation fixes; all 14 engine mutants and the NaN-skipping comparator mutant were detected. Corresponding mutant code paths are unchanged. The final orientation fixes additionally have failing pre-fix real-RAW evidence and passing corrected regression; mutation coverage is not claimed for those newly fixed paths. See `audit/cases/AUD-039/results.json` and isolated mutant patches/builds.
- AUD-037 measures the actual fresh audit build without checkpoint dumping and checks the declared screening wall/memory budgets. It is a single-sample diagnostic, separate from the repeated paired benchmark.
- Source hashes, complete artifact manifest and JUnit/aggregate consistency are verified by `verification.json`; all failures/incomplete cases remain visible.

## Remaining evidence limits

- AUD-033/canary-asan: BLOCKED — toolchain has no -lasan runtime
- AUD-033/canary-ubsan: BLOCKED — toolchain has no -lubsan runtime
- AUD-033/engine-under-sanitizer: BLOCKED — no sanitizer runtime in the pinned MinGW toolchain; requires MSVC (missing cl.exe on host) or an ASan-capable GCC; _GLIBCXX_ASSERTIONS build is recorded as a partial substitute
- AUD-034/runner: NOT_RUN — Coverage-guided fuzzing requires a libFuzzer-capable toolchain; current MinGW host has none. Budget also not allocated.
- AUD-036/runner: NOT_RUN — no implementation registered for this case ID
- AUD-038/runner: NOT_RUN — no implementation registered for this case ID

ASan/UBSan runtime remains unavailable in the pinned toolchain. Fuzzing, physical-color holdout and iOS/Android measurements remain unexecuted.
Non-integer resize quality, LUT dimensions 33/65 and broader cameras are not certified by the exercised variants.

## Reproduction and artifacts

- New audit: `artifacts/engine-improvements/20261001/audit/` (fresh build, results, XML, command logs and manifest).
- Final clean C++ regression, corrected orientation harness and combined evidence: `audit-regression-final/`, `audit-orientation-harness-fix/` and `audit-aggregate/`.
- Earlier diagnostic history: `audit-regression/` (WB fixed, orientation failure), `wb-regression-source.zip`, and `audit-regression-orientation/INTERRUPTED.md` (excluded incomplete run).
- Full-audit source snapshot: `full-audit-source.zip`; final source hashes are recorded in the regression and production verification.
- `final-regression-source.zip` preserves all compiled final-regression sources; `comment-only-update.json` records a later correction of stale orientation header comments. Removing only whole comment lines leaves identical code bytes. The production build recompiles that updated header; source provenance distinguishes the two texts explicitly.
- Paired benchmark: `benchmark-release/` and `benchmark-preview-release/`, with baseline-provenance pointers to immutable original measurements.
- Before-change source and binaries: `source-before.zip`, `source-before-sha256.json`, `baseline-photo-cli.exe`, `baseline-audit-harness.exe`.
- Reviewable changes: `improvements.patch`; generated matrix: `tests/acceptance/test_matrix.json`.
- Little CMS is a reference-only artifact, not a product dependency; official pinned source: https://github.com/mm2/Little-CMS/releases/tag/lcms2.17.

Run from `photo_engine` in PowerShell:

```powershell
$env:PATH = "$PWD/tools/toolchain/mingw64/mingw64/bin;$env:PATH"
$env:PE_AUDIT_LCMS_DLL = "$PWD/artifacts/engine-improvements/20261001/reference-lcms/lcms2.dll"
python tools/run_engine_audit.py --artifact-dir artifacts/engine-audit/new-unique-run --full-required --with-mutations
```

Use a fresh directory. Exit 0 requires every effective-required group PASS; 1 indicates FAIL; 2 indicates incomplete evidence.
