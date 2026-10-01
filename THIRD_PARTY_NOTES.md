# Third-party notes (G1)

Full pins (tag, URL, sha256, license identifier, rationale) live in
[third_party/manifest.json](third_party/manifest.json). Summary and caveats:

| Component | Version (pinned tag) | License | Used for |
|---|---|---|---|
| LibRaw | 0.22.2 (upstream release tag, not a snapshot) | LGPL-2.1-only OR CDDL-1.0 | RAW decode + P0 postprocessing behind RawDecoderAdapter |
| zlib | 1.3.2 | Zlib | Deflate containers inside LibRaw |
| libjpeg-turbo | 3.2.0 | IJG + BSD-3-Clause | JPEG encoding (export), JPEG-compressed containers in LibRaw |
| nlohmann/json | 3.12.0 | MIT | JSON value model/SAX behind strict_json wrapper |
| doctest | 2.5.3 | MIT | Unit tests only (not in the product pipeline) |
| WinLibs MinGW-w64 (toolchain) | GCC 16.2.0 r2 | GPL-3 with runtime exceptions | Host build only |

In-house replacements used deliberately:

- **SHA-256** implemented from FIPS 180-4 (engine/src/sha256.*), validated
  against the standard test vectors — avoids pulling a crypto dependency for
  one algorithm.
- **sRGB ICC v2 profile** generated in-engine (engine/src/icc_srgb.*),
  matrix-shaper + 1024-entry sRGB TRC, byte-deterministic; parse-checked with
  Pillow/ImageCms in the integration run. No third-party profile is shipped.

Honest caveats (docs/09):

1. LibRaw's dual license and the chosen link model are a **legal review item**,
   not something this G1 slice decides. The repo records the exact version so
   the review has a fixed target.
2. libjpeg-turbo is built **without SIMD** here for a deterministic, NASM-free
   build. That is a performance trade-off; JPEG *pixels* still follow the same
   spec, but encode speed on the host is lower than an SIMD build.
3. The RAW fixtures under fixtures/raw come from the raw.pixls.us community
   corpus (upload policy requires CC0 dedication). Each fixture's URL, hash and
   license note are in fixtures/fixtures_manifest.json. Before any wider
   redistribution, re-verify the license entry on the source page; the copies
   here are used only as local test inputs.
4. No Python runtime participates in the product image path; Python (jsonschema,
   Pillow) is used only by validation/test tooling.
