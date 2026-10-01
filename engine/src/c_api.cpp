// C ABI boundary. Every entry point catches all exceptions (mapping them to
// PE_INTERNAL / PE_OUT_OF_MEMORY), sets out-handles to NULL before any work,
// and records a thread-local last error. Ownership rules follow the contract
// in photo_engine.h.
#include "photo_engine.h"
#include "buffer.h"
#include "cancel_flag.h"
#include "color.h"
#include "engine_impl.h"
#include "file_util.h"
#include "icc_srgb.h"
#include "jpeg_encoder.h"
#include "render.h"
#include "sha256.h"
#include <nlohmann/json.hpp>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <new>

using namespace pe;

namespace {

Engine *as_engine(pe_engine *e) { return reinterpret_cast<Engine *>(e); }
Source *as_source(pe_source *s) { return reinterpret_cast<Source *>(s); }
CancelFlag *as_cancel(pe_cancel_token *t) { return reinterpret_cast<CancelFlag *>(t); }

struct Blob {
    std::vector<uint8_t> data;
};

struct Image {
    // RGBA FP32 (alpha=1) with the encoded sRGB contract (color_contract=2).
    std::vector<float> rgba;
    uint32_t width = 0;
    uint32_t height = 0;
    uint64_t request_generation = 0;
};

pe_status to_status(int code) { return pe_status(code); }

pe_status map_status(int code, const char *stage, const std::string &message) {
    set_last_error(code, stage, message);
    return to_status(code);
}

// Shared pipeline for render + export: prepare (recipe/source/look), then
// render_to_pixels. Returns PE_OK and fills `output` on success. When
// model_out is non-null it receives the validated recipe model.
pe_status run_pipeline(Engine &engine, Source &source, const char *recipe_json,
                       size_t recipe_bytes, uint32_t long_edge_override,
                       uint64_t request_generation, CancelFlag *cancel,
                       RenderOutput &output, StageTimings &timings,
                       RecipeModel *model_out = nullptr) {
    if (!recipe_json || recipe_bytes == 0) {
        return map_status(kPE_INVALID_ARGUMENT, "pipeline", "recipe JSON span is empty");
    }
    RecipeModel model;
    LookPackage look;
    std::string error;
    int st = prepare_recipe(engine, source, recipe_json, recipe_bytes, model, look, error);
    if (st != kPE_OK) return to_status(st);

    RenderRequest request = make_render_request(model, look, long_edge_override);
    if (long_edge_override) {
        cancellation_point(cancel, "preview.verify_source");
        bool ok = false;
        const std::string current_hash = sha256_hex_of_file(source.path, &ok);
        if (!ok || current_hash != source.probe.sha256)
            return map_status(kPE_ASSET_MISMATCH, "preview.verify_source", "source content changed; reopen source");
        request.preview_cache = &source.preview_cache;
        request.upstream_key = nlohmann::json({{"source", current_hash},
            {"wb", model.wb_multipliers}, {"pipeline", engine.identity.pipeline_id},
            {"version", engine.identity.pipeline_version}, {"build", engine.identity.developer_build}}).dump();
    }


    int status = 0;
    if (!render_to_pixels(source.path, request, engine.limits, cancel, output,
                          timings, status, error)) {
        return map_status(status, "render", error);
    }
    (void)request_generation;
    if (model_out) *model_out = model;
    set_last_error(kPE_OK, "pipeline", "");
    return PE_OK;
}

} // namespace

// ---------------------------------------------------------------- engine ----

pe_status pe_engine_create(const char *config_json, size_t config_bytes,
                           pe_engine **out_engine) {
    if (!out_engine) return PE_INVALID_ARGUMENT;
    *out_engine = nullptr;
    try {
        Engine *engine = nullptr;
        std::string error;
        int st = engine_create_from_config(config_json, config_bytes, &engine, error);
        if (st != kPE_OK) {
            set_last_error(st, "engine_create", error);
            return to_status(st);
        }
        *out_engine = reinterpret_cast<pe_engine *>(engine);
        set_last_error(kPE_OK, "engine_create", "");
        return PE_OK;
    } catch (const std::bad_alloc &) {
        return map_status(kPE_OUT_OF_MEMORY, "engine_create", "out of memory");
    } catch (...) {
        return map_status(kPE_INTERNAL, "engine_create", "unexpected exception");
    }
}

void pe_engine_destroy(pe_engine *engine) { delete as_engine(engine); }

// ---------------------------------------------------------------- source ----

pe_status pe_source_open_local(pe_engine *engine, const char *path_utf8,
                               size_t path_bytes, pe_source **out_source) {
    if (!out_source) return PE_INVALID_ARGUMENT;
    *out_source = nullptr;
    if (!engine) return map_status(kPE_INVALID_ARGUMENT, "source_open", "engine is NULL");
    if (!path_utf8 || path_bytes == 0) {
        return map_status(kPE_INVALID_ARGUMENT, "source_open", "path span is empty");
    }
    try {
        std::string path(path_utf8, path_bytes);
        Source *src = nullptr;
        std::string error;
        int st = source_open(*as_engine(engine), path, &src, error);
        if (st != kPE_OK) {
            set_last_error(st, "source_open", error);
            return to_status(st);
        }
        *out_source = reinterpret_cast<pe_source *>(src);
        set_last_error(kPE_OK, "source_open", "");
        return PE_OK;
    } catch (const std::bad_alloc &) {
        return map_status(kPE_OUT_OF_MEMORY, "source_open", "out of memory");
    } catch (...) {
        return map_status(kPE_INTERNAL, "source_open", "unexpected exception");
    }
}

