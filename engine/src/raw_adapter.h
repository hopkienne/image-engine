// LibRaw adapter (docs/02 section 2.2, RawDecoderAdapter + RawDeveloper P0).
// The decoder is configured explicitly for every stage it performs; nothing
// relies on library defaults. Embedded JPEG is never used as image data.
#pragma once
#include "buffer.h"
#include <string>
#include <vector>

namespace pe {

struct EngineLimits;
class CancelFlag;

struct SourceProbe {
    std::string make, model, normalized_make, normalized_model;
    std::string libraw_version;
    uint32_t dng_version = 0;
    unsigned raw_count = 0;
    uint32_t colors = 0;
    uint64_t filters = 0;
    uint32_t raw_width = 0, raw_height = 0;
    uint32_t width = 0, height = 0; // visible area, pre-orientation
    uint32_t top_margin = 0, left_margin = 0;
    uint32_t iwidth = 0, iheight = 0;
    uint32_t flip = 0; // dcraw flip bitmask reported by the decoder
    double cam_mul[4] = {0, 0, 0, 0};  // as-shot WB reported by the decoder
    double pre_mul[4] = {0, 0, 0, 0};
    uint32_t black_level = 0;
    uint32_t white_level = 0;
    bool has_thumbnail = false;
    bool thumbnail_is_jpeg = false;
    std::string kind; // cameraRaw | linearDng | proRaw (heuristic, Proposed)
    uint64_t file_size = 0;
    std::string sha256;
    std::string iso_speed, shutter, aperture; // display strings, no GPS/serial
};

// Opens the file (metadata only; no unpack) and fills SourceProbe.
// Maps failures onto PE_* codes via `pe_status_out` (see enum in photo_engine.h,
// values replicated here to avoid pulling the C header into core).
enum RawStatus {
    RawOK = 0,
    RawUnsupportedSource = 1,
    RawCorruptSource = 2,
    RawSourceUnavailable = 3,
    RawResourceLimit = 8,
    RawOutOfMemory = 9,
    RawCancelled = 10,
    RawIo = 11,
    RawInternal = 12,
};

bool raw_probe(const std::string &path, const EngineLimits &limits,
               SourceProbe &out, RawStatus &status, std::string &error);

// Resolve recipe WB normalized to G1. Three-color RAWs may omit G2 (zero);
// use G1 in that case only. Invalid required coefficients remain errors.
bool resolve_as_shot_wb(const SourceProbe &probe, double (&multipliers)[4]);

struct DevelopMeta {
    std::string make, model, libraw_version;
    uint32_t width = 0, height = 0; // decoded frame size (pre-orientation)
    uint32_t flip = 0;
    uint32_t black_level = 0, white_level = 0;
    double cam_mul[4] = {0, 0, 0, 0};
    uint64_t filters = 0;
    uint32_t colors = 0;
    uint64_t saturated_channels[3] = {0, 0, 0}; // post-develop 16-bit endpoint
};

struct DevelopResult {
    RgbFloatBuffer buffer; // Domain::LinearBounded, RGB interleaved FP32 in [0,1]
    DevelopMeta meta;
    double read_ms = 0, unpack_ms = 0, process_ms = 0, convert_ms = 0;
};

struct DevelopConfig {
    double wb_multipliers[4] = {1, 1, 1, 1}; // R, G(1), B, G2 (LibRaw user_mul order)
    bool collect_diagnostics = false;
    const char *audit_dir = nullptr;
    double audit_early_scale = 1.0; // test-only, requires audit_dir; not recipe/API
};

// Full decode + develop. The decoder configuration is fixed and echoed in
// `config_echo` (JSON) for the run report.
bool raw_develop(const std::string &path, const DevelopConfig &config,
                 const EngineLimits &limits, CancelFlag *cancel,
                 DevelopResult &out, RawStatus &status, std::string &error);

// JSON fragment describing the pinned decoder configuration (for reports).
std::string raw_developer_config_echo_json();

} // namespace pe
