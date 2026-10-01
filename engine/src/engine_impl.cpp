#include "engine_impl.h"
#include "embedded_schemas.h"
#include "file_util.h"
#include "sha256.h"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cstdio>
#include <filesystem>

namespace pe {

// ---- identity constants for this build (pipeline-affecting values pinned) ----
// PHOTO_ENGINE_DEVELOPER_BUILD comes from CMake and encodes the LibRaw pin.
#ifndef PHOTO_ENGINE_DEVELOPER_BUILD
#define PHOTO_ENGINE_DEVELOPER_BUILD "photo-engine-g1-libraw-unknown"
#endif

static const EngineIdentity kIdentity = {
    "photo-engine-major-1-proposed", // engineCompatibility (aligned with the
                                     // draft example's major-1 convention)
    "baseline-v0",                   // pipelineId (docs/03 section 3.1 P0)
    "0.1.0",                         // pipelineVersion
    PHOTO_ENGINE_DEVELOPER_BUILD,
};

Engine::~Engine() = default;

int engine_create_from_config(const char *config_json, size_t config_bytes,
                              Engine **out_engine, std::string &error) {
    *out_engine = nullptr;
    std::unique_ptr<Engine> engine(new Engine());
    engine->identity = kIdentity;

    if (config_json && config_bytes > 0) {
        nlohmann::json config;
        if (!strict_json_parse(config_json, config_bytes, engine->limits.json_limits(),
                               config, error)) {
            error = "engine config JSON: " + error;
            set_last_error(kPE_RECIPE_INVALID, "engine_create", error);
            return kPE_RECIPE_INVALID;
        }
        if (!engine->limits.apply_config(config, error)) {
            set_last_error(kPE_INVALID_ARGUMENT, "engine_create", error);
            return kPE_INVALID_ARGUMENT;
        }
        if (config.contains("assetSearchPaths")) {
            for (const auto &p : config["assetSearchPaths"]) {
                engine->asset_search_paths.push_back(p.get<std::string>());
            }
        }
    }

    engine->recipe_validator = std::make_unique<MiniSchemaValidator>();
    if (!engine->recipe_validator->load(
            nlohmann::json::parse(kRecipeSchemaJson, nullptr, false), error)) {
        error = "embedded recipe schema invalid: " + error;
        set_last_error(kPE_INTERNAL, "engine_create", error);
        return kPE_INTERNAL;
    }
    engine->look_validator = std::make_unique<MiniSchemaValidator>();
    if (!engine->look_validator->load(
            nlohmann::json::parse(kLookSchemaJson, nullptr, false), error)) {
        error = "embedded look schema invalid: " + error;
        set_last_error(kPE_INTERNAL, "engine_create", error);
        return kPE_INTERNAL;
    }
    *out_engine = engine.release();
    set_last_error(kPE_OK, "engine_create", "");
    return kPE_OK;
}

int source_open(Engine &engine, const std::string &path, Source **out_source,
                std::string &error) {
    *out_source = nullptr;
    if (path.empty()) {
        error = "source path is empty";
        set_last_error(kPE_INVALID_ARGUMENT, "source_open", error);
        return kPE_INVALID_ARGUMENT;
    }
    if (!path_exists(path)) {
        error = "source file does not exist or is not readable";
        set_last_error(kPE_SOURCE_UNAVAILABLE, "source_open", error);
        return kPE_SOURCE_UNAVAILABLE;
    }
    std::unique_ptr<Source> src(new Source());
    src->path = path;
    RawStatus status;
    if (!raw_probe(path, engine.limits, src->probe, status, error)) {
        set_last_error(int(status), "source_open", error);
        return int(status);
    }
    if (src->probe.kind == "linearDng" || src->probe.kind == "proRaw") {
        // Probe recognizes the kind; execution is a capability decision.
        error = "source kind '" + src->probe.kind +
                "' is recognized by probe but not executable by this build";
        set_last_error(kPE_UNSUPPORTED_SOURCE, "source_open", error);
        return kPE_UNSUPPORTED_SOURCE;
    }
    if (src->probe.colors != 3) {
        error = "decoder reports colors=" + std::to_string(src->probe.colors) +
                "; this build supports 3-color mosaic RAW only";
        set_last_error(kPE_UNSUPPORTED_SOURCE, "source_open", error);
        return kPE_UNSUPPORTED_SOURCE;
    }
    *out_source = src.release();
    set_last_error(kPE_OK, "source_open", "");
    return kPE_OK;
}

bool find_and_load_look(Engine &engine, const RecipeModel &model, LookPackage &out,
                        std::string &error) {
    namespace fs = std::filesystem;
    for (const std::string &root : engine.asset_search_paths) {
        std::vector<std::string> candidates;
        if (path_exists(root + "/manifest.json")) candidates.push_back(root);
        std::error_code ec;
        if (fs::is_directory(fs::u8path(root), ec)) {
            std::vector<std::string> subdirs;
            fs::directory_iterator it(fs::u8path(root), ec), end;
            for (; !ec && it != end; it.increment(ec)) {
                if (ec) break;
                std::string sub = it->path().u8string();
                if (path_exists(sub + "/manifest.json")) subdirs.push_back(sub);
            }
            std::sort(subdirs.begin(), subdirs.end());
            candidates.insert(candidates.end(), subdirs.begin(), subdirs.end());
        }
        for (const std::string &dir : candidates) {
            // Cheap pre-filter: manifest hash must equal the recipe pin before
            // any deeper validation runs.
            bool ok = false;
            std::string h = sha256_hex_of_file(dir + "/manifest.json", &ok);
            if (!ok || h != model.look_manifest_sha256) continue;
            if (load_look_package(dir, engine.limits, *engine.look_validator,
                                  model.pipeline_id, model.source_kind,
                                  model.look_manifest_sha256, out, error)) {
                if (out.id != model.look_id || out.version != model.look_version) {
                    error = "look package identity mismatch (recipe pins " +
                            model.look_id + " " + model.look_version + ", package is " +
                            out.id + " " + out.version + ")";
                    set_last_error(kPE_ASSET_MISMATCH, "resolve_look", error);
                    return false;
                }
                set_last_error(kPE_OK, "resolve_look", "");
                return true;
            }
            set_last_error(kPE_ASSET_MISMATCH, "resolve_look", error);
            return false; // pinned package found but invalid: never fall back
        }
    }
    error = "look package with manifest sha256 " + model.look_manifest_sha256 +
            " not found in engine asset search paths";
    set_last_error(kPE_ASSET_MISMATCH, "resolve_look", error);
    return false;
}

int prepare_recipe(Engine &engine, Source &source, const char *recipe_json,
                   size_t recipe_bytes, RecipeModel &model, LookPackage &look,
                   std::string &error) {
    SchemaValidators validators{engine.recipe_validator.get(),
                                engine.look_validator.get()};
    nlohmann::json recipe;
    if (!parse_recipe_json(recipe_json, recipe_bytes, engine.limits, validators,
                           recipe, error)) {
        set_last_error(kPE_RECIPE_INVALID, "validate_recipe", error);
        return kPE_RECIPE_INVALID;
    }
    if (!validate_recipe_semantics(recipe, engine.identity, model, error)) {
        set_last_error(kPE_RECIPE_INVALID, "validate_recipe", error);
        return kPE_RECIPE_INVALID;
    }
    // Source pin: hash and kind must match what the file actually is now.
    if (source.probe.sha256 != model.source_sha256) {
        error = "source hash mismatch (recipe pins " + model.source_sha256 +
                ", file hashes to " + source.probe.sha256 + ")";
        set_last_error(kPE_ASSET_MISMATCH, "verify_source", error);
        return kPE_ASSET_MISMATCH;
    }
    if (source.probe.kind != model.source_kind) {
        error = "source kind mismatch (recipe says " + model.source_kind +
                ", probe says " + source.probe.kind + ")";
        set_last_error(kPE_RECIPE_INVALID, "verify_source", error);
        return kPE_RECIPE_INVALID;
    }
    if (!find_and_load_look(engine, model, look, error)) {
        return kPE_ASSET_MISMATCH;
    }
    set_last_error(kPE_OK, "prepare_recipe", "");
    return kPE_OK;
}

bool find_and_load_look_unpinned(Engine &engine, const std::string &look_dir,
                                 const std::string &source_kind, LookPackage &out,
                                 std::string &error) {
    if (!path_exists(look_dir + "/manifest.json")) {
        error = "no manifest.json found in look directory: " + look_dir;
        set_last_error(kPE_ASSET_MISMATCH, "resolve_look", error);
        return false;
    }
    if (!load_look_package(look_dir, engine.limits, *engine.look_validator,
                           engine.identity.pipeline_id, source_kind,
                           /*manifest_sha256_expected=*/"", out, error)) {
        set_last_error(kPE_ASSET_MISMATCH, "resolve_look", error);
        return false;
    }
    set_last_error(kPE_OK, "resolve_look", "");
    return true;
}

RenderRequest make_render_request(const RecipeModel &model, const LookPackage &look,
                                  uint32_t long_edge_override, const char *audit_dir) {
    RenderRequest request;
    request.exposure_ev = model.exposure_ev;
    for (int i = 0; i < 4; i++)
        request.wb_multipliers[i] = model.wb_multipliers[i];
    request.look = &look;
    request.look_amount = model.look_amount;
    request.crop_left = model.crop_left;
    request.crop_top = model.crop_top;
    request.crop_width = model.crop_width;
    request.crop_height = model.crop_height;
    request.rotation_quarter_turns = model.rotation_quarter_turns;
    request.flip_horizontal = model.flip_horizontal;
    request.long_edge = long_edge_override ? long_edge_override :
        (model.has_long_edge ? model.long_edge : 0);
    request.audit_dir = audit_dir; // TEST-ONLY checkpoint dumps (nullptr = off)
    return request;
}

bool prepare_and_render(Engine &engine, Source &source,
                        const std::vector<uint8_t> &recipe_bytes,
                        RenderModelBundle &bundle, std::string &error,
                        const char *audit_dir, bool collect_diagnostics) {
    bundle.warnings.clear();
    int st = prepare_recipe(engine, source,
                            reinterpret_cast<const char *>(recipe_bytes.data()),
                            recipe_bytes.size(), bundle.model, bundle.look, error);
    bundle.status = st;
    if (st != kPE_OK) return false;
    if (bundle.model.developer_build != engine.identity.developer_build) {
        bundle.warnings.push_back(
            "recipe developerBuild differs from this engine build; pixel results "
            "may not match the original render");
    }
    RenderRequest request = make_render_request(bundle.model, bundle.look, 0, audit_dir);
    request.collect_diagnostics = collect_diagnostics;
    int status = 0;
    if (!render_to_pixels(source.path, request, engine.limits, nullptr,
                          bundle.output, bundle.timings, status, error)) {
        bundle.status = status;
        return false;
    }
    bundle.status = kPE_OK;
    return true;
}

std::string probe_to_json(const SourceProbe &p) {
    nlohmann::json j;
    j["fileSize"] = p.file_size;
    j["sha256"] = p.sha256;
    j["kind"] = p.kind;
    j["librawVersion"] = p.libraw_version;
    j["camera"] = {{"make", p.make},
                   {"model", p.model},
                   {"normalizedMake", p.normalized_make},
                   {"normalizedModel", p.normalized_model}};
    j["format"] = {{"dngVersion", p.dng_version},
                   {"rawCount", p.raw_count},
                   {"colors", p.colors},
                   {"filters", p.filters},
                   {"filtersHex", [&] {
                        char buf[32];
                        std::snprintf(buf, sizeof(buf), "%llx",
                                      (unsigned long long)p.filters);
                        return std::string("0x") + buf;
                    }()}};
    j["dimensions"] = {{"rawWidth", p.raw_width},
                       {"rawHeight", p.raw_height},
                       {"width", p.width},
                       {"height", p.height},
                       {"topMargin", p.top_margin},
                       {"leftMargin", p.left_margin},
                       {"iwidth", p.iwidth},
                       {"iheight", p.iheight}};
    j["orientation"] = {{"decoderFlip", p.flip},
                        {"note", "dcraw flip bitmask; engine normalizes before look"}};
    j["levels"] = {{"blackLevel", p.black_level}, {"whiteLevel", p.white_level}};
    j["whiteBalance"] = {{"asShot", {p.cam_mul[0], p.cam_mul[1], p.cam_mul[2], p.cam_mul[3]}},
                         {"preMultiplier", {p.pre_mul[0], p.pre_mul[1], p.pre_mul[2], p.pre_mul[3]}},
                         {"order", "R,G,B,G2"}};
    j["thumbnail"] = {{"present", p.has_thumbnail}, {"isJpeg", p.thumbnail_is_jpeg},
                      {"note", "embedded JPEG is never used as image data"}};
    j["exifDisplay"] = {{"iso", p.iso_speed}, {"shutter", p.shutter},
                        {"aperture", p.aperture}};
    return j.dump(2);
}

// ---- thread-local last error ----
namespace {
struct LastError {
    int code = kPE_OK;
    std::string stage;
    std::string message;
};
LastError &last_error_slot() {
    static thread_local LastError slot;
    return slot;
}
} // namespace

void set_last_error(int code, const char *stage, const std::string &message) {
    LastError &slot = last_error_slot();
    slot.code = code;
    slot.stage = stage ? stage : "";
    slot.message = message;
}

int take_last_error_json(std::string &out_json) {
    LastError &slot = last_error_slot();
    nlohmann::json j;
    j["code"] = pe_status_name(slot.code);
    j["stage"] = slot.stage;
    j["message"] = slot.message;
    out_json = j.dump();
    return slot.code;
}

const char *pe_status_name(int code) {
    switch (code) {
    case kPE_OK: return "PE_OK";
    case kPE_UNSUPPORTED_SOURCE: return "PE_UNSUPPORTED_SOURCE";
    case kPE_CORRUPT_SOURCE: return "PE_CORRUPT_SOURCE";
    case kPE_SOURCE_UNAVAILABLE: return "PE_SOURCE_UNAVAILABLE";
    case kPE_COLOR_PROFILE_MISSING: return "PE_COLOR_PROFILE_MISSING";
    case kPE_RECIPE_INVALID: return "PE_RECIPE_INVALID";
    case kPE_ASSET_MISMATCH: return "PE_ASSET_MISMATCH";
    case kPE_PIPELINE_UNAVAILABLE: return "PE_PIPELINE_UNAVAILABLE";
    case kPE_RESOURCE_LIMIT: return "PE_RESOURCE_LIMIT";
    case kPE_OUT_OF_MEMORY: return "PE_OUT_OF_MEMORY";
    case kPE_CANCELLED: return "PE_CANCELLED";
    case kPE_IO: return "PE_IO";
    case kPE_INTERNAL: return "PE_INTERNAL";
    case kPE_INVALID_ARGUMENT: return "PE_INVALID_ARGUMENT";
    default: return "PE_INTERNAL";
    }
}

} // namespace pe