pe_status pe_source_info_json(pe_source *source, pe_blob **out_json) {
    if (!out_json) return PE_INVALID_ARGUMENT;
    *out_json = nullptr;
    if (!source) return map_status(kPE_INVALID_ARGUMENT, "source_info", "source is NULL");
    try {
        Blob *blob = new Blob();
        std::string json_text = probe_to_json(as_source(source)->probe);
        blob->data.assign(json_text.begin(), json_text.end());
        *out_json = reinterpret_cast<pe_blob *>(blob);
        set_last_error(kPE_OK, "source_info", "");
        return PE_OK;
    } catch (const std::bad_alloc &) {
        return map_status(kPE_OUT_OF_MEMORY, "source_info", "out of memory");
    } catch (...) {
        return map_status(kPE_INTERNAL, "source_info", "unexpected exception");
    }
}

void pe_source_release(pe_source *source) { delete as_source(source); }

// ---------------------------------------------------------------- cancel ----

pe_status pe_cancel_create(pe_cancel_token **out_token) {
    if (!out_token) return PE_INVALID_ARGUMENT;
    *out_token = nullptr;
    try {
        *out_token = reinterpret_cast<pe_cancel_token *>(new CancelFlag());
        set_last_error(kPE_OK, "cancel_create", "");
        return PE_OK;
    } catch (const std::bad_alloc &) {
        return map_status(kPE_OUT_OF_MEMORY, "cancel_create", "out of memory");
    }
}

void pe_cancel_request(pe_cancel_token *token) {
    if (token) as_cancel(token)->request();
}

void pe_cancel_release(pe_cancel_token *token) { delete as_cancel(token); }

// ---------------------------------------------------------------- render ----

pe_status pe_render_preview(pe_engine *engine, pe_source *source,
                            const char *recipe_json, size_t recipe_bytes,
                            const pe_preview_options *options,
                            pe_cancel_token *cancel, pe_image **out_image) {
    if (!out_image) return PE_INVALID_ARGUMENT;
    *out_image = nullptr;
    if (!engine) return map_status(kPE_INVALID_ARGUMENT, "render", "engine is NULL");
    if (!source) return map_status(kPE_INVALID_ARGUMENT, "render", "source is NULL");
    if (!options) return map_status(kPE_INVALID_ARGUMENT, "render", "options is NULL");
    if (options->struct_size != sizeof(pe_preview_options) ||
        options->abi_version != 1) {
        return map_status(kPE_INVALID_ARGUMENT, "render",
                          "preview options struct_size/abi_version unsupported");
    }
    if (options->long_edge_px == 0) {
        return map_status(kPE_INVALID_ARGUMENT, "render",
                          "long_edge_px must be > 0 (use pe_export_jpeg for full size)");
    }
    if (options->quality != 0) {
        return map_status(kPE_INVALID_ARGUMENT, "render",
                          "quality=fast is not implemented in v0; use 0 (final)");
    }
    try {
        auto &latest = as_source(source)->latest_preview_generation;
        uint64_t seen = latest.load();
        while (options->request_generation > seen &&
               !latest.compare_exchange_weak(seen, options->request_generation)) {}
        if (options->request_generation && options->request_generation < latest.load())
            return map_status(kPE_CANCELLED, "preview.generation", "superseded preview request");
        RenderOutput output;
        StageTimings timings;
        pe_status st = run_pipeline(*as_engine(engine), *as_source(source),
                                    recipe_json, recipe_bytes, options->long_edge_px,
                                    options->request_generation, as_cancel(cancel),
                                    output, timings);
        if (st != PE_OK) return st;
        cancellation_point(as_cancel(cancel), "preview.pack");
        auto image = std::make_unique<Image>();
        image->width = output.encoded.width;
        image->height = output.encoded.height;
        image->request_generation = options->request_generation;
        const size_t pixels = size_t(output.encoded.width) * output.encoded.height;
        image->rgba.resize(pixels * 4);
        for_each_chunk(pixels, as_cancel(cancel), "preview.pack.chunk", [&](size_t begin, size_t end) {
            for (size_t i = begin; i < end; ++i) {
                image->rgba[i*4] = output.encoded.data[i*3];
                image->rgba[i*4+1] = output.encoded.data[i*3+1];
                image->rgba[i*4+2] = output.encoded.data[i*3+2];
                image->rgba[i*4+3] = 1.0f;
            }
        });
        cancellation_point(as_cancel(cancel), "preview.ready");
        if (options->request_generation && options->request_generation < latest.load())
            return map_status(kPE_CANCELLED, "preview.generation", "superseded preview result");
        *out_image = reinterpret_cast<pe_image *>(image.release());
        set_last_error(kPE_OK, "render", "");
        return PE_OK;
    } catch (const Cancelled &) {
        return map_status(kPE_CANCELLED, "render", "cancelled while preparing preview");
    } catch (const std::bad_alloc &) {
        return map_status(kPE_OUT_OF_MEMORY, "render", "out of memory");
    } catch (...) {
        return map_status(kPE_INTERNAL, "render", "unexpected exception");
    }
}

