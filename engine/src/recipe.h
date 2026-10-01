// Recipe parsing + validation (schema then semantics), per docs/04 section 4.5.
// Schema-valid does not imply executable: any parameter this build cannot
// execute is rejected explicitly, never silently ignored.
#pragma once
#include "buffer.h"
#include <nlohmann/json.hpp>
#include <string>
#include <vector>

namespace pe {

struct EngineLimits;

struct EngineIdentity {
    const char *engine_compatibility; // engineCompatibility value this build accepts
    const char *pipeline_id;          // e.g. "baseline-v0"
    const char *pipeline_version;     // e.g. "0.1.0"
    const char *developer_build;      // e.g. "libraw-0.22.2;photo-engine-g1"
};

struct RecipeModel {
    std::string recipe_id;
    // source
    std::string source_id;
    std::string source_sha256;
    std::string source_kind;
    // execution
    std::string engine_compatibility;
    std::string pipeline_id;
    std::string pipeline_version;
    std::string developer_build;
    bool has_camera_profile = false; // must be false for this build
    // adjustments
    double exposure_ev = 0.0;
    std::string wb_mode;
    bool has_multipliers = false;
    double wb_multipliers[4] = {1, 1, 1, 1}; // R, G(1), B, G2 order per docs/03.6
    // look
    std::string look_id;
    std::string look_version;
    std::string look_manifest_sha256;
    double look_amount = 1.0;
    // geometry
    double crop_left = 0, crop_top = 0, crop_width = 1, crop_height = 1;
    int rotation_quarter_turns = 0;
    bool flip_horizontal = false;
    // grain
    bool grain_enabled = false;
    // output
    int quality = 92;
    std::string subsampling = "444";
    bool has_long_edge = false;
    uint32_t long_edge = 0;
    std::string metadata_policy;
};

struct SchemaValidators {
    // Loaded from the embedded contract schemas (see embedded_schemas.hpp).
    class MiniSchemaValidator *recipe; // pe::MiniSchemaValidator
    class MiniSchemaValidator *look;
};

// Parses and schema-validates. Returns false with `error` on any problem.
bool parse_recipe_json(const char *data, size_t size, const EngineLimits &limits,
                       SchemaValidators validators, nlohmann::json &out_json,
                       std::string &error);

// Semantic checks that need engine capability. `out` is filled when all pass.
bool validate_recipe_semantics(const nlohmann::json &recipe, const EngineIdentity &identity,
                               RecipeModel &out, std::string &error);

} // namespace pe
