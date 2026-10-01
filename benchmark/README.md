# RAW multi-engine benchmark

Working directory: `G:\zalo_mini_app\app\photo_engine`. The runner and artifacts are local;
no photos are uploaded. The current engine algorithm is unchanged from the snapshot.
The immutable policy's original proposal label remains unchanged; actual run
status/counts are in summary.json and index.html, not that proposal label.

## Run / resume

```powershell
Set-Location -LiteralPath G:\zalo_mini_app\app\photo_engine
python -m raw_benchmark doctor --policy benchmark/benchmark.policy.json
python -m benchmark.check_color_transform
python -m raw_benchmark run --policy benchmark/benchmark.policy.json --stage pilot --resume
python -m raw_benchmark run --policy benchmark/benchmark.policy.json --stage standard --resume
python -m raw_benchmark report --stage standard
python -m benchmark.finalize_report
python -m benchmark.verify_evidence
```

`--resume` checks content hashes of source, binary/dependencies, policy, settings,
look, target ICC, adapter, normalizer and metrics; it also checks lossless output
and settings files before reuse. Cache reuse is not a render time sample. Omit
`--resume` to create fresh attempt folders; previous attempts remain. Run `doctor`
before rendering if checking the installed packages, then keep the engine lock
unchanged across pilot/holdout. A frozen holdout rejects configuration drift.

Output: `artifacts/multi-engine-benchmark/20261001/run-v1/index.html`.
Open it directly in a browser. All HTML/images/logs are relative local files, no CDN.
If the browser restricts local files, serve only loopback:

```powershell
python -m http.server 8765 --bind 127.0.0.1 --directory artifacts/multi-engine-benchmark/20261001/run-v1
```

Then open `http://127.0.0.1:8765/`. The benchmark does not start this server itself.

## Pinned software and setup evidence

Python 3.14, project-local tifffile 2026.9.20, imagecodecs 2026.8.16, psutil 7.2.2;
existing NumPy and Pillow versions are recorded in engines.lock.json. The installed
project-local packages remain in benchmark/python-deps. For another matching Python:

```powershell
python -m pip install --target benchmark/python-deps --no-deps tifffile==2026.9.20 imagecodecs==2026.8.16 psutil==7.2.2
```

The current run hashes actual package files, including the reference EXEs and DLLs.
Official package download URLs, release API evidence, and verified publisher
SHA256 digests are in benchmark/tools/downloads.json and benchmark/reference/.
RT 5.13 is extracted from its official portable ZIP. darktable 5.6.1 was installed
CURRENTUSER into benchmark/tools/darktable-5.6.1, no administrator privileges, using
the verified official installer. Install log is retained. Its HKCU install records
and IOLIBS environment entry were created by the installer. LUT3D DLL loading fails
on this host; the module is disabled in BASE and the warning remains in logs.

The independent normalizer uses the hash-pinned locally compiled Little CMS 2.17
DLL at artifacts/engine-improvements/20261001/reference-lcms/lcms2.dll. That directory
contains official source archive/hash and exact compilation argv/provenance.
benchmark/check_color_transform.py verifies a nonidentity linear-to-encoded sRGB
float transform against independent piecewise expected values. Harness H01-H14
is rerunnable using `python -m raw_benchmark selftest`.

The final verifier also compares RT's actual ICC with the official bundled
RTv4_sRGB profile. For darktable it independently rebuilds the pinned release's
sRGB v2.4 color tags (D65 xyY 0.31271/0.32902, parametric TRC type 4) and compares
matrix/TRC/whitepoint/adaptation payloads byte-exactly. Its v2 tabulated TRC is not
required to equal the normalizer's v4 parametric profile. Differences remain
measured and the actual CMS conversion is retained. Source URLs/hashes and values
are saved in profile-contract-evidence.json; no measurement pixels are changed.

## Measurement contracts

Ours: exact production encoded-sRGB FP32 before JPEG quantization; the matching
JPEG supplies ICC bytes only. Its native-f32.zip preserves the exact diagnostic
bytes and descriptor with a verified decompressed hash. JPEG pixels are never
measurement input. RT and darktable: real 16-bit RGB TIFF exports, with ICC.
Normalized TIFFs preserve float32 losslessly with verified roundtrip, LCMS float
color conversion, known orientation and an explicit SDR clamp after range evidence.
Native exports remain unchanged, including floats when present.

