#include "recipe.h"
#include "engine_limits.h"
#include "schema_validate.h"
#include "strict_json.h"
#include <cmath>
#include <cstring>

namespace pe {

bool parse_recipe_json(const char *data, size_t size, const EngineLimits &limits,
                       SchemaValidators validators, nlohmann::json &out_json,
                       std::string &error) {
    if (!strict_json_parse(data, size, limits.json_limits(), out_json, error)) {
        error = "recipe JSON: " + error;
        return false;
    }
    if (!validators.recipe->validate(out_json, error)) {
        error = "recipe schema: " + error;
        return false;
    }
    return true;
}

namespace {

bool get_number(const nlohmann::json &j, const char *key, double &out) {
    auto it = j.find(key);
    if (it == j.end() || !it->is_number()) return false;
    double v = it->get<double>();
    if (!std::isfinite(v)) return false;
    out = v;
    return true;
}

} // namespace

bool validate_recipe_semantics(const nlohmann::json &recipe,
                               const EngineIdentity &identity, RecipeModel &out,
                               std::string &error) {
    out.recipe_id = recipe["recipeId"].get<std::string>();

    const nlohmann::json &source = recipe["source"];
    out.source_id = source["id"].get<std::string>();
    out.source_sha256 = source["sha256"].get<std::string>();
    out.source_kind = source["kind"].get<std::string>();

    const nlohmann::json &execution = recipe["execution"];
    out.engine_compatibility = execution["engineCompatibility"].get<std::string>();
    out.pipeline_id = execution["pipelineId"].get<std::string>();
    out.pipeline_version = execution["pipelineVersion"].get<std::string>();
    out.developer_build = execution["developerBuild"].get<std::string>();
    out.has_camera_profile = !execution["cameraProfile"].is_null();

    const nlohmann::json &adj = recipe["adjustments"];
    if (!get_number(adj, "exposureEV", out.exposure_ev)) {
        error = "adjustments.exposureEV must be a finite number";
        return false;
    }
    const nlohmann::json &wb = adj["whiteBalance"];
    out.wb_mode = wb["mode"].get<std::string>();
    const nlohmann::json &mult = wb["resolvedCameraMultipliers"];
    out.has_multipliers = !mult.is_null();
    if (out.has_multipliers) {
        if (!mult.is_array() || mult.size() != 4) {
            error = "whiteBalance.resolvedCameraMultipliers must have 4 entries";
            return false;
        }
        for (int i = 0; i < 4; i++) {
            if (!mult[i].is_number() || !std::isfinite(mult[i].get<double>()) ||
                mult[i].get<double>() <= 0.0) {
                error = "whiteBalance.resolvedCameraMultipliers must be finite and > 0";
                return false;
            }
            out.wb_multipliers[i] = mult[i].get<double>();
        }
    }

    const nlohmann::json &look = recipe["look"];
    out.look_id = look["id"].get<std::string>();
    out.look_version = look["version"].get<std::string>();
    out.look_manifest_sha256 = look["manifestSha256"].get<std::string>();
    out.look_amount = look["amount"].get<double>();

    const nlohmann::json &geom = recipe["geometry"];
    const nlohmann::json &crop = geom["crop"];
    out.crop_left = crop["left"].get<double>();
    out.crop_top = crop["top"].get<double>();
    out.crop_width = crop["width"].get<double>();
    out.crop_height = crop["height"].get<double>();
    out.rotation_quarter_turns = geom["rotationQuarterTurns"].get<int>();
    out.flip_horizontal = geom["flipHorizontal"].get<bool>();
    // Semantic: crop must fit within the normalized extent (schema cannot say this).
    if (out.crop_left + out.crop_width > 1.0 + 1e-12 ||
        out.crop_top + out.crop_height > 1.0 + 1e-12) {
        error = "geometry.crop must fit within the normalized source extent";
        return false;
    }

    const nlohmann::json &grain = recipe["grain"];
    out.grain_enabled = grain["enabled"].get<bool>();

    const nlohmann::json &output = recipe["output"];
    out.quality = output["quality"].get<int>();
    out.subsampling = output["subsampling"].get<std::string>();
    out.metadata_policy = output["metadataPolicy"].get<std::string>();
    out.has_long_edge = !output["longEdge"].is_null();
    if (out.has_long_edge) out.long_edge = uint32_t(output["longEdge"].get<int64_t>());

    // ---- engine capability checks (schema-valid but unexecutable => reject) ----
    if (out.engine_compatibility != identity.engine_compatibility) {
        error = "recipe engineCompatibility '" + out.engine_compatibility +
                "' is not accepted by this engine ('" +
                identity.engine_compatibility + "')";
        return false;
    }
    if (out.pipeline_id != identity.pipeline_id) {
        error = "pipeline '" + out.pipeline_id + "' is not available in this build";
        return false;
    }
    if (out.pipeline_version != identity.pipeline_version) {
        error = "pipeline version " + out.pipeline_version +
                " does not match this build (" + identity.pipeline_version + ")";
        return false;
    }
    if (out.has_camera_profile) {
        error = "execution.cameraProfile assets are not supported by this build "
                "(P0 uses decoder color data); cameraProfile must be null";
        return false;
    }
    if (out.source_kind == "renderedImage") {
        error = "renderedImage sources are not supported by this build (G1 "
                "covers cameraRaw only)";
        return false;
    }
    if (out.source_kind != "cameraRaw") {
        error = "source kind '" + out.source_kind +
                "' is not executable by this build";
        return false;
    }
    if (out.wb_mode == "notApplicable") {
        error = "whiteBalance mode notApplicable is only valid for renderedImage "
                "sources";
        return false;
    }
    if (!out.has_multipliers) {
        error = "cameraRaw recipes require resolved whiteBalance multipliers";
        return false;
    }
    if (out.grain_enabled) {
        error = "grain is not implemented in this build; disable it (docs/03 "
                "section 3.4 keeps grain off to isolate color)";
        return false;
    }
    if (out.has_long_edge && out.long_edge < 64) {
        error = "output.longEdge must be >= 64 when set";
        return false;
    }
    return true;
}

} // namespace pe
