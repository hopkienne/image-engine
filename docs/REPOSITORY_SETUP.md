# Source repository and local data

This repository contains the engine, CLI, vendored dependency sources, tests,
contracts, small look fixtures, benchmark scripts/configuration, and documentation.
Generated results and installed tools stay local and are excluded by `.gitignore`.

## Build dependencies

Keep `third_party/src/`, `third_party/include/`, and their bundled license files:
the root CMake configuration uses these sources directly. Dependency versions,
download URLs, SHA-256 hashes, and the original Windows compiler pin are recorded
in `third_party/manifest.json`.

Install the build tools described in the root README before building. The original
portable compiler directory `tools/toolchain/` is not included in Git. Follow the
README build instructions with the compiler available on PATH; a clone does not
include executables or previous build directories.

## RAW test inputs

`fixtures/raw/` is excluded from Git. To run tests that require real RAW images,
download each development fixture from the URL in
`fixtures/fixtures_manifest.json`, save it at its `relativePath` under `fixtures/`,
and verify its SHA-256 against the manifest. Keep the small look packages under
`fixtures/looks/` in Git. Fixture provenance notes remain in the manifest and
`THIRD_PARTY_NOTES.md`.

## Optional benchmark and audit environment

See `benchmark/README.md` and `tests/acceptance/README.md`. Benchmark application
downloads are recorded in `benchmark/tools/downloads.json`; installed applications
and `benchmark/python-deps/` are excluded. Recorded absolute paths describe the
original machine and must be adapted for another checkout.

The independent Little CMS test library is also excluded. Its original source is
`https://codeload.github.com/mm2/Little-CMS/tar.gz/refs/tags/lcms2.17`, with archive
SHA-256 `6e6f6411db50e85ae8ff7777f01b2da0614aac13b7b9fcbea66dc56a1bc71418`.
The original Windows build compiled all `src/cms*.c` files from that archive with
GCC using `-shared -O2 -DCMS_DLL_BUILD`, the archive's `include/` directory on the
include path, and `-o lcms2.dll`. The audit uses `PE_AUDIT_LCMS_DLL`; the benchmark
currently expects the DLL and its build provenance at
`artifacts/engine-improvements/20261001/reference-lcms/`. Recreate this environment
before running those checks. Little CMS is not linked into the production engine.

Historical reports in `docs/` refer to local evidence under `artifacts/`. Those
links will not resolve in a fresh clone unless that evidence is restored separately.
Preserve the original evidence outside Git when it is needed for review; do not
interpret a source checkout as including historical benchmark results.

The sibling `../raw_photo_app_rnd_v0.1` documentation package referenced by the
README is not part of this engine repository. CMake only registers its optional
Python contract reference test when the package is present. Core contract schemas
are included under `contracts/`.
