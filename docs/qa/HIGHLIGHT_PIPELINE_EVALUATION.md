# Highlight pipeline evaluation — 01/10/2026

P0 remains `baseline-v0 0.1.0`: LibRaw develop returns bounded 16-bit RGB,
converted to FP32, followed by exposure, clamping and the display-domain look.
This update fixes ICC semantics and adds diagnostics; it does not claim highlight recovery.

## Measured observations

At EV=0 with the pinned as-shot white balance, the paired benchmark reports:

| RAW | Post-develop samples at the 16-bit endpoint, R/G/B | Samples pushed above 1 by exposure |
|---|---|---|
| Nikon D3200 | 1,087 / 6 / 0 | 0 / 0 / 0 |
| Nikon D7000 | 1,228 / 9,345 / 24,343 | 0 / 0 / 0 |

These are channel-sample counts before crop/resize, not counts of distinct pixels.
An endpoint can be legitimate white, so the numbers do not prove sensor clipping.
The complete JSON reports are retained under
`artifacts/engine-improvements/20261001/benchmark-release/candidate/`.
AUD-017 independently measures the increase of clipping at EV=+1/+2.

Where distinct decoder values have already collapsed to the same 16-bit endpoint,
later exposure cannot distinguish them. At EV=-2 they all become 0.25 in linear
space. Casting this output to float, changing a descriptor, or replacing only
the final clamp cannot restore the lost information.

## Proposed next pipeline and decision criteria

1. Keep LibRaw for unpack/metadata. Evaluate a float developer that retains
   black-corrected and white-normalized mosaic values, WB, demosaic and camera
   color conversion without an intermediate bounded 16-bit output. Decoder
   `output_bps` alone does not provide this pipeline.
2. Preserve values above 1 until a documented highlight/gamut/tone mapping step
   produces the bounded sRGB display domain expected by existing creative LUTs.
   Specify the working primaries, white point, units, negative-value policy,
   channel clipping and highlight reconstruction independently.
3. Introduce a distinct pipeline ID/version and explicit look compatibility.
   Do not reinterpret existing recipes or silently substitute new color math.
4. Validate against a holdout corpus: bracketed highlights, neutral and color
   charts, mixed illumination, saturated colors and multiple Bayer cameras.
   Compare highlight gradients, neutral WB, hue stability, noise, clipping and
   output transforms using frozen acceptance criteria and independent references.
5. Benchmark preview latency, cancellation, peak memory and full export before
   adoption. A float developer must not erase the memory improvements made here.
   Mobile measurements and sanitizer/fuzz evidence remain separate requirements.

The current two Nikon photographs and one Olympus orientation fixture do not
provide the physical-color/holdout evidence needed to choose or certify this
new developer. The orientation fixture is used only for mapping conformance.