pe_status pe_image_describe(const pe_image *image, pe_image_info *out_info) {
    if (!out_info) return PE_INVALID_ARGUMENT;
    if (out_info->struct_size != sizeof(pe_image_info) ||
        out_info->abi_version != 1) {
        return map_status(kPE_INVALID_ARGUMENT, "image_describe",
                          "image info struct_size/abi_version unsupported");
    }
    if (!image) return map_status(kPE_INVALID_ARGUMENT, "image_describe", "image is NULL");
    try {
        const Image *img = reinterpret_cast<const Image *>(image);
        out_info->width = img->width;
        out_info->height = img->height;
        out_info->row_stride_bytes = uint64_t(img->width) * 4 * sizeof(float);
        out_info->byte_length = uint64_t(img->width) * img->height * 4 * sizeof(float);
        out_info->pixel_format = 1; // interleaved native-endian RGBA FP32
        out_info->color_contract = 2; // srgb-display-v1 encoded (PE-G1-NOTE)
        out_info->orientation_state = 1; // baked/normalized
        out_info->reserved = 0;
        out_info->request_generation = img->request_generation;
        out_info->pixels = img->rgba.data();
        set_last_error(kPE_OK, "image_describe", "");
        return PE_OK;
    } catch (...) {
        return map_status(kPE_INTERNAL, "image_describe", "unexpected exception");
    }
}

void pe_image_release(pe_image *image) { delete reinterpret_cast<Image *>(image); }

// ---------------------------------------------------------------- export ----

pe_status pe_export_jpeg(pe_engine *engine, pe_source *source,
                         const char *recipe_json, size_t recipe_bytes,
                         const char *staging_path_utf8, size_t staging_path_bytes,
                         pe_cancel_token *cancel) {
    if (!engine) return map_status(kPE_INVALID_ARGUMENT, "export", "engine is NULL");
    if (!source) return map_status(kPE_INVALID_ARGUMENT, "export", "source is NULL");
    if (!staging_path_utf8 || staging_path_bytes == 0) {
        return map_status(kPE_INVALID_ARGUMENT, "export", "staging path is empty");
    }
    try {
        const std::string path(staging_path_utf8, staging_path_bytes);
        if (path_exists(path)) {
            return map_status(kPE_IO, "export",
                              "staging path already exists; refusing to overwrite");
        }
        Engine &eng = *as_engine(engine);

        // Recipe validation happens inside run_pipeline before heavy work, so
        // invalid recipes never reach decode or the filesystem (docs/04).
        RecipeModel model;
        RenderOutput output;
        StageTimings timings;
        std::string error;
        uint32_t long_edge_override = 0; // recipe.output.longEdge rules the export
        pe_status pstatus = run_pipeline(eng, *as_source(source), recipe_json,
                                         recipe_bytes, long_edge_override, 0,
                                         as_cancel(cancel), output, timings, &model);
        if (pstatus != PE_OK) return pstatus;

        const int status = export_rendered_jpeg(output, model, path, as_cancel(cancel), error);
        if (status != kPE_OK) return map_status(status, "export", error);
        set_last_error(kPE_OK, "export", "");
        return PE_OK;
    } catch (const std::bad_alloc &) {
        return map_status(kPE_OUT_OF_MEMORY, "export", "out of memory");
    } catch (...) {
        return map_status(kPE_INTERNAL, "export", "unexpected exception");
    }
}

// ------------------------------------------------------------- diagnostics ----

pe_status pe_last_error_json(pe_engine *engine, pe_blob **out_json) {
    if (!out_json) return PE_INVALID_ARGUMENT;
    *out_json = nullptr;
    (void)engine; // storage is thread-local; engine kept for ABI symmetry
    try {
        std::string json_text;
        int code = take_last_error_json(json_text);
        Blob *blob = new Blob();
        blob->data.assign(json_text.begin(), json_text.end());
        *out_json = reinterpret_cast<pe_blob *>(blob);
        return to_status(code);
    } catch (...) {
        return PE_INTERNAL;
    }
}

const uint8_t *pe_blob_data(const pe_blob *blob, size_t *out_bytes) {
    if (!blob) {
        if (out_bytes) *out_bytes = 0;
        return nullptr;
    }
    const Blob *b = reinterpret_cast<const Blob *>(blob);
    if (out_bytes) *out_bytes = b->data.size();
    return b->data.data();
}

void pe_blob_release(pe_blob *blob) { delete reinterpret_cast<Blob *>(blob); }
