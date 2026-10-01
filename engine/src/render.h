// Render pipeline orchestration (docs/03 section 3.4 graph):
//   decode/develop (P0) -> normalize orientation -> exposure (linear)
//   -> clamp+encode sRGB -> look + amount (srgb-display-v1) -> decode sRGB
//   -> user geometry (crop, rotate, flip) -> optional downscale
//   -> clamp+encode sRGB -> quantize -> JPEG (export)
#pragma once
#include "buffer.h"
#include "look.h"
#include "recipe.h"
#include "raw_adapter.h"
#include <mutex>
#include <string>

namespace pe {

struct EngineLimits;
class CancelFlag;

struct StageTimings {
    double read_ms = 0, unpack_ms = 0, raw_process_ms = 0, raw_convert_ms = 0;
    double transfer_encode_ms = 0, transfer_decode_ms = 0, diagnostic_ms = 0;
    double cache_copy_ms = 0;
    bool cache_hit = false;
    double develop_ms = 0;
    double orientation_ms = 0;
    double exposure_ms = 0;
    double look_ms = 0;
    double geometry_ms = 0;
    double resize_ms = 0;
    double encode_prep_ms = 0; // final clamp+encode+quantize
    double jpeg_ms = 0;
    double total_ms = 0;
};

// One full-resolution developed frame per source. Immutable cached pixels are
// copied before downstream processing. Export never receives this cache.
struct PreviewCache {
    std::mutex mutex;
    std::string key;
    DevelopResult developed;
    uint64_t hits = 0, misses = 0, develops = 0;
    StageTimings last_timings;
};

struct RenderRequest {
    double exposure_ev = 0.0;
    bool has_multipliers = false;
    double wb_multipliers[4] = {1, 1, 1, 1};
    // Look (already loaded and validated against the recipe).
    const LookPackage *look = nullptr;
    double look_amount = 1.0;
    // Geometry
    double crop_left = 0, crop_top = 0, crop_width = 1, crop_height = 1;
    int rotation_quarter_turns = 0;
    bool flip_horizontal = false;
    // Output resize: 0 = keep original size (no resample).
    uint32_t long_edge = 0;
    bool collect_diagnostics = false; // CLI report only; no preview hot-path scan
    // TEST-ONLY audit observability (see AUD plan): when non-null, dump raw
    // stage checkpoints B0..B4 as packed RGB FP32 LE + descriptor JSON files
    // into this directory. Purely observational: no pipeline math changes.
    const char *audit_dir = nullptr;
    double audit_early_scale = 1.0; // test-only pre-scale-colors attenuation
    PreviewCache *preview_cache = nullptr;
    std::string upstream_key; // verified source hash + resolved WB + pipeline identity
};

struct RenderOutput {
    RgbFloatBuffer encoded; // srgb-display-v1 RGB FP32, geometry applied
    uint32_t orientation_flip_applied = 0; // decoder flip bitmask normalized
    uint32_t out_width = 0;
    uint32_t out_height = 0;
    uint64_t develop_saturated_channels[3] = {0, 0, 0};
    uint64_t exposure_clamped_channels[3] = {0, 0, 0};
    uint64_t cfa_filters = 0;
};

// Runs the full pixel pipeline from the source file to the pre-quantize
// encoded sRGB buffer. Returns false with a pe_status-mapped code in
// `status_out` (values match pe_status in photo_engine.h).
bool render_to_pixels(const std::string &source_path, const RenderRequest &request,
                      const EngineLimits &limits, CancelFlag *cancel,
                      RenderOutput &output, StageTimings &timings, int &status_out,
                      std::string &error);

// Quantizes an encoded sRGB buffer to 8-bit (round half up).
Rgb8Buffer quantize_to_rgb8(const RgbFloatBuffer &encoded, CancelFlag *cancel = nullptr);

} // namespace pe