darktable XMP is generated per source by the pinned executable, then optional
modules are disabled while keeping required RAW, WB, input/output and orientation
modules. No fabricated camera-calibration blobs. Effective XMP is extracted from
the controlled export. RT uses explicit PP3 over its documented neutral defaults,
without `-d`, `-s`, `-S`; its complete merged PP3 is exported and checked. Engine
WB is resolved separately from each converter's as-shot policy. Perturbation jobs
prove configurations affect actual pixels. Default initialization is evidence,
not a second mode mixed into BASE metrics.

Each render receives a real RAW working copy, job-local settings/cache/config/temp,
CPU affinity at most four logical processors and OMP thread budget four. Original
and working hashes are checked afterward. Originals remain; only verified job RAW
copies and archive-verified temporary FP32 files are removed to control disk usage.
Process-tree working set is sampled about every 50ms and can underestimate peaks.
Fresh process does not mean cold OS/disk cache; three repeats have no p95 estimate.
Main execution timings exclude normalization and darktable's separate history
generation pass. Ours CLI wall time includes JPEG export plus writing/hashing the
FP32 diagnostic dump; it is not JPEG-only production latency. Internal stage
timers are retained in each engine-report.json and summarized for repeat fixtures
in performance-breakdown.json. Pipelines differ, so timings do not establish an equivalent-work
speed ranking or mobile performance.

Pixel comparisons require the same integer displacement in three native-grid edge
patches with correlation >=0.80 after known orientation. No resize, warp, tone/WB
matching. Failed mapping is NOT_COMPARABLE and produces no pixel metric. Overview
resizing/8-bit conversion is display-only. Matched 512-pixel crops have 100% CSS
size; independent gallery crops are explicitly marked as candidate/unsynchronized.
Endpoint fractions use encoded sRGB; Y quantiles use linear sRGB. Detail/chroma
proxies conflate texture, demosaic and noise, not sensor SNR. Heatmaps use fixed
0..0.25 encoded RGB mean absolute error scale. Two valid references are needed for
triage; no missing reference is replaced with zero. Converters are not ground truth.

## Corpus / review / limitations

40 immutable selected CC0 entries, 28 development / 12 holdout; 12 development pilot.
Each file stores actual publisher row/license evidence, URL, publisher SHA and
actual SHA/bytes. Same-camera variants are conservatively grouped together because
real scene/session labels are unknown. All failed selected files remain in the
planned 120-job denominator. The corpus and split are locked before holdout, no
camera certification. Scene/lighting/portrait coverage is UNKNOWN, not guessed.
FiveK remains PENDING_LICENSE_REVIEW and is not downloaded. Absolute chart accuracy
is NOT_RUN: NO_VALID_COLOR_REFERENCE. Public single shots establish neither physical
color accuracy nor highlight recovery stops.

Blind review is at blind/index.html; alias image filenames do not identify engines,
mapping is in separate blind-mapping.json. It is not claimed to be double-blind.
The reviewer enters ID/notes and downloads feedback JSON. No reviewer scores are
fabricated. View all flagged scenes and deterministic >=20% nonflagged scenes to
check false negatives. Absent feedback remains NOT_REVIEWED. G2 approval is manual.

The older sanitizer/fuzz/mobile gaps are deferred by the user's current instruction;
this benchmark does not claim to close them.

## Exact preservation of older attempts

Current latest native exports and normalized measurement files remain ordinary
files. Byte-identical generated derivatives may share NTFS storage; originals
are never hardlinked. See storage-deduplication.json.

Some older, superseded native TIFF/ZIP containers are represented by an adjacent
`*.history.json`: original metadata bytes plus references to byte-identical
compressed payloads in retained native exports. Each whole-file SHA256 was
reconstructed and checked before removal. This does not decode, reencode or alter
pixels. Historical result records point to the restoration manifest. All required
payloads must travel with the complete run directory. The independent artifact
verification reconstructs every historical container into its original hash.

To materialize one historical native export (needs free space within the quota):

```powershell
python -m benchmark.archive_history restore --manifest <absolute-path-to-native.tif.history.json>
```

The tool refuses to overwrite a different existing file. historical-storage.json
records each original digest, storage manifest and bytes saved. The archived
containers are superseded attempts, not current exports or RAW originals.
`lossless-history-tests.json` also records a real TIFF/ZIP restoration self-test.

`benchmark-source.zip` saves runner/config/helper sources, the protocol/matrix,
publisher/source documentation, identity technical look and the small independent
LCMS DLL with its source archive/provenance. It is separate from the unchanged
engine baseline. delivery-lock.json records its hash. The complete evidence
directory, pinned render tools and project-local Python dependencies are required
for replay; the ZIP alone does not contain RAWs or the three render executables.
