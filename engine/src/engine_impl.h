// Engine internals shared by the C API boundary and the CLI (CLI links the
// C++ core directly for stage timings; the C ABI remains the mobile boundary).
#pragma once
#include "buffer.h"
#include "engine_limits.h"
#include "look.h"
#include "recipe.h"
#include "raw_adapter.h"
#include "render.h"
#include "schema_validate.h"
#include <memory>
#include <atomic>
#include <string>
#include <vector>

namespace pe {

struct EngineIdentity;
struct LookPackage;
class MiniSchemaValidator;

struct Engine {
    EngineLimits limits;
    std::vector<std::string> asset_search_paths;
    std::unique_ptr<MiniSchemaValidator> recipe_validator;
    std::unique_ptr<MiniSchemaValidator> look_validator;
    EngineIdentity identity;

    ~Engine();
};

// Creates a fully initialized engine (config parsing + schema compilation).
// On failure: out_engine == NULL, code+error set.
int engine_create_from_config(const char *config_json, size_t config_bytes,
                              Engine **out_engine, std::string &error);

struct Source {
    std::string path;
    SourceProbe probe;
    PreviewCache preview_cache;
    std::atomic<uint64_t> latest_preview_generation{0};
};

int source_open(Engine &engine, const std::string &path, Source **out_source,
                std::string &error);

// Parses + validates the recipe, verifies the source hash/kind, resolves the
// look package. Filled into `model` and `look` (look may be absent when
// amount==0? No: look package is always resolved to verify the pin).
int prepare_recipe(Engine &engine, Source &source, const char *recipe_json,
                   size_t recipe_bytes, RecipeModel &model,
                   LookPackage &look, std::string &error);

// Look resolution over the engine asset search paths (deterministic order).
bool find_and_load_look(Engine &engine, const RecipeModel &model, LookPackage &out,
                        std::string &error);

// Loads one specific look directory without a recipe pin (init-recipe path);
// all structural validation still applies.
bool find_and_load_look_unpinned(Engine &engine, const std::string &look_dir,
                                 const std::string &source_kind, LookPackage &out,
                                 std::string &error);

// Shared mapping for CLI, preview and export. An override of zero uses the recipe.
RenderRequest make_render_request(const RecipeModel &model, const LookPackage &look,
                                  uint32_t long_edge_override = 0,
                                  const char *audit_dir = nullptr);

// Encodes an already validated/rendered result into a staging file. Used by
// both CLI and C ABI; does not develop the source again or publish the file.
int export_rendered_jpeg(const RenderOutput &output, const RecipeModel &model,
                         const std::string &path, CancelFlag *cancel,
                         std::string &error);

// Prepare + render bundle used by the CLI report path.
struct RenderModelBundle {
    RecipeModel model;
    LookPackage look;
    RenderOutput output;
    StageTimings timings;
    int status = 0;
    std::vector<std::string> warnings;
};

bool prepare_and_render(Engine &engine, Source &source,
                        const std::vector<uint8_t> &recipe_bytes,
                        RenderModelBundle &bundle, std::string &error,
                        const char *audit_dir = nullptr, bool collect_diagnostics = false);

// Builds probe JSON (pretty-printed) for pe_source_info_json / CLI.
std::string probe_to_json(const SourceProbe &probe);

// Thread-local last error store (C ABI diagnostics).
void set_last_error(int code, const char *stage, const std::string &message);
int take_last_error_json(std::string &out_json);

// pe_status values (duplicated from photo_engine.h for core-internal use).
enum {
    kPE_OK = 0, kPE_UNSUPPORTED_SOURCE = 1, kPE_CORRUPT_SOURCE = 2,
    kPE_SOURCE_UNAVAILABLE = 3, kPE_COLOR_PROFILE_MISSING = 4,
    kPE_RECIPE_INVALID = 5, kPE_ASSET_MISMATCH = 6,
    kPE_PIPELINE_UNAVAILABLE = 7, kPE_RESOURCE_LIMIT = 8,
    kPE_OUT_OF_MEMORY = 9, kPE_CANCELLED = 10, kPE_IO = 11,
    kPE_INTERNAL = 12, kPE_INVALID_ARGUMENT = 13,
};
const char *pe_status_name(int code);

} // namespace pe
